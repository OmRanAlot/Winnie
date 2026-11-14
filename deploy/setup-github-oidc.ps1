# One-time setup so GitHub Actions can deploy to GCP without any stored keys
# (Workload Identity Federation). Run it yourself; it changes IAM on the project.
#
#   powershell -File deploy/setup-github-oidc.ps1 -DryRun    # print what it would do
#   powershell -File deploy/setup-github-oidc.ps1            # do it (safe to re-run)
#
# Only workflows from $Repo on the main branch can impersonate the deployer account.
# At the end it prints the two values to save as GitHub repo VARIABLES (not secrets).
param(
    [string]$ProjectId = "hack-princeton-514716",
    [string]$Region = "us-east1",
    [string]$Repo = "OmRanAlot/Winnie",
    [string]$PoolId = "github",
    [string]$ProviderId = "github-actions",
    [string]$DeployerName = "github-deployer",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

function Invoke-Gcloud {
    if ($DryRun) { Write-Host ("[dry-run] gcloud " + ($args -join " ")); return }
    & gcloud @args
    if ($LASTEXITCODE -ne 0) { throw "gcloud failed: $($args -join ' ')" }
}

function Test-Gcloud {
    # True when a "describe" command succeeds (the resource already exists).
    # Windows PowerShell 5.1 turns native stderr into a terminating error under "Stop";
    # a missing resource must return $false instead, so relax it for this one call.
    $ErrorActionPreference = "Continue"
    & gcloud @args 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

$number = (& gcloud projects describe $ProjectId --format="value(projectNumber)").Trim()
if (-not $number) { throw "Cannot read project $ProjectId. Run: gcloud auth login" }
$deployer = "$DeployerName@$ProjectId.iam.gserviceaccount.com"
$runtimeSa = "$number-compute@developer.gserviceaccount.com"
$providerName = "projects/$number/locations/global/workloadIdentityPools/$PoolId/providers/$ProviderId"

Write-Host "Project $ProjectId ($number), repo $Repo"

Invoke-Gcloud services enable iam.googleapis.com iamcredentials.googleapis.com sts.googleapis.com `
    cloudresourcemanager.googleapis.com firebasehosting.googleapis.com --project $ProjectId

# 1. Deployer service account.
if (-not (Test-Gcloud iam service-accounts describe $deployer --project $ProjectId)) {
    Invoke-Gcloud iam service-accounts create $DeployerName --display-name "GitHub Actions deployer" --project $ProjectId
}

# 2. Identity pool + GitHub provider, locked to this repo and the main branch.
if (-not (Test-Gcloud iam workload-identity-pools describe $PoolId --location global --project $ProjectId)) {
    Invoke-Gcloud iam workload-identity-pools create $PoolId --location global --display-name "GitHub" --project $ProjectId
}
$condition = "assertion.repository == '$Repo' && assertion.ref == 'refs/heads/main'"
if (-not (Test-Gcloud iam workload-identity-pools providers describe $ProviderId --workload-identity-pool $PoolId --location global --project $ProjectId)) {
    Invoke-Gcloud iam workload-identity-pools providers create-oidc $ProviderId `
        --workload-identity-pool $PoolId --location global --project $ProjectId `
        --issuer-uri "https://token.actions.githubusercontent.com" `
        --attribute-mapping "google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" `
        --attribute-condition $condition
} else {
    # Provider already exists: re-point its condition at $Repo (e.g. after the repo moved/was renamed).
    Invoke-Gcloud iam workload-identity-pools providers update-oidc $ProviderId `
        --workload-identity-pool $PoolId --location global --project $ProjectId `
        --attribute-condition $condition
}

# 3. Let identities from that repo impersonate the deployer.
Invoke-Gcloud iam service-accounts add-iam-policy-binding $deployer --project $ProjectId `
    --role roles/iam.workloadIdentityUser `
    --member "principalSet://iam.googleapis.com/projects/$number/locations/global/workloadIdentityPools/$PoolId/attribute.repository/$Repo" | Out-Null

# 4. What the deployer may do: deploy Cloud Run from source, and release to Firebase Hosting.
$projectRoles = @(
    "roles/run.admin",                         # deploy the service
    "roles/cloudbuild.builds.editor",          # build the image from source
    "roles/artifactregistry.writer",           # push it
    "roles/storage.objectAdmin",               # upload the source archive
    "roles/logging.viewer",                    # stream build logs
    "roles/serviceusage.serviceUsageConsumer", # use project APIs
    "roles/firebasehosting.admin"              # firebase deploy --only hosting
)
foreach ($role in $projectRoles) {
    Invoke-Gcloud projects add-iam-policy-binding $ProjectId --member "serviceAccount:$deployer" --role $role --condition=None | Out-Null
}
# Act as the account Cloud Run and Cloud Build run as (only that account, not project-wide).
Invoke-Gcloud iam service-accounts add-iam-policy-binding $runtimeSa --project $ProjectId `
    --member "serviceAccount:$deployer" --role roles/iam.serviceAccountUser | Out-Null

Write-Host ""
Write-Host "Done. In GitHub: Settings > Secrets and variables > Actions > Variables, add:"
Write-Host "  GCP_WORKLOAD_IDENTITY_PROVIDER = $providerName"
Write-Host "  GCP_SERVICE_ACCOUNT            = $deployer"
Write-Host "  VITE_API_BASE_URL              = /api"
Write-Host "  VITE_SUPABASE_URL              = https://<your-ref>.supabase.co"
Write-Host "  VITE_SUPABASE_PUBLISHABLE_KEY  = <publishable key; public by design, never the secret key>"
