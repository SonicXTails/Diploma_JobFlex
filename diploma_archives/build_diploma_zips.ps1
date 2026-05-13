# Wrapper: builds ZIPs via Python (see build_diploma_zips.py).
$py = Join-Path (Split-Path -Parent $PSScriptRoot) ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
& $py (Join-Path $PSScriptRoot "build_diploma_zips.py")
exit $LASTEXITCODE
