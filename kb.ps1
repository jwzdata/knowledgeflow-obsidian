# KnowledgeFlow Windows launcher.
# Mirrors kb.sh: prepend this repo's src directory to PYTHONPATH, then run
# `python -m knowledgeflow --vault <repo>`. Requires Python 3.11+.
# Not tested on Windows. The steps were checked against kb.sh and
# src/knowledgeflow/__main__.py on Linux.
#
# From any working directory:
#   .\kb.ps1 run --offline
#   .\kb.ps1 search "keywords"
#   .\kb.ps1 context-pack "topic" --budget 2000
#
# If PowerShell refuses to run the file, the current process can allow it:
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Src = Join-Path $Root "src"
if ([string]::IsNullOrEmpty($env:PYTHONPATH)) {
    $env:PYTHONPATH = $Src
} else {
    $env:PYTHONPATH = "$Src;$env:PYTHONPATH"
}

$Python = $null
foreach ($Name in @("py", "python", "python3")) {
    $Cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -ne $Cmd) {
        $Python = $Cmd.Source
        break
    }
}
if ($null -eq $Python) {
    Write-Error "Python 3.11+ was not found on PATH. Tried: py, python, python3."
}

& $Python -m knowledgeflow --vault "$Root" @args
exit $LASTEXITCODE
