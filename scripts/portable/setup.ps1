$ErrorActionPreference = 'Stop'

$projectDir = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$runtimeDir = Join-Path $projectDir 'runtime'
$pythonHome = Join-Path $runtimeDir 'python'
$pythonInstaller = Join-Path $runtimeDir 'python-3.12.10-amd64.exe'
$nodeZip = Join-Path $runtimeDir 'node-v22.23.3-win-x64.zip'
$ffmpegZip = Join-Path $runtimeDir 'ffmpeg-release-essentials.zip'
$pythonExe = Join-Path $pythonHome 'python.exe'
$venvPython = Join-Path $projectDir '.venv\Scripts\python.exe'
$nodeHome = Join-Path $runtimeDir 'node'
$ffmpegBin = Join-Path $runtimeDir 'ffmpeg\bin'

if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -match 'ARM') {
    throw 'This portable retest bundle supports Windows x64 only.'
}
if (-not (Test-Path -LiteralPath (Join-Path $projectDir '.env'))) {
    throw 'The .env file is missing from the bundle.'
}
New-Item -ItemType Directory -Force -Path $runtimeDir, $nodeHome, $ffmpegBin, (Join-Path $projectDir 'data'), (Join-Path $projectDir 'logs'), (Join-Path $projectDir 'models\funasr') | Out-Null

if (-not (Test-Path -LiteralPath $pythonExe)) {
    if (-not (Test-Path -LiteralPath $pythonInstaller)) {
        Write-Host 'Downloading the private Python runtime (3.12.10)...'
        Invoke-WebRequest -UseBasicParsing 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' -OutFile $pythonInstaller
    }
    Write-Host 'Installing Python inside this project folder...'
    $arguments = '/quiet InstallAllUsers=0 Include_launcher=0 Include_test=0 Include_pip=1 PrependPath=0 Include_tcltk=0 TargetDir="' + $pythonHome + '"'
    $install = Start-Process -FilePath $pythonInstaller -ArgumentList $arguments -Wait -PassThru
    if (($install.ExitCode -ne 0 -and $install.ExitCode -ne 3010) -or -not (Test-Path -LiteralPath $pythonExe)) {
        throw "Private Python setup failed (exit $($install.ExitCode))."
    }
}

if (-not (Test-Path -LiteralPath (Join-Path $nodeHome 'node.exe'))) {
    if (-not (Test-Path -LiteralPath $nodeZip)) {
        Write-Host 'Downloading the private Node.js runtime (22.23.3 LTS)...'
        Invoke-WebRequest -UseBasicParsing 'https://nodejs.org/dist/v22.23.3/node-v22.23.3-win-x64.zip' -OutFile $nodeZip
    }
    $nodeExtract = Join-Path $runtimeDir 'node-extract'
    Expand-Archive -LiteralPath $nodeZip -DestinationPath $nodeExtract -Force
    $nodeSource = Join-Path $nodeExtract 'node-v22.23.3-win-x64'
    Copy-Item -Path (Join-Path $nodeSource '*') -Destination $nodeHome -Recurse -Force
    Remove-Item -LiteralPath $nodeExtract -Recurse -Force
}

if (-not (Test-Path -LiteralPath (Join-Path $ffmpegBin 'ffprobe.exe'))) {
    if (-not (Test-Path -LiteralPath $ffmpegZip)) {
        Write-Host 'Downloading private FFmpeg tools...'
        Invoke-WebRequest -UseBasicParsing 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' -OutFile $ffmpegZip
    }
    $ffmpegExtract = Join-Path $runtimeDir 'ffmpeg-extract'
    Expand-Archive -LiteralPath $ffmpegZip -DestinationPath $ffmpegExtract -Force
    $ffmpegSource = Get-ChildItem -LiteralPath $ffmpegExtract -Directory | Select-Object -First 1
    Copy-Item -Path (Join-Path $ffmpegSource.FullName 'bin\*') -Destination $ffmpegBin -Recurse -Force
    Remove-Item -LiteralPath $ffmpegExtract -Recurse -Force
}

if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host 'Creating a Python environment inside this project folder...'
    & $pythonExe -m venv (Join-Path $projectDir '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the project-local Python environment.' }
}
& $venvPython -m pip install --disable-pip-version-check --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'Could not prepare pip.' }

$gpuAvailable = $false
$nvidiaSmi = Get-Command 'nvidia-smi' -ErrorAction SilentlyContinue
if ($nvidiaSmi) {
    & $nvidiaSmi.Source '-L' *> $null
    $gpuAvailable = ($LASTEXITCODE -eq 0)
}
if ($gpuAvailable) {
    Write-Host 'NVIDIA GPU detected; installing CUDA 12.1 speech runtime first...'
    & $venvPython -m pip install --disable-pip-version-check -r (Join-Path $projectDir 'requirements-portable-cuda.txt')
    $cudaInstallSucceeded = ($LASTEXITCODE -eq 0)
    if ($cudaInstallSucceeded) {
        & $venvPython -c 'import torch; raise SystemExit(0 if torch.cuda.is_available() else 1)'
        $gpuAvailable = ($LASTEXITCODE -eq 0)
    } else { $gpuAvailable = $false }
} else { $cudaInstallSucceeded = $false }
if (-not $gpuAvailable) {
    & $venvPython -m pip uninstall -y torch torchaudio | Out-Null
    Write-Host 'CUDA is unavailable; installing the CPU speech runtime.'
    & $venvPython -m pip install --disable-pip-version-check -r (Join-Path $projectDir 'requirements-portable-cpu.txt')
    if ($LASTEXITCODE -ne 0) { throw 'CPU speech runtime installation failed.' }
}

Write-Host 'Installing Python application packages...'
& $venvPython -m pip install --disable-pip-version-check -r (Join-Path $projectDir 'requirements-portable.txt')
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }

$env:PATH = "$nodeHome;$env:PATH"
Write-Host 'Installing and building the frontend...'
& (Join-Path $nodeHome 'npm.cmd') ci --prefix (Join-Path $projectDir 'web')
if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
$env:NEXT_PUBLIC_API_MODE = 'real'
$env:BACKEND_URL = 'http://127.0.0.1:8000'
$env:API_PROXY_TIMEOUT_MS = '360000'
$env:NEXT_TELEMETRY_DISABLED = '1'
& (Join-Path $nodeHome 'npm.cmd') run build --prefix (Join-Path $projectDir 'web')
if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }

Write-Host 'Importing seed jobs...'
& $venvPython (Join-Path $projectDir 'scripts\import_seeds.py')
if ($LASTEXITCODE -ne 0) { throw 'Could not import the built-in jobs.' }
Write-Host 'Setup complete. Run start_portable.bat to launch the app.'
