$ErrorActionPreference = 'Stop'
$projectDir = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$distDir = Join-Path $projectDir 'dist'
$stageRoot = Join-Path $env:TEMP ('ai-interview-hub-stage-' + [Guid]::NewGuid().ToString('N'))
$bundleDir = Join-Path $stageRoot 'AIInterviewHub'
$zipPath = Join-Path $distDir ('AIInterviewHub-Portable-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.zip')
$excludedDirectories = @('.git','.venv','node_modules','.next','.pytest_cache','__pycache__','.codegraph','.taromcp','.workbuddy','memory','tmp','dist','runtime','models','logs','audio','resumes','experiment_resumes')
$excludedExtensions = @('.log','.db','.sqlite','.sqlite3','.mp3','.wav','.webm','.pdf')

$envPath = Join-Path $projectDir '.env'
if (-not (Test-Path -LiteralPath $envPath)) { throw 'Project .env is missing; configure the API before packaging.' }
$envLines = Get-Content -LiteralPath $envPath -Encoding UTF8
if (-not ($envLines -match '^FLAGSHIP_API_KEY=.+')) { throw 'FLAGSHIP_API_KEY is empty; package creation stopped.' }
if (-not ($envLines -match '^FLAGSHIP_MODEL=swe-2-max$')) { throw 'Project .env flagship model must be swe-2-max.' }
New-Item -ItemType Directory -Force -Path $bundleDir,$distDir | Out-Null

function Copy-PortableTree([string]$source, [string]$destination) {
    foreach ($item in Get-ChildItem -LiteralPath $source -Force) {
        if ($item.PSIsContainer) {
            if ($excludedDirectories -contains $item.Name) { continue }
            $next = Join-Path $destination $item.Name
            New-Item -ItemType Directory -Force -Path $next | Out-Null
            Copy-PortableTree $item.FullName $next
            continue
        }
        if ($item.Name.StartsWith('.env') -and $item.Name -notin @('.env','.env.example')) { continue }
        $relative = $item.FullName.Substring($projectDir.Length).TrimStart([char[]]@(92,47)) -replace '\\','/'
        if ($relative.StartsWith('data/') -and $relative -notin @('data/jobs_seed.json','data/freshman_static.json')) { continue }
        if ($relative -eq 'scripts/walkthrough_session.py') { continue }
        if ($excludedExtensions -contains $item.Extension.ToLowerInvariant()) { continue }
        if ($item.Name -match '\.(db|sqlite|sqlite3)([-.]|$)') { continue }
        Copy-Item -LiteralPath $item.FullName -Destination (Join-Path $destination $item.Name) -Force
    }
}
Copy-PortableTree $projectDir $bundleDir

$bundleEnvPath = Join-Path $bundleDir '.env'
$bundleEnv = Get-Content -LiteralPath $bundleEnvPath -Encoding UTF8
$bundleEnv = foreach ($line in $bundleEnv) {
    if ($line -match '^([A-Z0-9_]*(API_KEY|SECRET|TOKEN|PASSWORD)[A-Z0-9_]*)=' -and $Matches[1] -ne 'FLAGSHIP_API_KEY') {
        $Matches[1] + '='
    } else { $line }
}
Set-Content -LiteralPath $bundleEnvPath -Value $bundleEnv -Encoding UTF8

Add-Type -AssemblyName System.IO.Compression
$bundlePrefix = [System.IO.Path]::GetFullPath($bundleDir).TrimEnd([char[]]@([System.IO.Path]::DirectorySeparatorChar,[System.IO.Path]::AltDirectorySeparatorChar)) + [System.IO.Path]::DirectorySeparatorChar
$archiveStream = [System.IO.File]::Open($zipPath, [System.IO.FileMode]::CreateNew)
$archive = [System.IO.Compression.ZipArchive]::new($archiveStream, [System.IO.Compression.ZipArchiveMode]::Create, $false)
try {
    foreach ($file in Get-ChildItem -LiteralPath $bundleDir -Recurse -File -Force) {
        $fullName = [System.IO.Path]::GetFullPath($file.FullName)
        if (-not $fullName.StartsWith($bundlePrefix, [System.StringComparison]::OrdinalIgnoreCase)) { throw 'Unexpected file outside the staging directory.' }
        $entryName = $fullName.Substring($bundlePrefix.Length).Replace('\','/')
        $entry = $archive.CreateEntry($entryName, [System.IO.Compression.CompressionLevel]::Optimal)
        $sourceStream = [System.IO.File]::OpenRead($file.FullName)
        $entryStream = $entry.Open()
        try { $sourceStream.CopyTo($entryStream) }
        finally { $entryStream.Dispose(); $sourceStream.Dispose() }
    }
} finally {
    $archive.Dispose()
    $archiveStream.Dispose()
}
$sizeMb = [Math]::Round((Get-Item -LiteralPath $zipPath).Length / 1MB, 1)
Write-Output "Portable package created: $zipPath ($sizeMb MB)"
Write-Output 'Bundled the approved flagship API key; excluded local databases, personal files, caches, downloaded runtimes, model weights and node_modules.'
