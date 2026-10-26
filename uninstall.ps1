<#
.SYNOPSIS
Native Windows AI Guardian integration recovery and package uninstall.
.DESCRIPTION
Run from an operator terminal, not an AI session. Requires an independent
Python 3.11+ and scripts/ai_guardian_recovery.py from the same checkout.
No WSL, Bash, AI Guardian executable/package, or daemon is required.
Settings, violation history, and desktop entries are preserved. For normal
uninstall, the matching uv tool or this Python's pip package is removed only
after successful integration cleanup. See docs/UNINSTALL.md.
#>
[CmdletBinding()]
param(
    [switch]$IntegrationsOnly,
    [string]$Scope = 'user',
    [string[]]$Project = @(),
    [switch]$DryRun,
    [switch]$Yes,
    [string]$Python = 'python'
)

$ErrorActionPreference = 'Stop'
if ($Scope -notin @('user', 'project', 'both')) {
    [Console]::Error.WriteLine('Scope must be user, project, or both')
    exit 2
}
$Scope = $Scope.ToLowerInvariant()
if ($Scope -eq 'project' -and -not $IntegrationsOnly) {
    [Console]::Error.WriteLine('Project-only scope requires -IntegrationsOnly')
    exit 2
}
$engine = Join-Path $PSScriptRoot 'scripts/ai_guardian_recovery.py'
if (-not (Test-Path -LiteralPath $engine -PathType Leaf)) {
    [Console]::Error.WriteLine('Missing companion scripts/ai_guardian_recovery.py; no changes made')
    exit 2
}
try {
    # Resolve only executables: invoking a missing bare command starts PowerShell
    # module discovery, which can stall on Windows or import an unrelated module.
    # Unlike Get-Command with an exact name, GetCommands only searches the
    # requested command type and does not auto-import modules on a miss.
    $pythonCommands = @($ExecutionContext.InvokeCommand.GetCommands(
        $Python, [System.Management.Automation.CommandTypes]::Application, $false
    ))
    if ($pythonCommands.Count -eq 0) { throw 'Python executable not found' }
    $Python = $pythonCommands[0].Path
    & $Python -I -S -c 'import sys; sys.exit(sys.version_info < (3, 11))'
    if ($LASTEXITCODE -ne 0) { throw 'Python version check failed' }
} catch {
    [Console]::Error.WriteLine('An independent Python 3.11+ interpreter is required; no changes made')
    exit 2
}
$cleanupArgs = @('-I', '-S', $engine, '--scope', $Scope)
foreach ($path in $Project) { $cleanupArgs += @('--project', $path) }
if ($DryRun) { $cleanupArgs += '--dry-run' }
if ($Yes) { $cleanupArgs += '--yes' }
& $Python @cleanupArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if ($IntegrationsOnly) { exit 0 }

if (-not $DryRun -and -not $Yes) {
    if ((Read-Host 'Continue with package removal? [y/N]') -notmatch '^(?i:y|yes)$') {
        Write-Output 'Package removal cancelled.'
        exit 1
    }
}
# Recovery does not signal processes or load the missing application. Close the
# tray/daemon normally before package removal; do not trust stale PID files.
$uv = Get-Command uv -ErrorAction SilentlyContinue
if ($uv) {
    $tools = & $uv.Source tool list 2>$null
    if ($LASTEXITCODE -eq 0 -and ($tools -match '^ai-guardian(?:\s|$)')) {
        if ($DryRun) { Write-Output 'Would remove package (uv tool)' }
        else {
            & $uv.Source tool uninstall ai-guardian
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        }
        exit 0
    }
}
& $Python -m pip show ai-guardian *> $null
if ($LASTEXITCODE -eq 0) {
    if ($DryRun) { Write-Output 'Would remove package (selected Python pip)' }
    else {
        & $Python -m pip uninstall -y ai-guardian
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
} else {
    Write-Output 'Package absent from selected Python; other installations are not searched.'
}
Write-Output 'Settings, violation history, and desktop entries kept. Restart affected hosts.'
exit 0
