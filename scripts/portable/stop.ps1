$projectDir = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$stateFile = Join-Path $projectDir 'runtime\portable-services.json'
$projectPrefix = $projectDir.TrimEnd('\') + '\'
if (-not (Test-Path -LiteralPath $stateFile)) { Write-Host 'No portable services are recorded as running.'; exit 0 }
$pids = @(Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json)
foreach ($processId in $pids) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $([int]$processId)" -ErrorAction SilentlyContinue
    if ($process -and $process.ExecutablePath -and $process.ExecutablePath.StartsWith($projectPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        Stop-Process -Id ([int]$processId) -Force -ErrorAction SilentlyContinue
    }
}
Remove-Item -LiteralPath $stateFile -Force -ErrorAction SilentlyContinue
Write-Host 'Portable services stopped.'
