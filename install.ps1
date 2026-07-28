#Requires -Version 5.1
<#
.SYNOPSIS
    AI Guardian — One-line installer for Windows.

.DESCRIPTION
    Installs ai-guardian, creates configuration, and optionally sets up IDE hooks.

.PARAMETER Venv
    Create a virtual environment at $HOME\.ai-guardian-venv\

.PARAMETER IDE
    Setup hooks for a specific IDE (skipped if omitted).
    Choices: claude, cursor, copilot, codex, windsurf, gemini, cline,
             zoocode, augment, kiro, junie, aiderdesk, opencode

.PARAMETER Profile
    Security profile: @minimal, @standard (default), @strict

.PARAMETER Version
    Install a specific version or a local .whl file.

.PARAMETER NoSetup
    Install only, don't auto-detect or update existing IDE hooks.

.PARAMETER Tkinter
    Verify tkinter availability (included with python.org installers).

.EXAMPLE
    irm https://raw.githubusercontent.com/RedHatProductSecurity/ai-guardian/main/install.ps1 | iex

.EXAMPLE
    .\install.ps1 -IDE claude -Profile @strict -Venv
#>
[CmdletBinding()]
param(
    [switch]$Venv,
    [string]$IDE = "",
    [string]$Profile = "@standard",
    [string]$Version = "",
    [switch]$NoSetup,
    [switch]$Tkinter,
    [switch]$Help,
    [Parameter(ValueFromRemainingArguments)]
    [string[]]$SetupArgs
)

$ErrorActionPreference = "Stop"

function Log($msg) { Write-Host "==> $msg" -ForegroundColor Blue }
function Ok($msg)  { Write-Host "  ✓ $msg" -ForegroundColor Green }
function Err($msg) { Write-Host "Error: $msg" -ForegroundColor Red; exit 1 }

if ($Help) {
    Get-Help $MyInvocation.MyCommand.Path -Detailed
    exit 0
}

# --- Step 1: Find Python 3.9+ ---

Log "Checking Python version..."

$Python = $null
foreach ($candidate in @("python", "python3", "py")) {
    $found = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($found) {
        $versionOk = & $found.Source -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            $Python = $found.Source
            break
        }
    }
}

if (-not $Python) {
    # Try the Windows Python Launcher
    $py = Get-Command "py" -ErrorAction SilentlyContinue
    if ($py) {
        & py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            $Python = "py"
        }
    }
}

if (-not $Python) {
    Err "Python 3.9+ is required but not found. Install from https://www.python.org/downloads/"
}

$PyVersion = & $Python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
Ok "Python $PyVersion ($Python)"

# --- Step 2: Create venv (optional) ---

$VenvDir = Join-Path $HOME ".ai-guardian-venv"

if ($Venv) {
    Log "Creating virtual environment at $VenvDir..."
    & $Python -m venv $VenvDir
    $Python = Join-Path $VenvDir "Scripts\python.exe"
    Ok "Virtual environment created"
}

# --- Step 3: Install ai-guardian ---

Log "Installing ai-guardian..."
$Pkg = "ai-guardian"
if ($Version) {
    if ($Version -like "*.whl") {
        if (-not (Test-Path $Version)) {
            Err "Wheel file not found: $Version"
        }
        $Pkg = $Version
    } else {
        $Pkg = "ai-guardian==$Version"
    }
}
& $Python -m pip install --quiet $Pkg
if ($LASTEXITCODE -ne 0) { Err "pip install failed" }

$AgVersion = & $Python -m ai_guardian --version 2>&1 | ForEach-Object { ($_ -split ' ')[-1] }
Ok "ai-guardian $AgVersion installed"

# --- Step 3b: Verify tkinter (optional) ---

if ($Tkinter) {
    & $Python -c "import tkinter" 2>$null
    if ($LASTEXITCODE -eq 0) {
        Ok "tkinter available"
    } else {
        Write-Host "  tkinter not found. Reinstall Python from https://www.python.org/downloads/"
        Write-Host "  and check 'tcl/tk and IDLE' during installation."
        Write-Host "  Continuing without tkinter (NiceGUI browser fallback on Python 3.10+, Textual otherwise)"
    }
}

# --- Step 3c: Auto-detect and update existing agent hooks ---

