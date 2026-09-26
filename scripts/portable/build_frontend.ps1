[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$OutputDir
)

$ErrorActionPreference = 'Stop'

if (-not [System.IO.Path]::IsPathRooted($OutputDir)) {
    throw '-OutputDir must be an absolute path.'
}

$projectDir = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$sourceWebDir = Join-Path $projectDir 'web'
$nextEnvPath = Join-Path $sourceWebDir 'next-env.d.ts'
$tsconfigPath = Join-Path $sourceWebDir 'tsconfig.json'
$originalNextEnv = [System.IO.File]::ReadAllBytes($nextEnvPath)
$originalTsconfig = [System.IO.File]::ReadAllBytes($tsconfigPath)
$fullOutputDir = [System.IO.Path]::GetFullPath($OutputDir)
$outputWebDir = Join-Path $fullOutputDir 'web'

if ([string]::Equals($sourceWebDir.TrimEnd('\'), $outputWebDir.TrimEnd('\'), [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'OutputDir would overwrite the project web directory.'
}

$null = Get-Command node -ErrorAction Stop
$npmCommand = Get-Command npm.cmd -ErrorAction Stop

$originalApiMode = $env:NEXT_PUBLIC_API_MODE
$originalBackendUrl = $env:BACKEND_URL
$originalTelemetryDisabled = $env:NEXT_TELEMETRY_DISABLED
$originalDistDir = $env:NEXT_DIST_DIR
$buildDistDir = '.next-portable'
$locationPushed = $false

try {
    New-Item -ItemType Directory -Force -Path $fullOutputDir | Out-Null

    $env:NEXT_PUBLIC_API_MODE = 'real'
    $env:BACKEND_URL = 'http://127.0.0.1:8000'
    $env:NEXT_TELEMETRY_DISABLED = '1'
    $env:NEXT_DIST_DIR = $buildDistDir

    Push-Location -LiteralPath $sourceWebDir
    $locationPushed = $true
    & $npmCommand.Source run build
    if ($LASTEXITCODE -ne 0) {
        throw "npm run build failed with exit code $LASTEXITCODE."
    }

    $standaloneDir = Join-Path $sourceWebDir "$buildDistDir\standalone"
    $staticDir = Join-Path $sourceWebDir "$buildDistDir\static"
    if (-not (Test-Path -LiteralPath $standaloneDir -PathType Container)) {
        throw "Next.js standalone output was not created: $standaloneDir"
    }
    if (-not (Test-Path -LiteralPath $staticDir -PathType Container)) {
        throw "Next.js static output was not created: $staticDir"
    }

    if (Test-Path -LiteralPath $outputWebDir) {
        Remove-Item -LiteralPath $outputWebDir -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $outputWebDir | Out-Null

    Get-ChildItem -LiteralPath $standaloneDir -Force | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $outputWebDir -Recurse -Force
    }

    $outputStaticDir = Join-Path $outputWebDir "$buildDistDir\static"
    New-Item -ItemType Directory -Force -Path $outputStaticDir | Out-Null
    Get-ChildItem -LiteralPath $staticDir -Force | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $outputStaticDir -Recurse -Force
    }

    $publicDir = Join-Path $sourceWebDir 'public'
    if (Test-Path -LiteralPath $publicDir -PathType Container) {
        Copy-Item -LiteralPath $publicDir -Destination $outputWebDir -Recurse -Force
    }

    if (-not (Test-Path -LiteralPath (Join-Path $outputWebDir 'server.js') -PathType Leaf)) {
        throw 'The packaged standalone output does not contain server.js.'
    }

    Write-Output "Standalone frontend ready: $outputWebDir"
    Write-Output "Included: server.js, .next\static, standalone runtime files, and public/ when present."
    Write-Output 'The runtime PORT is left unset so the launcher can choose the listening port.'
}
finally {
    if ($locationPushed) {
        Pop-Location
    }
    $env:NEXT_PUBLIC_API_MODE = $originalApiMode
    $env:BACKEND_URL = $originalBackendUrl
    $env:NEXT_TELEMETRY_DISABLED = $originalTelemetryDisabled
    $env:NEXT_DIST_DIR = $originalDistDir
    [System.IO.File]::WriteAllBytes($nextEnvPath, $originalNextEnv)
    [System.IO.File]::WriteAllBytes($tsconfigPath, $originalTsconfig)
}
