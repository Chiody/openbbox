"""
OpenBBox FastAPI Server — Enhanced with diff stats, search, and richer API.
Serves the three-column workspace and provides real-time data push via WebSocket.
"""

from __future__ import annotations

import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

import uuid

from fastapi import FastAPI, File, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from pydantic import BaseModel

from adapters.registry import get_adapter_by_name, get_all_adapters, get_available_adapters
from core.diff_parser import calculate_diff_stats, generate_change_summary
from core.exporter import PromptExporter
from core.matcher import TemporalMatcher
from core.models import PulseNode, SourceIDE
from core.storage import PulseStorage

logger = logging.getLogger("openbbox.server")

app = FastAPI(
    title="OpenBBox API",
    description="脉络 | OpenBBox — The DNA of AI-Driven Development",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

storage = PulseStorage()
connected_clients: list[WebSocket] = []
_scan_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="scan")

DASHBOARD_DIR = Path(__file__).parent.parent / "dashboard"
DOCS_DIR = Path(__file__).parent.parent / "docs"
ASSETS_DIR = Path.home() / ".openbbox" / "assets"
ASSETS_DIR.mkdir(parents=True, exist_ok=True)


# ── Health & System ──

@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "openbbox", "version": "0.2.0"}


@app.get("/api/stats")
async def get_stats():
    """Get global statistics."""
    total_nodes = storage.count_nodes()
    total_projects = len(storage.list_dna())
    nodes = storage.list_nodes(limit=10000)

    # Calculate aggregate stats
    total_files_changed = 0
    total_additions = 0
    total_deletions = 0
    ide_counts: dict[str, int] = {}

    for node in nodes:
        total_files_changed += len(node.execution.affected_files)
        for diff in node.execution.diffs:
            for line in diff.hunk.split("\n"):
                if line.startswith("+") and not line.startswith("+++"):
                    total_additions += 1
                elif line.startswith("-") and not line.startswith("---"):
                    total_deletions += 1
        ide = node.source.ide.value
        ide_counts[ide] = ide_counts.get(ide, 0) + 1

    return {
        "total_prompts": total_nodes,
        "total_projects": total_projects,
        "total_files_changed": total_files_changed,
        "total_additions": total_additions,
        "total_deletions": total_deletions,
        "ide_distribution": ide_counts,
    }


# ── Projects ──

@app.get("/api/projects")
async def list_projects():
    """List all tracked projects, aggregated from PulseNodes."""
    all_nodes = storage.list_nodes(limit=10000)
    project_map: dict[str, dict] = {}

    for node in all_nodes:
        key = node.project_name or node.project_id or "(Uncategorized)"
        if key not in project_map:
            project_map[key] = {
                "project_name": node.project_name or key,
                "project_path": node.project_id,
                "source_ides": set(),
                "total_prompts": 0,
                "first_timestamp": node.timestamp,
                "last_timestamp": node.timestamp,
            }
        project_map[key]["total_prompts"] += 1
        project_map[key]["source_ides"].add(node.source.ide.value)
        if node.timestamp < project_map[key]["first_timestamp"]:
            project_map[key]["first_timestamp"] = node.timestamp
        if node.timestamp > project_map[key]["last_timestamp"]:
            project_map[key]["last_timestamp"] = node.timestamp

    projects = []
    for key, info in sorted(project_map.items(), key=lambda x: -x[1]["total_prompts"]):
        projects.append({
            "dna_id": info["project_path"] or key,
            "project_name": info["project_name"],
            "project_path": info["project_path"],
            "source_ides": sorted(info["source_ides"]),
            "total_prompts": info["total_prompts"],
            "created_at": info["first_timestamp"].isoformat(),
            "updated_at": info["last_timestamp"].isoformat(),
        })

    return {"projects": projects}


# ── Nodes (PulseNodes) ──

