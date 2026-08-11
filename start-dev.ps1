param(
  [int]$ApiPort = 8000,
  [int]$WebPort = 5173
)

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonCommand = Get-Command python -ErrorAction SilentlyContinue
$BundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$PythonCandidates = @(
  (Join-Path $ProjectRoot '.venv\Scripts\python.exe')
  if ($PythonCommand) { $PythonCommand.Source }
  $BundledPython
) | Select-Object -Unique
$PythonExe = $null
foreach ($Candidate in $PythonCandidates) {
  if (-not (Test-Path -LiteralPath $Candidate)) { continue }
  & $Candidate -c 'import fastapi, imageio_ffmpeg, langgraph, langchain, sentence_transformers, pymilvus' 2>$null
  if ($LASTEXITCODE -eq 0) {
    $PythonExe = $Candidate
    break
  }
}
$PnpmCommand = Get-Command pnpm.cmd -ErrorAction SilentlyContinue
$PnpmExe = if ($PnpmCommand) { $PnpmCommand.Source } else { Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\bin\fallback\pnpm.cmd' }

if (-not $PythonExe) { throw 'No Python environment with project dependencies was found. Run: python -m pip install -r backend\requirements.txt' }
if (-not (Test-Path -LiteralPath $PnpmExe)) { throw 'pnpm not found, please run: npm install -g pnpm' }

$ApiArgs = @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', $ApiPort)
# The bundled Codex runtime cannot be safely respawned by Uvicorn on Windows.
if ($PythonExe -notmatch 'codex-primary-runtime') { $ApiArgs += '--reload' }
$WebArgs = @('run', 'dev', '--', '--port', $WebPort)
$env:VITE_API_PROXY = "http://127.0.0.1:$ApiPort"
Start-Process -FilePath $PythonExe -ArgumentList $ApiArgs -WorkingDirectory (Join-Path $ProjectRoot 'backend') -WindowStyle Hidden
Start-Process -FilePath $PnpmExe -ArgumentList $WebArgs -WorkingDirectory (Join-Path $ProjectRoot 'frontend') -WindowStyle Hidden

Write-Host "Zhiyan Backend: http://127.0.0.1:$ApiPort/api/docs"
Write-Host "Zhiyan Frontend: http://127.0.0.1:$WebPort"
Write-Host "Python runtime: $PythonExe"
Write-Host "Demo account: demo@zhiyan.ai / demo123456"
