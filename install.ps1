# OpenBBox (脉络) — One-line installer for Windows PowerShell
# Usage: irm https://raw.githubusercontent.com/Chiody/openbbox/main/install.ps1 | iex
$ErrorActionPreference = "Stop"

$REPO = "https://github.com/Chiody/openbbox.git"
$INSTALL_DIR = if ($env:OPENBBOX_HOME) { $env:OPENBBOX_HOME } else { "$env:USERPROFILE\.openbbox-app" }
$MIN_PYTHON_MINOR = 9

Write-Host ""
Write-Host "  ╔══════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "  ║     OpenBBox | 脉络                  ║" -ForegroundColor Cyan
Write-Host "  ║  The DNA of AI-Driven Development    ║" -ForegroundColor Cyan
Write-Host "  ╚══════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

function Info($msg)  { Write-Host "[OpenBBox] $msg" -ForegroundColor Cyan }
function Ok($msg)    { Write-Host "[  ✓  ] $msg" -ForegroundColor Green }
function Fail($msg)  { Write-Host "[  ✗  ] $msg" -ForegroundColor Red; exit 1 }

# Check Python
Info "Checking Python..."
$python = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $ver = & $cmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        if ($ver) {
            $parts = $ver.Split(".")
            if ([int]$parts[0] -ge 3 -and [int]$parts[1] -ge $MIN_PYTHON_MINOR) {
                $python = $cmd
                break
            }
        }
    } catch {}
}

if (-not $python) {
    Write-Host "[  ✗  ] Python >= 3.$MIN_PYTHON_MINOR is required." -ForegroundColor Red
    Write-Host ""
    Write-Host "💡 Tip: Open this project in your AI IDE and paste this prompt:" -ForegroundColor Cyan
    Write-Host '  "Install Python 3.9+ on my Windows system, then run the OpenBBox install.ps1 script again."' -ForegroundColor White
    Write-Host ""
    exit 1
}
$pyver = & $python --version 2>&1
Ok "Found $python ($pyver)"

# Check Git
Info "Checking Git..."
try { git --version | Out-Null } catch { Fail "Git is required. Install from https://git-scm.com" }
Ok "Found git ($(git --version))"

# Clone or update
if (Test-Path "$INSTALL_DIR\.git") {
    Info "Updating existing installation..."
    Set-Location $INSTALL_DIR
    git pull origin main
    Ok "Updated to latest version"
} else {
    Info "Cloning OpenBBox..."
    git clone --depth 1 $REPO $INSTALL_DIR
    Ok "Cloned to $INSTALL_DIR"
}

Set-Location $INSTALL_DIR

# Create venv
Info "Setting up virtual environment..."
if (-not (Test-Path ".venv")) {
    & $python -m venv .venv
}
& .\.venv\Scripts\Activate.ps1
Ok "Virtual environment ready"

# Install
Info "Installing dependencies..."
pip install --upgrade pip -q
pip install -e . -q
Ok "Dependencies installed"

# Create launcher batch file
$binDir = "$env:USERPROFILE\.local\bin"
New-Item -ItemType Directory -Force -Path $binDir | Out-Null
$launcher = "$binDir\openbbox.cmd"
@"
@echo off
set "INSTALL_DIR=%OPENBBOX_HOME%"
if "%INSTALL_DIR%"=="" set "INSTALL_DIR=%USERPROFILE%\.openbbox-app"
call "%INSTALL_DIR%\.venv\Scripts\activate.bat"
python -m cli.main %*
"@ | Out-File -Encoding ASCII $launcher
Ok "Launcher created at $launcher"

# Check PATH
if ($env:PATH -notlike "*$binDir*") {
    Write-Host ""
    Info "Add this directory to your PATH:"
    Write-Host "  $binDir" -ForegroundColor Yellow
    Write-Host '  [Environment]::SetEnvironmentVariable("PATH", "$env:PATH;' + $binDir + '", "User")' -ForegroundColor DarkGray
    Write-Host ""
}

Write-Host ""
Write-Host "Installation complete!" -ForegroundColor Green
Write-Host ""
Write-Host "  Start:     openbbox start" -ForegroundColor White
Write-Host "  Dashboard: http://localhost:9966" -ForegroundColor White
Write-Host ""
Write-Host "💡 Having issues? Open the project in your AI IDE and paste:" -ForegroundColor Cyan
Write-Host '  "Read the OpenBBox README, fix any setup issues, and start the server on port 9966."' -ForegroundColor White
Write-Host ""