@app.get("/api/nodes")
async def list_nodes(
    project_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """List PulseNodes with optional project filter."""
    nodes = storage.list_nodes(project_id=project_id, limit=limit, offset=offset)
    total = storage.count_nodes(project_id=project_id)
    return {
        "total": total,
        "nodes": [_node_to_dict(n) for n in nodes],
    }


@app.get("/api/nodes/{node_id}")
async def get_node(node_id: str):
    """Get a single PulseNode with full details."""
    node = storage.get_node(node_id)
    if not node:
        return {"error": "Node not found"}
    result = _node_to_dict(node)
    # Add diff statistics
    if node.execution.diffs:
        stats = calculate_diff_stats(node.execution.diffs)
        result["diff_stats"] = stats.to_dict()
        result["change_summary"] = generate_change_summary(node.execution.diffs)
    return result


@app.get("/api/search")
async def search_nodes(
    q: str = Query(..., min_length=1),
    limit: int = Query(50, ge=1, le=200),
):
    """Search nodes by prompt content."""
    all_nodes = storage.list_nodes(limit=10000)
    query_lower = q.lower()
    matched = [
        n for n in all_nodes
        if query_lower in n.intent.raw_prompt.lower()
        or query_lower in n.intent.clean_title.lower()
        or query_lower in n.execution.ai_response.lower()
    ]
    return {
        "query": q,
        "total": len(matched),
        "nodes": [_node_to_dict(n) for n in matched[:limit]],
    }


# ── Scan / Sniff ──

def _ide_name_to_enum(name: str) -> SourceIDE:
    mapping = {
        "cursor": SourceIDE.CURSOR,
        "trae": SourceIDE.TRAE,
        "claudecode": SourceIDE.CLAUDECODE,
        "vscode": SourceIDE.VSCODE,
        "codex": SourceIDE.CODEX,
    }
    return mapping.get(name.lower(), SourceIDE.UNKNOWN)


CLOUD_ONLY_ADAPTERS = {"ClaudeDesktop"}

@app.get("/api/adapters")
async def list_adapters_v2():
    """List all adapters with detection status and DB info."""
    all_adapters = get_all_adapters()
    return {
        "adapters": [
            {
                "name": a.name(),
                "detected": a.detect(),
                "db_count": len(a.get_db_paths()) if a.detect() else 0,
                "db_paths": a.get_db_paths()[:5] if a.detect() else [],
                "cloud_only": a.name() in CLOUD_ONLY_ADAPTERS,
            }
            for a in all_adapters
        ]
    }


import queue as _queue


def _scan_worker(adapter_names: list[str], progress_q: _queue.Queue):
    """
    Run scan in a worker thread, pushing progress events to a queue.
    Uses each adapter's standard sniff strategy for layer-by-layer scanning.
    """
    all_adapters = get_all_adapters()

    targets = []
    if adapter_names:
        for name in adapter_names:
            a = get_adapter_by_name(name)
            if a and a.detect():
                targets.append(a)
    else:
        targets = [a for a in all_adapters if a.detect()]

    total_adapters = len(targets)
    progress_q.put({
        "type": "progress",
        "step": "init",
        "message": f"Starting scan for {total_adapters} IDE(s)...",
        "detail": ", ".join(a.name() for a in targets),
        "percent": 0,
    })

    discovered: dict[str, dict] = {}
    scan_errors: list[str] = []

    for idx, adapter in enumerate(targets):
        adapter_name = adapter.name()
        base_pct = int((idx / total_adapters) * 80)

        # Show strategy layers for this adapter
        strategy = adapter.get_sniff_strategy()
        layer_names = [l.name for l in strategy]

        progress_q.put({
            "type": "progress",
            "step": "adapter_start",
            "message": f"Scanning {adapter_name}...",
            "detail": f"Strategy: {len(strategy)} layer(s) — {', '.join(layer_names)}",
            "adapter": adapter_name,
            "adapter_index": idx + 1,
            "adapter_total": total_adapters,
            "percent": base_pct,
        })

        def on_layer_progress(event, _adapter=adapter_name, _base=base_pct):
            step = event.get("step", "")
            if step == "layer_start":
                progress_q.put({
                    "type": "progress",
                    "step": "layer_start",
                    "adapter": _adapter,
                    "message": f"{_adapter} → {event['layer_name']}: {event['layer_desc']}",
                    "detail": f"Speed: {event.get('speed', '?')}",
                    "percent": _base + 5,
                })
            elif step == "layer_done":
                projs = event.get("projects_found", [])
                progress_q.put({
                    "type": "progress",
                    "step": "layer_done",
                    "adapter": _adapter,
                    "message": f"{_adapter} → {event['layer_name']}: {event['conversations_found']} conversations, {len(projs)} projects ({event['elapsed_ms']}ms)",
                    "detail": ", ".join(projs[:8]) + ("..." if len(projs) > 8 else ""),
                    "percent": _base + 10,
                })
            elif step == "layer_skip":
                progress_q.put({
                    "type": "progress",
                    "step": "layer_skip",
                    "adapter": _adapter,
                    "message": f"{_adapter} → {event['layer_name']}: {event.get('reason', 'skipped')}",
                    "percent": _base + 10,
                })
            elif step == "layer_error":
                progress_q.put({
                    "type": "progress",
                    "step": "layer_error",
                    "adapter": _adapter,
                    "message": f"{_adapter} → {event['layer_name']}: ERROR — {event.get('error', '')}",
                    "percent": _base + 10,
                })

        try:
            conversations = adapter.poll_with_progress(
                since=None, on_progress=on_layer_progress,
            )
            conv_count = len(conversations)

            progress_q.put({
                "type": "progress",
                "step": "adapter_done",
                "message": f"{adapter_name}: total {conv_count} conversation(s)",
                "adapter": adapter_name,
                "conversations_found": conv_count,
                "percent": int(((idx + 1) / total_adapters) * 80),
            })

            for convo in conversations:
                proj_name = convo.project_name or "(Unknown)"
                proj_path = convo.project_path or ""
                key = f"{adapter_name}::{proj_name}"

                if key not in discovered:
                    discovered[key] = {
                        "project_name": proj_name,
                        "project_path": proj_path,
                        "ide": adapter_name,
                        "prompt_count": 0,
                        "first_prompt_preview": "",
                    }
                discovered[key]["prompt_count"] += 1
                if not discovered[key]["first_prompt_preview"] and convo.prompt:
                    clean = convo.prompt[:120].replace("\n", " ").strip()
                    discovered[key]["first_prompt_preview"] = clean

        except Exception as e:
            err_msg = f"{adapter_name}: {str(e)[:100]}"
            scan_errors.append(err_msg)
            progress_q.put({
                "type": "progress",
                "step": "adapter_error",
                "message": f"Error scanning {adapter_name}",
                "detail": str(e)[:100],
                "adapter": adapter_name,
                "percent": int(((idx + 1) / total_adapters) * 80),
            })

    progress_q.put({
        "type": "progress",
        "step": "checking_imported",
        "message": "Checking existing imports...",
        "percent": 85,
    })

    existing_nodes = storage.list_nodes(limit=10000)
    existing_projects = set()
    for n in existing_nodes:
        if n.project_name:
            existing_projects.add(n.project_name)

    results = []
    for key, info in sorted(discovered.items(), key=lambda x: -x[1]["prompt_count"]):
        results.append({
            **info,
            "already_imported": info["project_name"] in existing_projects,
            "key": key,
        })

    progress_q.put({
        "type": "result",
        "total_discovered": len(results),
        "projects": results,
        "errors": scan_errors,
        "percent": 100,
    })


@app.get("/api/scan/discover")
async def scan_discover_sse(
    adapters: list[str] = Query(default=[]),
):
    """
    SSE endpoint: streams scan progress events, then final results.
    Uses Server-Sent Events so the frontend gets real-time updates.
    """
    progress_q: _queue.Queue = _queue.Queue()
    loop = asyncio.get_event_loop()

    loop.run_in_executor(_scan_executor, _scan_worker, adapters, progress_q)

    async def event_stream():
        while True:
            try:
                event = await asyncio.wait_for(
                    loop.run_in_executor(None, progress_q.get, True, 2.0),
                    timeout=5.0,
                )
            except (asyncio.TimeoutError, _queue.Empty):
                yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
                continue

            yield f"data: {json.dumps(event)}\n\n"

            if event.get("type") == "result":
                break

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


class ImportRequest(BaseModel):
    projects: list[dict]


def _do_scan_import(projects_list: list[dict]) -> dict:
    """Run import in a worker thread."""
    imported_count = 0
    errors: list[str] = []

    for proj in projects_list:
        ide_name = proj.get("ide", "")
        proj_name = proj.get("project_name", "")
        if not ide_name or not proj_name:
            continue

        adapter = get_adapter_by_name(ide_name)
        if not adapter:
            errors.append(f"Adapter not found: {ide_name}")
            continue

        try:
            conversations = adapter.poll_new(since=None)
            matcher = TemporalMatcher()
            ide_enum = _ide_name_to_enum(ide_name)

            matched = [c for c in conversations if (c.project_name or "(Unknown)") == proj_name]

            for convo in matched:
                matcher.add_prompt(convo, ide_enum)

            nodes = matcher.flush()
            for node in nodes:
                storage.save_node(node)
            imported_count += len(nodes)
        except Exception as e:
            errors.append(f"{ide_name}/{proj_name}: {str(e)[:100]}")

    return {
        "imported": imported_count,
        "errors": errors,
    }


@app.post("/api/scan/import")
async def scan_import(req: ImportRequest):
    """
    Import selected projects from scan results.
    Runs in a thread pool to avoid blocking.
    """
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        _scan_executor, _do_scan_import, req.projects
    )
    return result


