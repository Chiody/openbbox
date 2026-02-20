#!/usr/bin/env bash
# OpenBBox (脉络) — One-line installer for macOS / Linux
# Usage: curl -fsSL https://raw.githubusercontent.com/Chiody/openbbox/main/install.sh | bash
set -euo pipefail

REPO="https://github.com/Chiody/openbbox.git"
INSTALL_DIR="${OPENBBOX_HOME:-$HOME/.openbbox-app}"
MIN_PYTHON="3.10"

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()  { echo -e "${CYAN}[OpenBBox]${NC} $*"; }
ok()    { echo -e "${GREEN}[  ✓  ]${NC} $*"; }
fail()  { echo -e "${RED}[  ✗  ]${NC} $*"; exit 1; }

echo -e "${BOLD}${CYAN}"
echo "  ╔══════════════════════════════════════╗"
echo "  ║     OpenBBox | 脉络                  ║"
echo "  ║  The DNA of AI-Driven Development    ║"
echo "  ╚══════════════════════════════════════╝"
echo -e "${NC}"

# Check Python
info "Checking Python..."
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
        major=$(echo "$ver" | cut -d. -f1)
        minor=$(echo "$ver" | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ]; then
            PYTHON="$cmd"
            break
        fi
    fi
done

[ -z "$PYTHON" ] && fail "Python >= $MIN_PYTHON is required. Install from https://python.org"
ok "Found $PYTHON ($($PYTHON --version 2>&1))"

# Check Git
info "Checking Git..."
command -v git &>/dev/null || fail "Git is required. Install from https://git-scm.com"
ok "Found git ($(git --version))"

# Clone or update
if [ -d "$INSTALL_DIR/.git" ]; then
    info "Updating existing installation..."
    cd "$INSTALL_DIR"
    git pull --ff-only origin main 2>/dev/null || git pull origin main
    ok "Updated to latest version"
else
    info "Cloning OpenBBox..."
    git clone --depth 1 "$REPO" "$INSTALL_DIR"
    ok "Cloned to $INSTALL_DIR"
fi

cd "$INSTALL_DIR"

# Create venv
info "Setting up virtual environment..."
if [ ! -d ".venv" ]; then
    $PYTHON -m venv .venv
fi
source .venv/bin/activate
ok "Virtual environment ready"

# Install dependencies
info "Installing dependencies..."
pip install --upgrade pip -q
pip install -e . -q
ok "Dependencies installed"

# Create launcher script
LAUNCHER="$HOME/.local/bin/openbbox"
mkdir -p "$(dirname "$LAUNCHER")"
cat > "$LAUNCHER" << 'LAUNCHER_EOF'
#!/usr/bin/env bash
INSTALL_DIR="${OPENBBOX_HOME:-$HOME/.openbbox-app}"
source "$INSTALL_DIR/.venv/bin/activate"
exec python -m cli.main "$@"
LAUNCHER_EOF
chmod +x "$LAUNCHER"
ok "Launcher created at $LAUNCHER"

# Check PATH
if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
    echo ""
    info "Add this to your shell profile (~/.bashrc, ~/.zshrc, etc.):"
    echo -e "  ${BOLD}export PATH=\"\$HOME/.local/bin:\$PATH\"${NC}"
    echo ""
fi

echo ""
echo -e "${GREEN}${BOLD}Installation complete!${NC}"
echo ""
echo -e "  Start:    ${BOLD}openbbox start${NC}"
echo -e "  Update:   ${BOLD}cd $INSTALL_DIR && git pull && pip install -e .${NC}"
echo -e "  Dashboard: ${BOLD}http://localhost:9966${NC}"
echo ""
