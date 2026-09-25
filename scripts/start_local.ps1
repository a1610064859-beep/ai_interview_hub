$ErrorActionPreference = 'Stop'

$projectDir = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$webDir = Join-Path $projectDir 'web'
$python = Join-Path $projectDir '.venv\Scripts\python.exe'
$nextCli = Join-Path $webDir 'node_modules\next\dist\bin\next'

function Get-LocalSetting([string]$name) {
    $prefix = "$name="
    foreach ($file in @((Join-Path $projectDir '.env'), (Join-Path $projectDir '.env.example'))) {
        if (-not (Test-Path -LiteralPath $file)) { continue }
        foreach ($line in (Get-Content -LiteralPath $file -Encoding UTF8)) {
            if ($line.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
                $value = $line.Substring($prefix.Length).Trim().Trim('"', "'")
                if ($value) { return $value }
            }
        }
    }
    throw "Missing $name in .env or .env.example"
}

function Test-Ready([string]$url) {
    try {
        $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 4
        return ($response.StatusCode -eq 200)
    } catch {
        return $false
    }
}

function Wait-Ready([string]$url, [string]$name, [System.Diagnostics.Process]$process) {
    for ($attempt = 1; $attempt -le 60; $attempt++) {
        if (Test-Ready $url) { return }
        if ($process) {
            $process.Refresh()
            if ($process.HasExited) { throw "$name exited before becoming ready (code $($process.ExitCode))." }
        }
        Start-Sleep -Seconds 2
    }
    throw "$name did not become ready within 120 seconds: $url"
}

try {
    if (-not (Test-Path -LiteralPath $python)) { throw "Python environment missing: $python" }
    if (-not (Test-Path -LiteralPath $nextCli)) { throw "Frontend dependencies missing: $nextCli" }
    $node = (Get-Command node -ErrorAction Stop).Source

    $backendUrl = (Get-LocalSetting 'BACKEND_URL').TrimEnd('/')
    $frontendUrl = (Get-LocalSetting 'FRONTEND_URL').TrimEnd('/') + '/'
    $backendUri = [uri]$backendUrl
    $frontendUri = [uri]$frontendUrl
    if ($backendUri.Scheme -ne 'http' -or $frontendUri.Scheme -ne 'http') {
        throw 'Local launcher expects http URLs in BACKEND_URL and FRONTEND_URL.'
    }

    $backendCheck = "$backendUrl/api/jobs"
    if (Test-Ready $backendCheck) {
        Write-Host "Backend already ready: $backendUrl"
    } else {
        Write-Host "Starting backend: $backendUrl"
        $backendProcess = Start-Process -FilePath $python -ArgumentList @(
            '-m', 'uvicorn', 'server.main:app', '--host', $backendUri.Host,
            '--port', [string]$backendUri.Port
        ) -WorkingDirectory $projectDir -WindowStyle Hidden -PassThru
        Wait-Ready $backendCheck 'Backend' $backendProcess
    }

    if (Test-Ready $frontendUrl) {
        Write-Host "Frontend already ready: $frontendUrl"
    } else {
        Write-Host "Starting frontend: $frontendUrl"
        $env:NEXT_PUBLIC_API_MODE = 'real'
        $env:BACKEND_URL = $backendUrl
        $env:NEXT_TELEMETRY_DISABLED = '1'
        $frontendProcess = Start-Process -FilePath $node -ArgumentList @(
            $nextCli, 'dev', '-p', [string]$frontendUri.Port, '-H', $frontendUri.Host
        ) -WorkingDirectory $webDir -WindowStyle Hidden -PassThru
        Wait-Ready $frontendUrl 'Frontend' $frontendProcess
    }

    $frontendApi = "${frontendUrl}api/jobs"
    if (-not (Test-Ready $frontendApi)) {
        throw "Frontend is visible, but the backend API proxy is unavailable: $frontendApi"
    }
    Write-Host "Ready: $frontendUrl"
    try { Start-Process -FilePath $frontendUrl } catch { Write-Warning "Open this URL manually: $frontendUrl" }
} catch {
    Write-Error "Startup failed: $($_.Exception.Message)"
    exit 1
}