# ── Project Memos ──

class MemoCreate(BaseModel):
    project_key: str
    content: str
    memo_type: str = "note"
    pinned: bool = False
    meta: Optional[dict] = None

class MemoUpdate(BaseModel):
    content: Optional[str] = None
    pinned: Optional[bool] = None
    meta: Optional[dict] = None


@app.get("/api/memos/{project_key}")
async def list_memos(project_key: str, memo_type: Optional[str] = Query(None)):
    memos = storage.list_memos(project_key, memo_type=memo_type)
    return {"memos": memos}


@app.post("/api/memos")
async def create_memo(req: MemoCreate):
    memo = storage.add_memo(req.project_key, req.content, memo_type=req.memo_type,
                            pinned=req.pinned, meta=req.meta)
    return memo


@app.put("/api/memos/{memo_id}")
async def update_memo(memo_id: int, req: MemoUpdate):
    memo = storage.update_memo(memo_id, content=req.content, pinned=req.pinned, meta=req.meta)
    if not memo:
        return {"error": "Memo not found"}
    return memo


@app.delete("/api/memos/{memo_id}")
async def delete_memo(memo_id: int):
    ok = storage.delete_memo(memo_id)
    return {"deleted": ok}


# ── Project README ──

class ReadmeSave(BaseModel):
    project_key: str
    markdown: str
    blocks: Optional[list] = None
    template_id: str = "default"


