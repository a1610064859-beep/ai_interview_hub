[CmdletBinding()]
param([string]$ResumeStageDir)

$ErrorActionPreference = 'Stop'
$projectDir = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$distDir = Join-Path $projectDir 'dist'
$buildId = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N').Substring(0, 6)
$stageDir = if ($ResumeStageDir) { (Resolve-Path -LiteralPath $ResumeStageDir).Path } else { Join-Path $distDir ('exe-' + $buildId) }
$distPrefix = [System.IO.Path]::GetFullPath($distDir).TrimEnd('\') + '\'
if ($ResumeStageDir -and -not $stageDir.StartsWith($distPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw '-ResumeStageDir must be inside the project dist directory.'
}
$zipPath = Join-Path $distDir ('AIInterviewHub-Offline-EXE-' + $buildId + '.zip')
$launcherBuildDir = Join-Path $distDir '.build-launcher'
$launcherVenv = Join-Path $launcherBuildDir 'venv'
$launcherPython = Join-Path $launcherVenv 'Scripts\python.exe'
$sourceVenvPython = Join-Path $projectDir '.venv\Scripts\python.exe'
$sourceSitePackages = Join-Path $projectDir '.venv\Lib\site-packages'
$modelSource = Join-Path $env:USERPROFILE '.cache\modelscope\models\iic--speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch\snapshots\master'

foreach ($required in @($sourceVenvPython, $sourceSitePackages, (Join-Path $modelSource 'model.pt'), (Join-Path $projectDir '.env'))) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Build input is missing: $required" }
}
New-Item -ItemType Directory -Force -Path $distDir, $stageDir, $launcherBuildDir | Out-Null

function Copy-LargeTree([string]$source, [string]$destination) {
    New-Item -ItemType Directory -Force -Path $destination | Out-Null
    & robocopy.exe $source $destination /E /R:2 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "Copy failed ($LASTEXITCODE): $source" }
}

function Copy-SourceTree([string]$source, [string]$destination) {
    New-Item -ItemType Directory -Force -Path $destination | Out-Null
    foreach ($file in Get-ChildItem -LiteralPath $source -Recurse -File -Force) {
        $relative = $file.FullName.Substring($source.Length).TrimStart([char[]]@(92,47))
        if ($relative -match '(^|[\\/])(__pycache__|\.pytest_cache|\.git)([\\/]|$)') { continue }
        if ($file.Extension.ToLowerInvariant() -in @('.pyc','.pyo','.log','.db','.sqlite','.sqlite3')) { continue }
        $target = Join-Path $destination $relative
        New-Item -ItemType Directory -Force -Path (Split-Path $target -Parent) | Out-Null
        Copy-Item -LiteralPath $file.FullName -Destination $target -Force
    }
}

if (-not $ResumeStageDir) {
Write-Host 'Building self-contained Next.js output...'
& (Join-Path $projectDir 'scripts\portable\build_frontend.ps1') -OutputDir $stageDir
if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) { throw "Frontend build failed ($LASTEXITCODE)." }

Write-Host 'Copying application files...'
Copy-SourceTree (Join-Path $projectDir 'server') (Join-Path $stageDir 'server')
New-Item -ItemType Directory -Force -Path (Join-Path $stageDir 'scripts'), (Join-Path $stageDir 'data') | Out-Null
Copy-Item -LiteralPath (Join-Path $projectDir 'scripts\import_seeds.py') -Destination (Join-Path $stageDir 'scripts\import_seeds.py')
foreach ($seed in @('jobs_seed.json','freshman_static.json')) {
    Copy-Item -LiteralPath (Join-Path $projectDir "data\$seed") -Destination (Join-Path $stageDir "data\$seed")
}
Copy-Item -LiteralPath (Join-Path $projectDir 'docs\exe-portable-retest.md') -Destination (Join-Path $stageDir 'README.md')

