param(
    [int]$Port = 3000
)

$ErrorActionPreference = 'Stop'
if ($Port -lt 1 -or $Port -gt 65535) { throw 'Port must be between 1 and 65535.' }

$addresses = @(Get-NetIPAddress -InterfaceAlias 'Radmin VPN' -AddressFamily IPv4 -ErrorAction Stop |
    Where-Object { $_.IPAddress -match '^26\.' -and $_.AddressState -eq 'Preferred' })
if ($addresses.Count -ne 1) {
    throw 'Expected one ready Radmin VPN IPv4 address. Connect Radmin VPN and retry.'
}

$vpnIp = $addresses[0].IPAddress
if ($Port -ne 3000) { throw 'Radmin exposes only the frontend port 3000.' }

$localUrl = 'http://127.0.0.1:3000/api/jobs'
try {
    $response = Invoke-WebRequest -Uri $localUrl -UseBasicParsing -TimeoutSec 10
    $payload = $response.Content | ConvertFrom-Json
    if ($response.StatusCode -ne 200 -or $null -eq $payload.jobs) { throw 'Unexpected API response' }
} catch {
    throw "Start the local website and API first; $localUrl is unavailable."
}

$pattern = "^\s*$([regex]::Escape($vpnIp))\s+$Port\s+(\S+)\s+(\d+)\s*$"
$existingRule = @(netsh interface portproxy show v4tov4) |
    Where-Object { $_ -match $pattern } | Select-Object -First 1

if ($existingRule) {
    if ($existingRule -notmatch "^\s*$([regex]::Escape($vpnIp))\s+$Port\s+127\.0\.0\.1\s+$Port\s*$") {
        throw "Radmin port $Port already forwards to a different destination: $existingRule"
    }
} else {
    $alreadyListening = Get-NetTCPConnection -LocalAddress $vpnIp -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($alreadyListening) { throw "Radmin address $vpnIp already has another listener on port $Port." }
    & netsh interface portproxy add v4tov4 "listenaddress=$vpnIp" "listenport=$Port" `
        'connectaddress=127.0.0.1' "connectport=$Port" 'protocol=tcp' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not create the Radmin VPN portproxy rule for port $Port." }
}

$ruleName = "AI Interview Hub - Radmin VPN TCP $Port"
$firewallRule = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
$needsFirewallChange = -not $firewallRule -or @($firewallRule | Where-Object { $_.Enabled -eq 'True' }).Count -eq 0

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmin = ([Security.Principal.WindowsPrincipal]$identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin -and (-not $existingRule -or $needsFirewallChange)) {
    $scriptPath = '"' + $PSCommandPath + '"'
    $arguments = "-NoProfile -ExecutionPolicy Bypass -File $scriptPath -Port $Port"
    $elevated = Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList $arguments -Wait -PassThru
    if ($elevated.ExitCode -ne 0) { throw "Elevated Radmin setup failed with exit code $($elevated.ExitCode)." }
    Write-Host "Radmin VPN website is ready: http://${vpnIp}:3000/"
    exit 0
}

if ($needsFirewallChange) {
    if ($firewallRule) {
        $firewallRule | Enable-NetFirewallRule | Out-Null
    } else {
        New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow `
            -Protocol TCP -LocalPort $Port -RemoteAddress '26.0.0.0/8' -InterfaceAlias 'Radmin VPN' | Out-Null
    }
}

$url = "http://${vpnIp}:$Port/api/jobs"
try {
    $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 10
    $payload = $response.Content | ConvertFrom-Json
    if ($response.StatusCode -ne 200 -or $null -eq $payload.jobs) { throw 'Unexpected API response' }
} catch {
    throw "Radmin listener was created, but $url is unavailable. Check the IP Helper service and firewall."
}
Write-Host "Radmin website ready: http://${vpnIp}:$Port/"
Write-Host 'The website forwards uploads to the API on this computer. Remote clients should use connect_radmin_client.ps1 for microphone access.'
