# Creates two authenticated scheduled HTTP jobs on the existing API; no always-running worker.
param(
 [string]$ProjectId='hack-princeton-514716',
 [string]$Region='us-east1',
 [string]$Service='api',
 [switch]$EnableSheetsAutoApply
)
$ErrorActionPreference='Stop'
$repoRoot=Split-Path $PSScriptRoot -Parent
function Invoke-Gcloud([Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments) {
 & gcloud @Arguments
 if ($LASTEXITCODE -ne 0) {throw 'Google Cloud command failed; later setup steps were not run.'}
}
if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) {throw 'Use a computer with gcloud installed and signed in to this project.'}
$backendPath=Join-Path $repoRoot 'backend'
$pythonPath=@((Join-Path $backendPath '.venv-auth/Scripts/python.exe'),(Join-Path $backendPath '.venv/Scripts/python.exe')) |
 Where-Object {Test-Path -LiteralPath $_} | Select-Object -First 1
if (-not $pythonPath) {throw 'Run uv sync in backend first.'}
Push-Location $backendPath
try {
 & $pythonPath -c 'from app.services.automation import AutomationStore; AutomationStore()._execute("automation_jobs",lambda q:q.select("key").limit(0)); print("Automation migration verified.")'
 if ($LASTEXITCODE -ne 0) {throw 'Apply migrations through 20261115200000_notification_automation.sql first.'}
 # Read only the configured source list; no secret values are printed or copied.
 $serviceJson=& gcloud run services describe $Service --project $ProjectId --region $Region --format=json
 if ($LASTEXITCODE -ne 0) {throw 'Could not read the existing API configuration.'}
 $existing=$serviceJson | ConvertFrom-Json
 $sourcesJson=$null
 if ($EnableSheetsAutoApply) {
  $sourceEnv=$existing.spec.template.spec.containers[0].env | Where-Object {$_.name -eq 'WINNIE_SHEET_SYNC_SOURCES'}
  if (-not $sourceEnv.value) {throw 'Configure WINNIE_SHEET_SYNC_SOURCES on Cloud Run before enabling automatic apply.'}
  $sources=@($sourceEnv.value | ConvertFrom-Json)
  if (-not $sources.Count) {throw 'At least one tracker source is required.'}
  foreach ($source in $sources) {$source | Add-Member -NotePropertyName auto_apply -NotePropertyValue $true -Force}
  $sourcesJson=ConvertTo-Json -InputObject $sources -Compress -Depth 12
 }
 Invoke-Gcloud @('run','deploy',$Service,'--source','.','--project',$ProjectId,'--region',$Region,'--quiet')
 $apiUrl=& gcloud run services describe $Service --project $ProjectId --region $Region --format='value(status.url)'
 if ($LASTEXITCODE -ne 0 -or -not $apiUrl) {throw 'Could not resolve the deployed API URL.'}
 $ready=Invoke-RestMethod -Uri "$apiUrl/api/photon/webhook"
 if (-not $ready.enabled -or -not $ready.configured) {throw 'Complete setup-photon-webhook.ps1 before enabling scheduled delivery.'}
 Invoke-Gcloud @('services','enable','cloudscheduler.googleapis.com','--project',$ProjectId)
 $account="winnie-scheduler@$ProjectId.iam.gserviceaccount.com"
 & gcloud iam service-accounts describe $account --project $ProjectId 2>$null | Out-Null
 if ($LASTEXITCODE -ne 0) {Invoke-Gcloud @('iam','service-accounts','create','winnie-scheduler','--project',$ProjectId,'--display-name=Winnie scheduled automation')}
 Invoke-Gcloud @('run','services','add-iam-policy-binding',$Service,'--project',$ProjectId,'--region',$Region,"--member=serviceAccount:$account",'--role=roles/run.invoker','--quiet')
 $envVars="WINNIE_NOTIFICATIONS_ENABLED=true,WINNIE_REMINDERS_ENABLED=true,WINNIE_REMINDER_TRANSPORT=photon,WINNIE_SCHEDULER_SERVICE_ACCOUNT=$account,WINNIE_SCHEDULER_AUDIENCE=$apiUrl"
 Invoke-Gcloud @('run','services','update',$Service,'--project',$ProjectId,'--region',$Region,'--update-env-vars',$envVars,'--quiet')
 if ($sourcesJson) {
  $delimiter=[guid]::NewGuid().ToString('N')
  Invoke-Gcloud @('run','services','update',$Service,'--project',$ProjectId,'--region',$Region,'--update-env-vars',"^$delimiter^WINNIE_SHEET_SYNC_SOURCES=$sourcesJson",'--quiet')
 }
 foreach ($kind in @('reminders','sheets')) {
  $job="winnie-$kind"
  & gcloud scheduler jobs describe $job --location $Region --project $ProjectId 2>$null | Out-Null
  $verb=if ($LASTEXITCODE -eq 0) {'update'} else {'create'}
  $jobArgs=@('scheduler','jobs',$verb,'http',$job,'--project',$ProjectId,'--location',$Region,
   '--schedule=*/5 * * * *','--time-zone=America/New_York',"--uri=$apiUrl/api/internal/automation/$kind",
   '--http-method=POST',"--oidc-service-account-email=$account","--oidc-token-audience=$apiUrl",
   '--attempt-deadline=180s','--max-retry-attempts=3','--min-backoff=30s','--max-backoff=60s','--quiet')
  Invoke-Gcloud @jobArgs
 }
 Write-Host 'Scheduled reminder/notification scans and Sheets runner configured on the existing API.'
 Write-Host 'Check Automation and notifications in Admin Settings after the next five-minute tick.'
 if (-not $EnableSheetsAutoApply) {Write-Host 'Sheets sources remain unchanged: only sources already marked auto_apply=true will write.'}
} finally {Pop-Location}
