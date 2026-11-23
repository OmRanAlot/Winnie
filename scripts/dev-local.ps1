# Start the backend and frontend locally for pre-deploy testing.
# Uses your existing .env files (Supabase, Gemini, Photon, bridge secret) unchanged.
# Run from the repository root:
#
#   powershell -ExecutionPolicy Bypass -File .\scripts\dev-local.ps1
#   powershell -ExecutionPolicy Bypass -File .\scripts\dev-local.ps1 -Messaging
#   powershell -ExecutionPolicy Bypass -File .\scripts\dev-local.ps1 -SkipInstall -BackendPort 8000 -FrontendPort 5174
#
# Dashboard: http://localhost:5173  (override with -FrontendPort)
# API docs:  http://localhost:8000/docs
# Photon SMS/iMessage testing: .\scripts\test-photon.ps1 help

[CmdletBinding()]
param(
    [switch]$Messaging,
    [switch]$SkipInstall,
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path $PSScriptRoot -Parent
$backendPath = Join-Path $repoRoot 'backend'
$frontendPath = Join-Path $repoRoot 'frontend'
$messagingPath = Join-Path $repoRoot 'messaging'
$processes = [System.Collections.Generic.List[System.Diagnostics.Process]]::new()

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
        # Do not clobber vars already set in this shell.
        if (-not [string]::IsNullOrEmpty([Environment]::GetEnvironmentVariable($name))) { return }
        Set-Item -Path "Env:$name" -Value $value
    }
}

function Get-EnvValue([string]$Name) {
    $value = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($value)) { return $null }
    return $value.Trim()
}

function Require-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Missing required command: $Name"
    }
}

# Start-Process cannot launch PowerShell shim scripts (npm.ps1). Prefer .cmd / .exe.
function Resolve-NativeCommand([string]$Name) {
    foreach ($candidate in @("$Name.cmd", "$Name.exe", $Name)) {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandType -eq 'Application' } |
            Select-Object -First 1
        if ($cmd -and $cmd.Source -and ($cmd.Source -notmatch '\.ps1$')) {
            return $cmd.Source
        }
    }
    throw "Could not resolve a native executable for '$Name' (need $Name.cmd or $Name.exe)."
}

