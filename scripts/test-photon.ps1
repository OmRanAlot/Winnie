# Local Photon iMessage test CLI. Uses the number YOU pass — not roster numbers in Supabase.
# Run from the repository root.
#
# Prerequisites:
#   1. Add your phone (or iMessage email) under Users in https://app.photon.codes
#   2. PROJECT_ID / PROJECT_SECRET in messaging/.env, or WINNIE_PHOTON_* in backend/.env
#   3. For -Bridge: local backend running and matching bridge secrets
#
# Examples:
#   .\scripts\test-photon.ps1 send -To +15551234567 -Text "hello from Winnie"
#   .\scripts\test-photon.ps1 listen -From +15551234567
#   .\scripts\test-photon.ps1 chat -To +15551234567
#   .\scripts\test-photon.ps1 chat -To +15551234567 -Bridge
#
# Full bot (listener + backend + frontend):  .\scripts\dev-local.ps1 -Messaging
# then text ping / help / whoami from your phone to the Photon project line.

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('send', 'listen', 'chat', 'help')]
    [string]$Command = 'help',

    [string]$To,
    [string]$From,

    [Alias('m')]
    [string]$Text,

    [switch]$Bridge,
    [string]$BackendUrl = 'http://127.0.0.1:8000'
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path $PSScriptRoot -Parent
$messagingPath = Join-Path $repoRoot 'messaging'
$backendPath = Join-Path $repoRoot 'backend'

function Import-DotEnvFile {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return }
    Get-Content -LiteralPath $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith('#')) { return }
        $eq = $line.IndexOf('=')
        if ($eq -lt 1) { return }
        $name = $line.Substring(0, $eq).Trim()
        $value = $line.Substring($eq + 1).Trim()
        if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        if ([string]::IsNullOrWhiteSpace($name)) { return }
        if (-not [string]::IsNullOrEmpty([Environment]::GetEnvironmentVariable($name))) { return }
        Set-Item -Path "Env:$name" -Value $value
    }
}

function Get-EnvValue([string]$Name) {
    $value = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($value)) { return $null }
    return $value.Trim()
}

# Load secrets into this process without printing them. Node --env-file will not override these.
Import-DotEnvFile (Join-Path $repoRoot '.env')
Import-DotEnvFile (Join-Path $backendPath '.env')
Import-DotEnvFile (Join-Path $messagingPath '.env')

if (-not (Get-EnvValue 'PROJECT_ID')) {
    $id = Get-EnvValue 'WINNIE_PHOTON_PROJECT_ID'
    if ($id) { Set-Item -Path Env:PROJECT_ID -Value $id }
}
if (-not (Get-EnvValue 'PROJECT_SECRET')) {
    $secret = Get-EnvValue 'WINNIE_PHOTON_PROJECT_SECRET'
    if ($secret) { Set-Item -Path Env:PROJECT_SECRET -Value $secret }
}
if (-not (Get-EnvValue 'MESSAGING_BRIDGE_SECRET')) {
    $bridgeSecret = Get-EnvValue 'WINNIE_MESSAGING_BRIDGE_SECRET'
    if ($bridgeSecret) { Set-Item -Path Env:MESSAGING_BRIDGE_SECRET -Value $bridgeSecret }
}
Set-Item -Path Env:BACKEND_URL -Value $BackendUrl

if (-not (Test-Path -LiteralPath (Join-Path $messagingPath 'package.json'))) {
    throw 'messaging/ not found. Run this script from the repository root (.\scripts\test-photon.ps1 ...).'
}

if ($Command -eq 'help') {
    Write-Host @"
Photon local test — pass YOUR number; roster numbers in Supabase are never used.
Run every command from the repository root.

  .\scripts\test-photon.ps1 send  -To +1YOURNUMBER -Text "hello from Winnie"
  .\scripts\test-photon.ps1 listen -From +1YOURNUMBER
  .\scripts\test-photon.ps1 chat  -To +1YOURNUMBER
  .\scripts\test-photon.ps1 chat  -To +1YOURNUMBER -Bridge

-Bridge forwards inbound DMs to the local backend (/api/messages) and texts the reply.
Add your handle under Photon dashboard → Users before sending.
Full stack: .\scripts\dev-local.ps1 -Messaging
"@
    exit 0
}

if ($Command -eq 'send') {
    if (-not $To) { throw 'send requires -To +1YOURNUMBER' }
    if (-not $Text) { throw 'send requires -Text "message"' }
}
elseif ($Command -eq 'listen') {
    if (-not $From -and -not $To) { throw 'listen requires -From +1YOURNUMBER' }
}
elseif ($Command -eq 'chat') {
    if (-not $To -and -not $From) { throw 'chat requires -To +1YOURNUMBER' }
}

if (-not (Test-Path -LiteralPath (Join-Path $messagingPath 'node_modules'))) {
    Write-Host 'Installing messaging dependencies...'
    Push-Location $messagingPath
    try { & npm install } finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) { throw 'npm install failed in messaging/' }
}

$npmArgs = @('run', 'test:photon', '--', $Command)
if ($To) { $npmArgs += @('--to', $To) }
if ($From) { $npmArgs += @('--from', $From) }
if ($Text) { $npmArgs += @('--text', $Text) }
if ($Bridge) { $npmArgs += @('--bridge') }
if ($BackendUrl) { $npmArgs += @('--backend', $BackendUrl) }

Push-Location $messagingPath
try {
    # Pass args as an array so PowerShell does not drop `--`.
    & npm @npmArgs
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
