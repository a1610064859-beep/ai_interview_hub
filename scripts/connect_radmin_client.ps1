param(
    [Parameter(Mandatory = $true)]
    [string]$ServerIp,
    [int]$LocalPort = 3000,
    [int]$ServerPort = 3000
)

$ErrorActionPreference = 'Stop'
if ($LocalPort -lt 1 -or $LocalPort -gt 65535 -or $ServerPort -lt 1 -or $ServerPort -gt 65535) {
    throw 'Ports must be between 1 and 65535.'
}
$parsedIp = $null
if (-not [Net.IPAddress]::TryParse($ServerIp, [ref]$parsedIp) -or
    $parsedIp.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork -or
    $ServerIp -notmatch '^26\.') {
    throw 'ServerIp must be the server Radmin VPN IPv4 address (26.x.x.x).'
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmin = ([Security.Principal.WindowsPrincipal]$identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { throw 'Run PowerShell as Administrator to create the local tunnel.' }
if (-not (Get-NetIPAddress -InterfaceAlias 'Radmin VPN' -AddressFamily IPv4 -ErrorAction SilentlyContinue)) {
    throw 'Join the same Radmin VPN network as the server before connecting.'
}
if (Get-NetTCPConnection -LocalPort $LocalPort -State Listen -ErrorAction SilentlyContinue) {
    throw "Local port $LocalPort is already in use. Choose another LocalPort or remove the old portproxy rule."
}

& netsh interface portproxy add v4tov4 "listenaddress=127.0.0.1" "listenport=$LocalPort" `
    "connectaddress=$ServerIp" "connectport=$ServerPort" "protocol=tcp" | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Could not create the local portproxy rule.' }

$url = "http://127.0.0.1:$LocalPort/"
try {
    $response = Invoke-WebRequest -Uri "${url}api/jobs" -UseBasicParsing -TimeoutSec 10
    $payload = $response.Content | ConvertFrom-Json
    if ($response.StatusCode -ne 200 -or $null -eq $payload.jobs) { throw 'Unexpected API response' }
} catch {
    throw "Tunnel created, but the website is unavailable at $url. Check Radmin VPN and the server firewall."
}
Write-Host "Ready: $url"
Write-Host 'Open this localhost URL on this client. The browser can use the microphone, and audio uploads to the server through Radmin VPN.'