function Start-LoggedProcess {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$ArgumentList,
        [Parameter(Mandatory)][string]$WorkingDirectory,
        [Parameter(Mandatory)][string]$Label
    )
    $exe = Resolve-NativeCommand $FilePath
    Write-Host "Starting $Label..."
    # .cmd/.bat must go through cmd.exe; Start-Process on npm.cmd raises
    # "%1 is not a valid Win32 application" on Windows. npm.ps1 is unusable here.
    if ($exe -match '\.(cmd|bat)$') {
        $quotedArgs = @(
            foreach ($arg in $ArgumentList) {
                if ($arg -match '[\s"]') { '"' + ($arg -replace '"', '""') + '"' } else { $arg }
            }
        )
        $cmdline = '"' + $exe + '" ' + ($quotedArgs -join ' ')
        $proc = Start-Process -FilePath $env:ComSpec `
            -ArgumentList @('/d', '/c', $cmdline) `
            -WorkingDirectory $WorkingDirectory -PassThru -NoNewWindow
    } else {
        $proc = Start-Process -FilePath $exe -ArgumentList $ArgumentList `
            -WorkingDirectory $WorkingDirectory -PassThru -NoNewWindow
    }
    $processes.Add($proc) | Out-Null
    Start-Sleep -Milliseconds 800
    if ($proc.HasExited) {
        throw "$Label exited immediately (code $($proc.ExitCode)). Check that folder's .env and dependencies."
    }
    return $proc
}

function Stop-ProcessTree([System.Diagnostics.Process]$Process) {
    if (-not $Process) { return }
    if (-not $Process.HasExited) {
        # /T kills child node/uvicorn reload workers that would otherwise hold the port.
        & taskkill.exe /PID $Process.Id /T /F 2>$null | Out-Null
    }
}

function Initialize-PhotonBridgeEnv {
    # messaging/ may have a stale .env; prefer process env already loaded from backend/.env.
    if (-not (Get-EnvValue 'PROJECT_ID')) {
        $id = Get-EnvValue 'WINNIE_PHOTON_PROJECT_ID'
        if ($id) { Set-Item -Path Env:PROJECT_ID -Value $id }
    }
    if (-not (Get-EnvValue 'PROJECT_SECRET')) {
        $secret = Get-EnvValue 'WINNIE_PHOTON_PROJECT_SECRET'
        if (-not $secret) { $secret = Get-EnvValue 'PROJECT_SECRET' }
        if ($secret) { Set-Item -Path Env:PROJECT_SECRET -Value $secret }
    }
    if (-not (Get-EnvValue 'MESSAGING_BRIDGE_SECRET')) {
        $bridge = Get-EnvValue 'WINNIE_MESSAGING_BRIDGE_SECRET'
        if ($bridge) { Set-Item -Path Env:MESSAGING_BRIDGE_SECRET -Value $bridge }
    }
    Set-Item -Path Env:BACKEND_URL -Value "http://127.0.0.1:$BackendPort"

    if (-not (Get-EnvValue 'PROJECT_ID') -or -not (Get-EnvValue 'PROJECT_SECRET')) {
        throw 'Photon PROJECT_ID/PROJECT_SECRET missing. Set them in messaging/.env or WINNIE_PHOTON_* in backend/.env.'
    }
    if (-not (Get-EnvValue 'MESSAGING_BRIDGE_SECRET')) {
        throw 'MESSAGING_BRIDGE_SECRET missing. Set it in messaging/.env and match WINNIE_MESSAGING_BRIDGE_SECRET in backend/.env.'
    }
    $photonEnabled = Get-EnvValue 'WINNIE_PHOTON_ENABLED'
    if ($photonEnabled -and $photonEnabled.ToLowerInvariant() -eq 'true') {
        Write-Warning 'WINNIE_PHOTON_ENABLED=true: local messaging gets reply=null (webhook mode). Set it false in backend/.env for laptop Photon testing.'
    }
}

try {
    Require-Command uv
    Require-Command npm
    Require-Command node

    if (-not (Test-Path -LiteralPath $backendPath)) { throw "backend/ not found under $repoRoot" }
    if (-not (Test-Path -LiteralPath $frontendPath)) { throw "frontend/ not found under $repoRoot" }

    Import-DotEnvFile (Join-Path $repoRoot '.env')
    Import-DotEnvFile (Join-Path $backendPath '.env')
    Import-DotEnvFile (Join-Path $frontendPath '.env')
    if ($Messaging) {
        Import-DotEnvFile (Join-Path $messagingPath '.env')
        Initialize-PhotonBridgeEnv
    }

    if (-not (Get-EnvValue 'SUPABASE_URL') -and -not (Get-EnvValue 'WINNIE_SUPABASE_URL')) {
        Write-Warning 'Supabase URL not found in .env. Tasks API will return 503 until SUPABASE_URL is set.'
    }
    if (-not (Get-EnvValue 'GEMINI_API_KEY') -and -not (Get-EnvValue 'GOOGLE_API_KEY') -and -not (Get-EnvValue 'WINNIE_GEMINI_API_KEY')) {
        Write-Warning 'GEMINI_API_KEY not found in .env. Task extraction / message AI will be unavailable.'
    }

    if (-not $SkipInstall) {
        Write-Host 'Syncing backend dependencies (uv sync)...'
        Push-Location $backendPath
        try { & uv sync } finally { Pop-Location }
        if ($LASTEXITCODE -ne 0) { throw 'uv sync failed' }

        Write-Host 'Installing frontend dependencies...'
        Push-Location $frontendPath
        try { & npm install } finally { Pop-Location }
        if ($LASTEXITCODE -ne 0) { throw 'frontend npm install failed' }

        if ($Messaging) {
            Write-Host 'Installing messaging dependencies...'
            Push-Location $messagingPath
            try { & npm install } finally { Pop-Location }
            if ($LASTEXITCODE -ne 0) { throw 'messaging npm install failed' }
        }
    }

    if ($FrontendPort -lt 1 -or $FrontendPort -gt 65535) {
        throw "-FrontendPort must be between 1 and 65535 (got $FrontendPort)."
    }
    if ($BackendPort -lt 1 -or $BackendPort -gt 65535) {
        throw "-BackendPort must be between 1 and 65535 (got $BackendPort)."
    }
    if ($FrontendPort -eq $BackendPort) {
        throw "-FrontendPort and -BackendPort cannot be the same ($FrontendPort)."
    }

    # Point Vite's /api proxy at this backend port (inherited by the frontend child process).
    Set-Item -Path Env:WINNIE_DEV_API_PROXY -Value "http://127.0.0.1:$BackendPort"

    # Backend: --local sets WINNIE_MODE=local for this process only (reload + 127.0.0.1).
    Start-LoggedProcess -FilePath 'uv' -ArgumentList @('run', 'python', '-m', 'app.cli.serve', '--local', '--port', "$BackendPort") `
        -WorkingDirectory $backendPath -Label 'backend (local)'

    # Pass port after `--` so Vite receives it (avoid relying on PowerShell `--` forwarding).
    Start-LoggedProcess -FilePath 'npm' -ArgumentList @('run', 'dev:local', '--', '--port', "$FrontendPort", '--strictPort') `
        -WorkingDirectory $frontendPath -Label "frontend (port $FrontendPort)"

    if ($Messaging) {
        # npm start loads messaging/.env; process env above fills any missing Photon/bridge keys.
        Start-LoggedProcess -FilePath 'npm' -ArgumentList @('start') `
            -WorkingDirectory $messagingPath -Label 'messaging (Photon listener)'
    }

    Write-Host ''
    Write-Host "Local stack is up (mode=local). API http://127.0.0.1:$BackendPort  dashboard http://localhost:$FrontendPort"
    Write-Host 'Outside services (Supabase, Gemini, Photon) use your existing .env values.'
    if ($Messaging) {
        Write-Host 'Photon listener is running. Text ping / help / whoami to the project iMessage line,'
        Write-Host 'or use:  .\scripts\test-photon.ps1 send -To +1YOURNUMBER -Text "hello from Winnie"'
    } else {
        Write-Host 'Photon: re-run with -Messaging, or use .\scripts\test-photon.ps1 (send / listen / chat).'
    }
    Write-Host 'Press Ctrl+C to stop all local processes.'
    Write-Host ''

    while ($true) {
        foreach ($proc in @($processes)) {
            if ($proc.HasExited) {
                throw "$($proc.StartInfo.FileName) exited (code $($proc.ExitCode)). Stopping the rest of the local stack."
            }
        }
        Start-Sleep -Seconds 1
    }
}
finally {
    Write-Host 'Stopping local processes...'
    foreach ($proc in @($processes)) {
        Stop-ProcessTree $proc
    }
}
