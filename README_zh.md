<p align="center">
  <h1 align="center">🧬 脉络 | OpenBBox</h1>
  <p align="center">
    <strong>打开 AI 编程的黑匣子。追踪项目的 DNA 演进脉络。</strong>
  </p>
  <p align="center">
    <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-cyan.svg" alt="License: MIT"></a>
    <a href="https://python.org"><img src="https://img.shields.io/badge/Python-3.9%2B-blue?logo=python" alt="Python 3.9+"></a>
    <a href="http://makeapullrequest.com"><img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg" alt="PRs Welcome"></a>
    <a href="./Dockerfile"><img src="https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker" alt="Docker"></a>
  </p>
  <p align="center">
    <a href="./README.md">English</a> · <a href="./README_zh.md">简体中文</a>
  </p>
</p>

---

<p align="center">
  <img src="./docs/screenshots/dashboard.png" alt="OpenBBox 三列工作台" width="100%">
  <br>
  <em>三列工作台：提示词列表 → AI 回复 → 代码 Diff 与行号</em>
</p>

---

## ⚡️ 为什么需要脉络？

用 AI 写代码很快，但它是一个**黑匣子**。

1. **失忆症** — 两周前那个修复复杂 Bug 的提示词，你还记得吗？
2. **信息孤岛** — Cursor 里的好提示词，没法在 Trae 或 Claude Code 里复用。
3. **黑盒问题** — 看着 Git Diff，却忘了是什么指令导致了这些变更。

**脉络（OpenBBox）** 是一个通用的侧挂观察者。它嗅探你本地的 AI IDE 日志和 Git Diff，构建一条永久的、可复用的**项目 DNA 序列** — 从意图到代码的完整脉络。

> *"不要只是用 AI 写代码。去指挥它，追踪它，沉淀它。"*

---

## ✨ 核心特性

| 特性 | 描述 |
|:-----|:-----|
| 🧬 **提示词脉络** | 每条提示词都被捕获为干净、可搜索的"基因代码" — 去除聊天噪音 |
| 📊 **演进映射** | 在统一时间轴中看到"因"（提示词）和"果"（代码变更） |
| 🔄 **多 IDE 同步** | 一个面板管理 Cursor、Trae、Claude Code、VS Code、Kiro、Windsurf、Codex |
| 💾 **资产导出** | 将你的"导演剧本"导出为 Markdown 或 `.pulse` JSON 格式复用 |
| 🔒 **隐私优先** | 100% 本地运行。数据**永远不会**离开你的电脑 |
| 🌐 **中英双语** | 一键切换中英文界面 |

---

## 📺 实战案例：从意图到代码的脉络

想象你在 **项目 A** 中用 Cursor 构建了一个安全认证模块。有了脉络，你不只是复制代码 — 你导出 `.pulse` 序列，即引导 AI 的完整提示词流程。然后在 **项目 B** 中用 Trae "回放"这个逻辑。

**这才是真正的杠杆。代码是结果，脉络才是资产。**

| # | 意图（提示词） | 演进（代码） | 影响 |
|:--|:-------------|:-----------|:-----|
| 01 | "初始化 FastAPI 骨架，集成 WebSocket 路由" | 创建 `main.py`，建立连接池 | 架构基础 |
| 02 | "添加 AES-256 加密中间件，确保端到端安全" | `security.py` 加解密钩子 | 安全资产 |
| 03 | "重构：将消息存储从内存改为 Redis 异步持久化" | `db.py`、`config.py` 更新 | 性能优化 |
| 04 | "添加 JWT 认证和刷新令牌轮换" | `auth.py` 注入，12 个文件更新 | 认证体系 |
| 05 | "编写认证流程的完整测试套件" | `tests/test_auth.py` 含 15 个测试用例 | 质量保障 |

> 💡 分享 `.pulse` 文件，其他开发者就能瞬间看清你是如何通过这 5 步"调教" AI 完成架构演进的。

---

## 🛠 支持的 IDE（2026）