@app.get("/api/readme/{project_key}")
async def get_readme(project_key: str):
    data = storage.get_readme(project_key)
    if not data:
        return {"project_key": project_key, "markdown": "", "blocks": [], "template_id": "default", "updated_at": None}
    return data


@app.post("/api/readme")
async def save_readme(req: ReadmeSave):
    return storage.save_readme(req.project_key, req.markdown, req.blocks, req.template_id)


@app.get("/api/readme/{project_key}/autofill")
async def readme_autofill(project_key: str):
    """Auto-generate README content from project pulse data and memos."""
    all_nodes = storage.list_nodes(limit=10000)
    proj_nodes = [n for n in all_nodes if (n.project_name or "") == project_key]
    memos = storage.list_memos(project_key)

    features = []
    for n in proj_nodes[:20]:
        title = n.intent.clean_title or n.intent.raw_prompt[:60]
        title = title.replace("<user_query>", "").replace("</user_query>", "").strip()
        if len(title) > 5:
            features.append({
                "title": title[:80],
                "timestamp": n.timestamp.isoformat(),
                "ide": n.source.ide.value,
            })

    deploy_memos = [m for m in memos if m.get("memo_type") == "deploy"]
    note_memos = [m for m in memos if m.get("memo_type") == "note"]

    return {
        "project_key": project_key,
        "total_prompts": len(proj_nodes),
        "features": features,
        "deploy_memos": deploy_memos,
        "note_memos": note_memos,
        "ides_used": list(set(n.source.ide.value for n in proj_nodes)),
    }