function Detect-InstalledAgents {
    $agents = @()

    # JSON-config agents: check file exists + contains "ai-guardian"
    $claudeDir = if ($env:CLAUDE_CONFIG_DIR) { $env:CLAUDE_CONFIG_DIR } else { Join-Path $HOME ".claude" }
    $claudeConfig = Join-Path $claudeDir "settings.json"
    if ((Test-Path $claudeConfig) -and (Select-String -Path $claudeConfig -Pattern "ai-guardian" -Quiet)) { $agents += "claude" }

    $cursorConfig = Join-Path $HOME ".cursor\hooks.json"
    if ((Test-Path $cursorConfig) -and (Select-String -Path $cursorConfig -Pattern "ai-guardian" -Quiet)) { $agents += "cursor" }

    $copilotConfig = Join-Path $HOME ".github\hooks\hooks.json"
    if ((Test-Path $copilotConfig) -and (Select-String -Path $copilotConfig -Pattern "ai-guardian" -Quiet)) { $agents += "copilot" }

    $codexConfig = Join-Path $HOME ".codex\hooks.json"
    if ((Test-Path $codexConfig) -and (Select-String -Path $codexConfig -Pattern "ai-guardian" -Quiet)) { $agents += "codex" }

    $windsurfConfig = Join-Path $HOME ".codeium\windsurf\hooks.json"
    if ((Test-Path $windsurfConfig) -and (Select-String -Path $windsurfConfig -Pattern "ai-guardian" -Quiet)) { $agents += "windsurf" }

    $geminiConfig = Join-Path $HOME ".gemini\settings.json"
    if ((Test-Path $geminiConfig) -and (Select-String -Path $geminiConfig -Pattern "ai-guardian" -Quiet)) { $agents += "gemini" }

    $augmentConfig = Join-Path $HOME ".augment\settings.json"
    if ((Test-Path $augmentConfig) -and (Select-String -Path $augmentConfig -Pattern "ai-guardian" -Quiet)) { $agents += "augment" }

    # Plugin-file agents
    $opencodePlugin = Join-Path $HOME ".config\opencode\plugins\ai-guardian.ts"
    if (Test-Path $opencodePlugin) { $agents += "opencode" }

    # Extension-based agents
    $aiderdeskExt = Join-Path $HOME ".aider-desk\extensions\ai-guardian\index.ts"
    if (Test-Path $aiderdeskExt) { $agents += "aiderdesk" }

    $openclawExt = Join-Path $HOME ".openclaw\plugins\ai-guardian\index.ts"
    if (Test-Path $openclawExt) { $agents += "openclaw" }

    return $agents
}

if (-not $IDE -and -not $NoSetup) {
    $DetectedAgents = Detect-InstalledAgents
    if ($DetectedAgents.Count -gt 0) {
        Log "Detected existing hooks, updating..."
        $UpdatedAgents = @()
        foreach ($agent in $DetectedAgents) {
            try {
                & $Python -m ai_guardian setup --ide $agent --force --yes @SetupArgs 2>&1 | Out-Null
                $UpdatedAgents += $agent
            } catch { }
        }
        if ($UpdatedAgents.Count -gt 0) {
            Ok "Updated hooks for: $($UpdatedAgents -join ', ')"
        }
    } else {
        Write-Host ""
        Write-Host "  No existing hooks found. Run setup for your IDE:"
        Write-Host "    ai-guardian setup --ide claude"
        Write-Host "    ai-guardian setup --ide opencode"
        Write-Host "    ai-guardian setup --ide cursor"
        Write-Host ""
    }
}

# --- Step 4: Create config ---

Log "Creating configuration (profile: $Profile)..."
& $Python -m ai_guardian setup --create-config --profile $Profile --yes 2>&1 | Select-Object -Last 1
$ConfigPath = Join-Path $env:APPDATA "ai-guardian\ai-guardian.json"
if (-not (Test-Path $ConfigPath)) {
    $ConfigPath = Join-Path $HOME ".config\ai-guardian\ai-guardian.json"
}
Ok "Config at $ConfigPath"

# --- Step 5: Setup IDE hooks (only when -IDE is provided) ---

if ($IDE) {
    Log "Setting up hooks for $IDE..."
    $setupCmd = @("-m", "ai_guardian", "setup", "--ide", $IDE, "--install-scanner", "--yes")
    if ($SetupArgs) { $setupCmd += $SetupArgs }
    $SetupOutput = & $Python @setupCmd 2>&1 | Out-String
    $SetupOutput -split "`n" | Where-Object { $_ -ne "" } | Select-Object -Last 3
    if ($SetupOutput -match "already configured") {
        Ok "Hooks already configured for $IDE"
    } else {
        Ok "Hooks installed for $IDE"
    }
}

# --- Step 6: Verify installation ---

Log "Verifying installation..."
& $Python -m ai_guardian doctor 2>&1 | Select-Object -Last 5

# --- Step 7: Summary ---

Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
Write-Host "  AI Guardian $AgVersion installed successfully"
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
Write-Host ""
Write-Host "  Version:  $AgVersion"
Write-Host "  Config:   $ConfigPath"
Write-Host "  Profile:  $Profile"
if ($Venv) {
    Write-Host "  Venv:     $VenvDir"
}
if ($IDE) {
    Write-Host "  IDE:      $IDE"
} elseif ($UpdatedAgents -and $UpdatedAgents.Count -gt 0) {
    Write-Host "  Updated:  $($UpdatedAgents -join ', ')"
}

& $Python -c "import tkinter" 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "  Popups:   tkinter (native dialogs)"
} else {
    & $Python -c "import nicegui" 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  Popups:   NiceGUI (browser-based form)"
    } else {
        Write-Host "  Popups:   Textual (terminal fallback)"
    }
}

Write-Host ""
Write-Host "  Popup override env vars:"
Write-Host '    $env:AI_GUARDIAN_NO_TKINTER=1   skip tkinter, use NiceGUI or Textual'
Write-Host '    $env:AI_GUARDIAN_NO_NICEGUI=1   skip NiceGUI, use Textual'
Write-Host ""
Write-Host "  Next steps:"
if (-not $IDE -and (-not $UpdatedAgents -or $UpdatedAgents.Count -eq 0)) {
    Write-Host "    ai-guardian setup --ide <NAME>  # setup hooks for your IDE"
}
Write-Host "    ai-guardian doctor         # verify setup"
Write-Host "    ai-guardian daemon start   # start background daemon"
Write-Host "    ai-guardian tray start     # start system tray"
Write-Host "    ai-guardian --help         # see all commands"
if ($Venv) {
    Write-Host "    & $VenvDir\Scripts\Activate.ps1  # activate venv"
}
Write-Host ""