$packedEnv = foreach ($line in Get-Content -LiteralPath (Join-Path $projectDir '.env') -Encoding UTF8) {
    if ($line -match '^([A-Z0-9_]*(API_KEY|SECRET|TOKEN|PASSWORD)[A-Z0-9_]*)=' -and $Matches[1] -ne 'FLAGSHIP_API_KEY') {
        $Matches[1] + '='
    } elseif ($line -match '^ASR_MODEL_NAME=') {
        'ASR_MODEL_NAME=./models/funasr/snapshot'
    } else {
        $line
    }
}
if (-not ($packedEnv -match '^FLAGSHIP_API_KEY=.+')) { throw 'The approved flagship API key is missing.' }
if (-not ($packedEnv -match '^ASR_DEVICE=cuda$')) { throw 'ASR_DEVICE must be cuda for CUDA-first fallback.' }
Set-Content -LiteralPath (Join-Path $stageDir '.env') -Value $packedEnv -Encoding UTF8

Write-Host 'Copying the private Python runtime and application packages...'
$sourceBase = (& $sourceVenvPython -c 'import sys; print(sys.base_prefix)').Trim()
if (-not (Test-Path -LiteralPath (Join-Path $sourceBase 'python.exe'))) { throw "Python base is missing: $sourceBase" }
$stagePython = Join-Path $stageDir 'runtime\python'
Copy-LargeTree $sourceBase $stagePython
$stageVenv = Join-Path $stageDir '.venv'
New-Item -ItemType Directory -Force -Path (Join-Path $stageVenv 'Scripts'), (Join-Path $stageVenv 'Lib') | Out-Null
Copy-Item -LiteralPath $sourceVenvPython -Destination (Join-Path $stageVenv 'Scripts\python.exe')
Copy-Item -LiteralPath (Join-Path $projectDir '.venv\pyvenv.cfg') -Destination (Join-Path $stageVenv 'pyvenv.cfg')
Copy-LargeTree $sourceSitePackages (Join-Path $stageVenv 'Lib\site-packages')
$stageConfig = Join-Path $stageVenv 'pyvenv.cfg'
$configLines = Get-Content -LiteralPath $stageConfig
$configLines = foreach ($line in $configLines) {
    if ($line -match '^home\s*=') { "home = $stagePython" }
    elseif ($line -match '^executable\s*=') { "executable = $(Join-Path $stagePython 'python.exe')" }
    else { $line }
}
Set-Content -LiteralPath $stageConfig -Value $configLines -Encoding UTF8
& (Join-Path $stageVenv 'Scripts\python.exe') -c 'import sys, torch, funasr, fastapi; assert sys.prefix != sys.base_prefix; print("Bundled Python imports passed:", torch.__version__)'
if ($LASTEXITCODE -ne 0) { throw 'The relocated Python environment cannot import its dependencies.' }

Write-Host 'Copying Node.js, FFmpeg and the local speech model...'
$nodePath = (Get-Command node -ErrorAction Stop).Source
$ffmpegCommand = (Get-Command ffmpeg -ErrorAction Stop).Source
$ffmpegTarget = (Get-Item -LiteralPath $ffmpegCommand).Target
if (-not $ffmpegTarget) { $ffmpegTarget = $ffmpegCommand }
$ffprobeTarget = Join-Path (Split-Path $ffmpegTarget -Parent) 'ffprobe.exe'
if (-not (Test-Path -LiteralPath $ffprobeTarget)) { throw "ffprobe.exe is missing: $ffprobeTarget" }
New-Item -ItemType Directory -Force -Path (Join-Path $stageDir 'runtime\node'), (Join-Path $stageDir 'runtime\ffmpeg\bin') | Out-Null
Copy-Item -LiteralPath $nodePath -Destination (Join-Path $stageDir 'runtime\node\node.exe')
Copy-Item -LiteralPath $ffmpegTarget -Destination (Join-Path $stageDir 'runtime\ffmpeg\bin\ffmpeg.exe')
Copy-Item -LiteralPath $ffprobeTarget -Destination (Join-Path $stageDir 'runtime\ffmpeg\bin\ffprobe.exe')
Copy-LargeTree $modelSource (Join-Path $stageDir 'models\funasr\snapshot')
} else {
    Write-Host "Resuming a fully staged package: $stageDir"
    foreach ($required in @('web\server.js','runtime\python\python.exe','.venv\Scripts\python.exe','runtime\node\node.exe','models\funasr\snapshot\model.pt','.env')) {
        if (-not (Test-Path -LiteralPath (Join-Path $stageDir $required))) { throw "Resume input is missing: $required" }
    }
    Copy-Item -LiteralPath (Join-Path $projectDir 'docs\exe-portable-retest.md') -Destination (Join-Path $stageDir 'README.md') -Force
}

