<# 
Entrypoint for Windows development checks.
Runs the pre-launch validation script from scripts/.
#>

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$checkScript = Join-Path -Path $scriptDir -ChildPath "scripts\\check-resolve-ready.ps1"

if (-not (Test-Path -Path $checkScript)) {
    Write-Error "Missing pre-launch script: $checkScript"
    exit 1
}

& $checkScript @args
