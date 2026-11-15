# Sets the backend's secrets and env vars on the Cloud Run service "api".
#
# Run from anywhere:  pwsh -File deploy/set-cloud-run-env.ps1   (or powershell -File ...)
# You are prompted for each value; input is hidden for secrets. Press Enter to skip one
# (an existing value is kept). Secrets go to Secret Manager and are mounted into Cloud Run;
# nothing is written to disk except a short-lived temp file that is deleted right away.
#
# Deliberately NOT set: WINNIE_ENVIRONMENT and WINNIE_TASK_API_KEY. The frontend does not send
# the X-Winnie-Api-Key header, so setting either would make /api/members return 503/401.
param(
    [string]$ProjectId = "hack-princeton-514716",
    [string]$Region = "us-east1",
    [string]$Service = "api"
)

# Not "Stop": Windows PowerShell 5.1 treats gcloud's progress output on stderr as a fatal
# error. Failures are caught by checking $LASTEXITCODE after each gcloud call instead.
$ErrorActionPreference = "Continue"

# Secret Manager secret name == the env var name the backend reads.
$SecretNames = @("GEMINI_API_KEY", "SUPABASE_SECRET_KEY", "WINNIE_MESSAGING_BRIDGE_SECRET")

function Read-Plain([string]$Prompt, [bool]$Hidden) {
    if (-not $Hidden) { return (Read-Host $Prompt).Trim() }
    $secure = Read-Host $Prompt -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr).Trim() }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}

function Save-Secret([string]$Name, [string]$Value) {
    # Write without a trailing newline: piping adds one and would corrupt API keys.
    $tmp = [IO.Path]::GetTempFileName()
    try {
        [IO.File]::WriteAllText($tmp, $Value, (New-Object Text.UTF8Encoding $false))
        # Windows PowerShell 5.1 treats native stderr as fatal under "Stop"; a missing
        # secret is expected here, so relax it for this one check.
        $prev = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        gcloud secrets describe $Name --project $ProjectId 2>$null | Out-Null
        $exists = ($LASTEXITCODE -eq 0)
        $ErrorActionPreference = $prev
        if ($exists) {
            gcloud secrets versions add $Name --data-file=$tmp --project $ProjectId | Out-Null
        } else {
            gcloud secrets create $Name --data-file=$tmp --replication-policy=automatic --project $ProjectId | Out-Null
        }
        if ($LASTEXITCODE -ne 0) { throw "Could not save secret $Name" }
    } finally {
        Remove-Item $tmp -Force -ErrorAction SilentlyContinue
    }
}

gcloud services enable secretmanager.googleapis.com --project $ProjectId

# Service account the service runs as (falls back to the default compute account).
$sa = gcloud run services describe $Service --region $Region --project $ProjectId `
    --format="value(spec.template.spec.serviceAccountName)"
if (-not $sa) {
    $number = gcloud projects describe $ProjectId --format="value(projectNumber)"
    $sa = "$number-compute@developer.gserviceaccount.com"
}
Write-Host "Cloud Run runs as: $sa"

$secretMounts = @()
foreach ($name in $SecretNames) {
    $value = Read-Plain "Value for $name (Enter to skip)" $true
    if (-not $value) { continue }
    Save-Secret $name $value
    gcloud secrets add-iam-policy-binding $name --project $ProjectId `
        --member="serviceAccount:$sa" --role="roles/secretmanager.secretAccessor" | Out-Null
    $secretMounts += "$name=$($name):latest"
}

# Always pin the deployed service to prod mode (local mode only exists via `python -m app.cli.serve --local`).
$envVars = @("WINNIE_MODE=prod")
$supabaseUrl = Read-Plain "SUPABASE_URL, e.g. https://<ref>.supabase.co (Enter to skip)" $false
if ($supabaseUrl) { $envVars += "SUPABASE_URL=$supabaseUrl" }

$updateArgs = @("run", "services", "update", $Service, "--region", $Region, "--project", $ProjectId)
if ($secretMounts) {
    # Cloud Run refuses to turn an existing plain env var into a secret reference of the
    # same name, so drop any plain-text copy in the same update (the secret replaces it).
    $mountedNames = $secretMounts | ForEach-Object { ($_ -split "=")[0] }
    $updateArgs += @("--remove-env-vars", ($mountedNames -join ","))
    $updateArgs += @("--update-secrets", ($secretMounts -join ","))
}
if ($envVars) {
    # Same type-conflict rule in the other direction: drop any secret reference of that name.
    $plainNames = $envVars | ForEach-Object { ($_ -split "=")[0] }
    $updateArgs += @("--remove-secrets", ($plainNames -join ","))
    $updateArgs += @("--update-env-vars", ($envVars -join ","))
}

if ($secretMounts -or $envVars) {
    gcloud @updateArgs
    if ($LASTEXITCODE -ne 0) { throw "gcloud run services update failed" }
    Write-Host "Done. Check: gcloud run services logs read $Service --region $Region --limit 20"
} else {
    Write-Host "Nothing entered; service left unchanged."
}