Write-Host 'Building the Windows launcher EXE...'
if (-not (Test-Path -LiteralPath $launcherPython)) {
    & (Get-Command python -ErrorAction Stop).Source -m venv $launcherVenv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the launcher build environment.' }
}
& $launcherPython -m pip install --disable-pip-version-check --timeout 120 --retries 5 'pyinstaller==6.16.0'
if ($LASTEXITCODE -ne 0) { throw 'Could not install the build-only PyInstaller package.' }
& $launcherPython -m PyInstaller --onefile --console --clean --noconfirm --name AIInterviewHub --distpath $stageDir --workpath (Join-Path $launcherBuildDir 'work') --specpath (Join-Path $launcherBuildDir 'spec') (Join-Path $projectDir 'scripts\portable\launcher.py')
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller could not build the launcher.' }

Write-Host 'Verifying package inputs...'
foreach ($required in @('AIInterviewHub.exe','web\server.js','runtime\python\python.exe','.venv\Scripts\python.exe','runtime\node\node.exe','runtime\ffmpeg\bin\ffmpeg.exe','models\funasr\snapshot\model.pt','README.md','.env')) {
    if (-not (Test-Path -LiteralPath (Join-Path $stageDir $required))) { throw "The finished package is missing: $required" }
}
Add-Type -AssemblyName System.IO.Compression.FileSystem
Write-Host 'Compressing the installer-free ZIP (this can take several minutes)...'
$stagePrefix = [System.IO.Path]::GetFullPath($stageDir).TrimEnd('\') + '\'
$zipStream = [System.IO.File]::Open($zipPath, [System.IO.FileMode]::CreateNew)
$archive = [System.IO.Compression.ZipArchive]::new($zipStream, [System.IO.Compression.ZipArchiveMode]::Create, $false)
$entryCount = 0
try {
    foreach ($file in Get-ChildItem -LiteralPath $stageDir -Recurse -File -Force) {
        $fullName = [System.IO.Path]::GetFullPath($file.FullName)
        if (-not $fullName.StartsWith($stagePrefix, [System.StringComparison]::OrdinalIgnoreCase)) { throw 'Unexpected file outside stage directory.' }
        $relative = $fullName.Substring($stagePrefix.Length).Replace('\','/')
        if ($relative -match '(^|/)(__pycache__|\.pytest_cache)(/|$)') { continue }
        if ($relative -match '^(logs|resumes|experiment_resumes)/') { continue }
        if ($relative.StartsWith('data/') -and $relative -notin @('data/jobs_seed.json','data/freshman_static.json')) { continue }
        if ($file.Extension.ToLowerInvariant() -in @('.log','.pyc','.pyo')) { continue }
        $entry = $archive.CreateEntry($relative, [System.IO.Compression.CompressionLevel]::Fastest)
        $inputStream = [System.IO.File]::OpenRead($fullName)
        $entryStream = $entry.Open()
        try { $inputStream.CopyTo($entryStream) }
        finally { $entryStream.Dispose(); $inputStream.Dispose() }
        $entryCount++
        if ($entryCount % 10000 -eq 0) { Write-Host "Archived $entryCount files..." }
    }
} finally {
    $archive.Dispose()
    $zipStream.Dispose()
}
Write-Host "Archived $entryCount files."
Write-Output "Portable EXE package: $zipPath"
Write-Output "Unpacked directory: $stageDir"
Write-Output 'The approved flagship API key is bundled; local databases and personal resumes are excluded.'