# ── Export ──

@app.get("/api/export/markdown")
async def export_markdown(
    project_id: Optional[str] = Query(None),
    project_name: str = Query("OpenBBox Project"),
):
    """Export all prompts as a Markdown Director's Script."""
    nodes = storage.list_nodes(project_id=project_id, limit=10000)
    md = PromptExporter.to_markdown(nodes, project_name)
    return PlainTextResponse(content=md, media_type="text/markdown")


@app.get("/api/export/json")
async def export_json(
    project_id: Optional[str] = Query(None),
    project_name: str = Query("OpenBBox Project"),
):
    """Export all prompts as a .pulse JSON file."""
    nodes = storage.list_nodes(project_id=project_id, limit=10000)
    data = PromptExporter.to_json(nodes, project_name)
    return PlainTextResponse(content=data, media_type="application/json")


@app.get("/api/export/prompts")
async def export_prompts(project_id: Optional[str] = Query(None)):
    """Export only the clean prompt list (for copy-paste replication)."""
    nodes = storage.list_nodes(project_id=project_id, limit=10000)
    text = PromptExporter.to_prompt_list(nodes)
    return PlainTextResponse(content=text, media_type="text/plain")


# ── WebSocket ──

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    connected_clients.append(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        if ws in connected_clients:
            connected_clients.remove(ws)


async def broadcast_new_node(node: PulseNode):
    """Push a new PulseNode to all connected WebSocket clients."""
    data = json.dumps({"type": "new_node", "node": _node_to_dict(node)})
    disconnected = []
    for ws in connected_clients:
        try:
            await ws.send_text(data)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        if ws in connected_clients:
            connected_clients.remove(ws)


# ── Image Upload ──

@app.post("/api/upload")
async def upload_image(file: UploadFile = File(...)):
    """Upload an image, store in ~/.openbbox/assets/, return URL."""
    ext = Path(file.filename or "img.png").suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"):
        ext = ".png"
    name = f"{uuid.uuid4().hex[:12]}{ext}"
    dest = ASSETS_DIR / name
    content = await file.read()
    dest.write_bytes(content)
    return {"url": f"/assets/{name}", "filename": name, "size": len(content)}


# ── Static files ──

@app.get("/")
async def serve_dashboard():
    index = DASHBOARD_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return HTMLResponse("<h1>OpenBBox</h1><p>Dashboard not found.</p>")


@app.get("/landing")
async def serve_landing():
    index = DOCS_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return HTMLResponse("<h1>OpenBBox</h1><p>Landing page not found.</p>")


if DASHBOARD_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(DASHBOARD_DIR)), name="dashboard")

app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")


# ── Helpers ──

def _node_to_dict(node: PulseNode) -> dict:
    return {
        "id": node.id,
        "timestamp": node.timestamp.isoformat(),
        "project_id": node.project_id,
        "project_name": node.project_name,
        "source": {
            "ide": node.source.ide.value,
            "model_name": node.source.model_name,
            "session_id": node.source.session_id,
        },
        "intent": {
            "raw_prompt": node.intent.raw_prompt,
            "clean_title": node.intent.clean_title,
            "context_files": node.intent.context_files,
        },
        "execution": {
            "ai_response": node.execution.ai_response,
            "reasoning": node.execution.reasoning,
            "diffs": [
                {
                    "file_path": d.file_path,
                    "hunk": d.hunk,
                    "change_type": d.change_type,
                }
                for d in node.execution.diffs
            ],
            "affected_files": node.execution.affected_files,
        },
        "status": node.status.value,
        "token_usage": node.token_usage,
    }