| IDE | 类型 | 采集方式 | 状态 |
|-----|------|---------|------|
| **Cursor** | 原生 AI IDE | SQLite + JSONL | ✅ 深度支持 |
| **VS Code** | 插件生态 | Copilot Chat 增量 JSONL + 扩展 DB | ✅ 完整支持 |
| **Trae** | 原生 AI IDE | SQLite | ✅ 已支持 |
| **Claude Code** | CLI Agent | 文件监控 + PTY | ✅ 已支持 |
| **Kiro** | 原生 AI IDE (Amazon) | Agent Sessions JSON + Q Chat API 日志 | ✅ 完整支持 |
| **Cline / Roo Code** | VS Code 扩展 | 扩展存储 | ✅ 已支持 |
| **Windsurf** | 原生 AI IDE | SQLite | ✅ 已支持 |
| **Codex** | CLI | PTY | ✅ 已支持 |
| **Claude Desktop** | 云端应用 | API | ☁️ 云端 |

> 想添加新 IDE？查看[贡献指南](./CONTRIBUTING.md#how-to-add-a-new-ide-adapter)。

<p align="center">
  <img src="./docs/screenshots/scan-panel.png" alt="IDE 嗅探面板 — 自动检测已安装的 AI IDE" width="680">
  <br>
  <em>IDE 嗅探面板：自动检测你机器上的 Cursor、VS Code、Trae、Codex 等</em>
</p>

---

## 🚀 快速开始

### 一行命令安装

**macOS / Linux：**

```bash
curl -fsSL https://raw.githubusercontent.com/Chiody/openbbox/main/install.sh | bash
```

**Windows（PowerShell）：**

```powershell
irm https://raw.githubusercontent.com/Chiody/openbbox/main/install.ps1 | iex
```

### 手动安装

```bash
git clone https://github.com/Chiody/openbbox.git
cd openbbox
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
openbbox start
# 浏览器打开 http://localhost:9966
```

### Docker

```bash
git clone https://github.com/Chiody/openbbox.git
cd openbbox
docker compose up -d
# 浏览器打开 http://localhost:9966
```

### Makefile 快捷命令

```bash
make install    # 创建虚拟环境 + 安装依赖
make start      # 启动服务器
make dev        # 开发模式（自动重载）
make scan       # 一次性扫描
make status     # 查看检测到的 IDE
make help       # 显示所有命令
```

---

## 📂 项目结构

```text
openbbox/
├── adapters/           # IDE 数据读取器（Cursor、Trae、Claude、VS Code...）
├── core/               # 核心引擎：匹配算法、数据模型、存储、导出
├── server/             # FastAPI + WebSocket + REST API
├── cli/                # Click CLI 命令行工具
├── protocol/           # OpenPulse JSON Schema 协议规范
├── dashboard/          # 三列工作台 SPA（零构建依赖）
├── docs/               # 官网着陆页 + 技术文档
├── .github/            # Issue 模板
├── Dockerfile          # 容器支持
├── docker-compose.yml  # 一键部署
├── pyproject.toml      # pip install 支持
├── Makefile            # 开发快捷命令
├── install.sh          # macOS/Linux 一键安装脚本
└── install.ps1         # Windows 一键安装脚本
```

---

## 🧠 工作原理

脉络作为**影子观察者**运行 — 一个被动读取本地 IDE 数据库的侧挂进程，不修改任何 IDE 数据。

```
IDE 日志 (SQLite/JSONL) ──▶ 适配器 ──▶ 时空匹配引擎 ──▶ 脉络节点 ──▶ 可视化面板
                                            │
                                  评分 = α·(1/ΔT) + β·文件重叠度 + γ·关键词相似度
```

1. **嗅探** — 以只读模式访问 IDE 对话数据库
2. **匹配** — 使用加权时空对齐算法将提示词与 Git Diff 配对
3. **存储** — 将结构化的脉络节点保存到 `~/.openbbox/openbbox.db`
4. **可视化** — 三列面板，支持搜索、导出和实时更新

> 📖 完整算法详解请查看[技术架构文档](./docs/ARCHITECTURE.md)。

### 各 IDE 嗅探策略

<details>
<summary><strong>Kiro</strong> — 双层策略（Agent Sessions + Q Chat API 日志）</summary>

| 层级 | 数据源 | 速度 | 采集内容 |
|------|--------|------|---------|
| **workspace_sessions** | `kiro.kiroagent/workspace-sessions/{b64path}/sessions.json` | 快速 | 从 session 历史中提取用户提示词；项目路径从 base64 目录名解码 |
| **workspace_db** | `workspaceStorage/{hash}/state.vscdb` | 快速 | 兜底：从 VS Code 兼容的 SQLite 中读取 chat/composer 键值 |

**关键发现**：Kiro 的 session JSON 中 assistant 回复只存储占位符（"On it."）。真正的 AI 回复存储在 `~/Library/Application Support/Kiro/logs/` 下的 `Q Chat API.log` 文件中。OpenBBox 解析这些日志，提取 `fullResponse` 和 `assistantResponseEvent` 内容，通过 `conversationId` 关联回对应的会话。

</details>

<details>
<summary><strong>VS Code</strong> — 三层策略（工作区聊天 + 全局聊天 + AI 扩展）</summary>

| 层级 | 数据源 | 速度 | 采集内容 |
|------|--------|------|---------|
| **workspace_chat** | `workspaceStorage/{hash}/chatSessions/*.jsonl` | 快速 | 每个项目的 Copilot Chat 对话 |
| **global_chat** | `globalStorage/emptyWindowChatSessions/*.jsonl` | 快速 | 无工作区窗口中的对话 |
| **ai_extensions** | `globalStorage/{ext-id}/`（Cline、Roo Code、Continue、Cody） | 中速 | 第三方 AI 扩展的对话 |

**关键发现**：VS Code Copilot Chat 使用增量 JSONL 格式 — `kind=0` 初始化会话状态，`kind=1` 补丁更新单个字段，`kind=2` 替换整个数组。OpenBBox 通过重放这些增量更新重建完整会话，然后从 response 对象中提取 `markdownContent`。

</details>

---

## 🔌 API 接口

| 方法 | 端点 | 描述 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/adapters` | 列出 IDE 及检测状态 |
| GET | `/api/nodes` | 列出脉络节点（分页） |
| GET | `/api/search?q=` | 按关键词搜索提示词 |
| GET | `/api/export/markdown` | 导出为 Markdown |
| GET | `/api/export/json` | 导出为 .pulse JSON |
| WS | `/ws` | 实时节点推送 |

启动服务器后访问 `http://localhost:9966/docs` 查看完整的交互式 API 文档。

---

## 🔒 隐私与安全

- **100% 本地** — 所有数据存储在你电脑的 `~/.openbbox/openbbox.db`
- **零遥测** — 无网络请求、无分析、无追踪
- **只读嗅探** — IDE 数据库以 `?mode=ro` 和 `PRAGMA query_only = ON` 打开
- **不修改 IDE** — 无插件、无扩展、无代码注入
- **数据自主** — 删除 `~/.openbbox/` 即可清除所有数据

---

## 📖 文档

| 文档 | 描述 |
|------|------|
| [技术架构](./docs/ARCHITECTURE.md) | 影子监听引擎、时空匹配算法、数据管道 |
| [贡献指南](./CONTRIBUTING.md) | 如何添加新 IDE 适配器、代码规范、PR 流程 |
| [OpenPulse 协议](./docs/PROTOCOL.md) | PulseNode JSON Schema、导出格式、版本管理 |

---

## 🤝 参与贡献

脉络为社区而生。无论你用 Cursor、Trae 还是命令行工具，我们都需要你的帮助。

```bash
git clone https://github.com/Chiody/openbbox.git
cd openbbox && make install && source .venv/bin/activate
make dev  # 开发模式启动
```

详见 [CONTRIBUTING.md](./CONTRIBUTING.md)。

---

## 🗺 路线图

- [x] 核心 Python 嗅探引擎 + 多适配器架构
- [x] 时空匹配算法（提示词 → Git Diff）
- [x] 三列可视化面板 + 中英双语 UI
- [x] 多 IDE 支持（Cursor、Trae、Claude Code、VS Code、Kiro、Windsurf、Codex）
- [x] PTY 终端包装器（CLI 工具捕获）
- [x] 资产导出（Markdown / JSON / 提示词列表）
- [ ] 社区 "Pulse Hub" — 分享提示词序列
- [ ] GitHub Actions 集成 — 自动化脉络追踪
- [ ] VS Code 扩展 — 编辑器内脉络视图

---

## 🙏 致谢

- [Aider](https://github.com/paul-gauthier/aider) — Git 监控模式
- [Continue](https://github.com/continuedev/continue) — SQLite 聊天历史结构
- [Asciinema](https://github.com/asciinema/asciinema) — PTY 终端录制架构
- [python-unidiff](https://github.com/btimby/python-unidiff) — Unified Diff 解析

---

## 📄 许可证

基于 **MIT 许可证** 分发。详见 [LICENSE](./LICENSE)。

---

<p align="center">
  为 AI 指挥官时代而生 ❤️<br>
  <strong>打开黑匣子，追踪每一条脉络。</strong>
</p>
