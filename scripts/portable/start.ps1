$ErrorActionPreference = 'Stop'
$projectDir = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$python = Join-Path $projectDir '.venv\Scripts\python.exe'
$node = Join-Path $projectDir 'runtime\node\node.exe'
$nextCli = Join-Path $projectDir 'web\node_modules\next\dist\bin\next'
$backendLog = Join-Path $projectDir 'logs\portable-backend.out.txt'
$backendErr = Join-Path $projectDir 'logs\portable-backend.err.txt'
$frontendLog = Join-Path $projectDir 'logs\portable-frontend.out.txt'
$frontendErr = Join-Path $projectDir 'logs\portable-frontend.err.txt'
$stateFile = Join-Path $projectDir 'runtime\portable-services.json'

if (-not (Test-Path -LiteralPath $python) -or -not (Test-Path -LiteralPath $node) -or -not (Test-Path -LiteralPath $nextCli)) {
    & (Join-Path $PSScriptRoot 'setup.ps1')
}

$env:PATH = "$(Join-Path $projectDir 'runtime\node');$(Join-Path $projectDir 'runtime\ffmpeg\bin');$env:PATH"
$env:NEXT_PUBLIC_API_MODE = 'real'
$env:BACKEND_URL = 'http://127.0.0.1:8000'
$env:API_PROXY_TIMEOUT_MS = '360000'
$env:NEXT_TELEMETRY_DISABLED = '1'
New-Item -ItemType Directory -Force -Path (Join-Path $projectDir 'logs') | Out-Null

function Test-Ready([string]$url) {
    try { return (Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 8).StatusCode -eq 200 } catch { return $false }
}
function Wait-Ready([string]$url, [string]$name, [System.Diagnostics.Process]$process, [int]$timeoutSeconds) {
    $deadline = [DateTime]::UtcNow.AddSeconds($timeoutSeconds)
    $lastNotice = [DateTime]::UtcNow
    while ([DateTime]::UtcNow -lt $deadline) {
        if (Test-Ready $url) { return }
        if ($process) {
            $process.Refresh()
            if ($process.HasExited) { throw "$name stopped during startup. See logs\portable-*.err.txt." }
        }
        if (([DateTime]::UtcNow - $lastNotice).TotalSeconds -ge 60) {
            Write-Host "$name is still starting; the first speech-model download may take a while..."
            $lastNotice = [DateTime]::UtcNow
        }
        Start-Sleep -Seconds 3
    }
    throw "$name did not become ready in time. Check logs\portable-*.err.txt and internet access."
}

if (-not (Test-Ready 'http://127.0.0.1:8000/api/jobs')) {
    Write-Host 'Starting API; first CPU speech-model setup can take several minutes...'
    $backend = Start-Process -FilePath $python -ArgumentList @('-m','uvicorn','server.main:app','--host','127.0.0.1','--port','8000') -WorkingDirectory $projectDir -WindowStyle Hidden -PassThru -RedirectStandardOutput $backendLog -RedirectStandardError $backendErr
    Wait-Ready 'http://127.0.0.1:8000/api/jobs' 'Backend' $backend 1800
} else { $backend = $null }

if (-not (Test-Ready 'http://127.0.0.1:3000/')) {
    Write-Host 'Starting web application...'
    $frontend = Start-Process -FilePath $node -ArgumentList @($nextCli,'start','-p','3000','-H','127.0.0.1') -WorkingDirectory (Join-Path $projectDir 'web') -WindowStyle Hidden -PassThru -RedirectStandardOutput $frontendLog -RedirectStandardError $frontendErr
    Wait-Ready 'http://127.0.0.1:3000/' 'Frontend' $frontend 300
} else { $frontend = $null }

$pids = @()
if ($backend) { $pids += $backend.Id }
if ($frontend) { $pids += $frontend.Id }
if ($pids.Count -gt 0) { ConvertTo-Json -InputObject $pids | Set-Content -LiteralPath $stateFile -Encoding UTF8 }
Write-Host 'Ready: http://127.0.0.1:3000/'
try { Start-Process 'http://127.0.0.1:3000/' } catch { Write-Host 'Open http://127.0.0.1:3000/ in a browser.' }
