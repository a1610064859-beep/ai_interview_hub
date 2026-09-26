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
$localUrl = 'http://127.0.0.1:3000/api/jobs'
try {
    $response = Invoke-WebRequest -Uri $localUrl -UseBasicParsing -TimeoutSec 10
    $payload = $response.Content | ConvertFrom-Json
    if ($response.StatusCode -ne 200 -or $null -eq $payload.jobs) { throw 'Unexpected API response' }
} catch {
    throw "Start the local website and API first; $localUrl is unavailable."
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmin = ([Security.Principal.WindowsPrincipal]$identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { throw 'Run this script once from an Administrator PowerShell window.' }

$alreadyListening = Get-NetTCPConnection -LocalAddress $vpnIp -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if (-not $alreadyListening) {
    & netsh interface portproxy add v4tov4 "listenaddress=$vpnIp" "listenport=$Port" `
        'connectaddress=127.0.0.1' 'connectport=3000' 'protocol=tcp' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the Radmin VPN portproxy rule.' }
}

$ruleName = "AI Interview Hub - Radmin VPN TCP $Port"
if (-not (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow `
        -Protocol TCP -LocalPort $Port -RemoteAddress '26.0.0.0/8' -InterfaceAlias 'Radmin VPN' | Out-Null
}

$url = "http://${vpnIp}:$Port/api/jobs"
try {
    $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 10
    $payload = $response.Content | ConvertFrom-Json
    if ($response.StatusCode -ne 200 -or $null -eq $payload.jobs) { throw 'Unexpected API response' }
} catch {
    throw "Radmin listener was created, but $url is unavailable. Check the IP Helper service and firewall."
}
Write-Host "Radmin VPN entry ready: http://${vpnIp}:$Port/"
Write-Host 'The website forwards uploads to the API on this computer. Remote clients should use connect_radmin_client.ps1 for microphone access.'
