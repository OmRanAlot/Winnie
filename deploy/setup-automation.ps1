# Creates two authenticated scheduled HTTP jobs on the existing API; no always-running worker.
param(
 [string]$ProjectId='hack-princeton-514716',
 [string]$Region='us-east1',
 [string]$Service='api',
 [switch]$EnableSheetsAutoApply,
 # Resume configuration using the deployed image after a successful build.
 [switch]$SkipBuild
)
$ErrorActionPreference='Stop'
$repoRoot=Split-Path $PSScriptRoot -Parent
# Takes one string[] (call as Invoke-Gcloud @('a','b') or Invoke-Gcloud $list); never splat, which would bind only the first item.
function Invoke-Gcloud([string[]]$Arguments) {
 # gcloud.ps1 writes native stderr even for successful progress messages.
 # Keep this preference local and use the process exit code to detect failure.
 $ErrorActionPreference='Continue'
 & gcloud @Arguments
 if ($LASTEXITCODE -ne 0) {throw 'Google Cloud command failed; later setup steps were not run.'}
}
function Test-GcloudResource([string[]]$Arguments) {
 $ErrorActionPreference='Continue'
 $result=& gcloud @Arguments 2>&1
 if ($LASTEXITCODE -eq 0) {return $true}
 if (($result | Out-String) -match '\bNOT_FOUND\b') {return $false}
 throw "Google Cloud resource lookup failed; later setup steps were not run.`n$($result | Out-String)"
}
function Invoke-GcloudWithEnvironment([string[]]$Arguments, [hashtable]$Environment) {
 # A flags file preserves JSON quotes across gcloud.ps1's native process boundary.
 # Use update-env-vars, not env-vars-file, to retain unrelated vars and secret refs.
 $flagsPath=[IO.Path]::GetTempFileName()
 try {
  $flags=ConvertTo-Json -InputObject @{'--update-env-vars'=$Environment} -Depth 12
  [IO.File]::WriteAllText($flagsPath,$flags,(New-Object Text.UTF8Encoding $false))
  Invoke-Gcloud ($Arguments + @('--flags-file',$flagsPath))
 } finally {Remove-Item -LiteralPath $flagsPath -Force}
}
function Get-AutomationSheetSources($ServiceConfig, [string]$ProjectId, [string]$Region) {
 $sourceEnv=$ServiceConfig.spec.template.spec.containers[0].env | Where-Object {$_.name -eq 'WINNIE_SHEET_SYNC_SOURCES'}
 if (-not $sourceEnv.value) {throw 'Configure WINNIE_SHEET_SYNC_SOURCES on Cloud Run before enabling automatic apply.'}
 try {$sources=ConvertFrom-Json -InputObject $sourceEnv.value} catch {
  # Failed updates still change the template. Recover only this setting from a
  # healthy revision; never guess missing quotes or copy unrelated configuration.
  $readyRevision=$ServiceConfig.status.latestReadyRevisionName
  if (-not $readyRevision) {throw 'Sheets sources are invalid JSON and no healthy revision is available to recover them.'}
  $revisionJson=Invoke-Gcloud @('run','revisions','describe',$readyRevision,'--project',$ProjectId,'--region',$Region,'--format=json')
  $revision=$revisionJson | ConvertFrom-Json
  $sourceEnv=$revision.spec.containers[0].env | Where-Object {$_.name -eq 'WINNIE_SHEET_SYNC_SOURCES'}
  if (-not $sourceEnv.value) {throw 'The healthy revision has no Sheets sources to recover.'}
  $sources=ConvertFrom-Json -InputObject $sourceEnv.value
  Write-Host "Recovered Sheets sources from healthy revision $readyRevision."
 }
 # Windows PowerShell emits JSON arrays as one pipeline object. Normalize after
 # assignment to avoid wrapping the source array inside another array.
 $sources=@($sources)
 if (-not $sources.Count) {throw 'At least one tracker source is required.'}
 foreach ($source in $sources) {$source | Add-Member -NotePropertyName auto_apply -NotePropertyValue $true -Force}
 return ConvertTo-Json -InputObject $sources -Compress -Depth 12
}
if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) {throw 'Use a computer with gcloud installed and signed in to this project.'}
$backendPath=Join-Path $repoRoot 'backend'
$pythonPath=@((Join-Path $backendPath '.venv-auth/Scripts/python.exe'),(Join-Path $backendPath '.venv/Scripts/python.exe')) |
 Where-Object {Test-Path -LiteralPath $_} | Select-Object -First 1
if (-not $pythonPath) {throw 'Run uv sync in backend first.'}
Push-Location $backendPath
try {
 # Pass source over stdin: Windows PowerShell 5.1 strips embedded quotes in native arguments.
 @'
from app.services.automation import AutomationStore
AutomationStore()._execute("automation_jobs", lambda q: q.select("key").limit(0))
print("Automation migration verified.")
'@ | & $pythonPath -
 if ($LASTEXITCODE -ne 0) {throw 'Automation preflight failed; see the Python error above. Check backend configuration and migrations through 20261115200000_notification_automation.sql.'}
 # Read only the configured source list; no secret values are printed or copied.
 $serviceJson=Invoke-Gcloud @('run','services','describe',$Service,'--project',$ProjectId,'--region',$Region,'--format=json')
 $existing=$serviceJson | ConvertFrom-Json
 $sourcesJson=$null
 if ($EnableSheetsAutoApply) {
  $sourcesJson=Get-AutomationSheetSources -ServiceConfig $existing -ProjectId $ProjectId -Region $Region
 }
 $apiUrl=$existing.status.url
 if (-not $apiUrl) {throw 'Could not resolve the deployed API URL.'}
 $ready=Invoke-RestMethod -Uri "$apiUrl/api/photon/webhook"
 if (-not $ready.enabled -or -not $ready.configured) {throw 'Complete setup-photon-webhook.ps1 before enabling scheduled delivery.'}
 Invoke-Gcloud @('services','enable','cloudscheduler.googleapis.com','--project',$ProjectId)
 $account="winnie-scheduler@$ProjectId.iam.gserviceaccount.com"
 if (-not (Test-GcloudResource @('iam','service-accounts','describe',$account,'--project',$ProjectId))) {
  Invoke-Gcloud @('iam','service-accounts','create','winnie-scheduler','--project',$ProjectId,'--display-name=Winnie scheduled automation')
 }
 Invoke-Gcloud @('run','services','add-iam-policy-binding',$Service,'--project',$ProjectId,'--region',$Region,"--member=serviceAccount:$account",'--role=roles/run.invoker','--quiet')
 $envVars=@{
  WINNIE_NOTIFICATIONS_ENABLED='true'
  WINNIE_REMINDERS_ENABLED='true'
  WINNIE_REMINDER_TRANSPORT='photon'
  WINNIE_SCHEDULER_SERVICE_ACCOUNT=$account
  WINNIE_SCHEDULER_AUDIENCE=$apiUrl
 }
 if ($sourcesJson) {$envVars.WINNIE_SHEET_SYNC_SOURCES=$sourcesJson}
 # Apply all settings in the same revision, including any recovered sources.
 $deployArgs=if ($SkipBuild) {@('run','services','update',$Service)} else {@('run','deploy',$Service,'--source','.')}
 $deployArgs+=@('--project',$ProjectId,'--region',$Region,'--quiet')
 Invoke-GcloudWithEnvironment -Arguments $deployArgs -Environment $envVars
 $ready=Invoke-RestMethod -Uri "$apiUrl/api/photon/webhook"
 if (-not $ready.enabled -or -not $ready.configured) {throw 'The deployed API is not ready for scheduled delivery.'}
 foreach ($kind in @('reminders','sheets')) {
  $job="winnie-$kind"
  $verb=if (Test-GcloudResource @('scheduler','jobs','describe',$job,'--location',$Region,'--project',$ProjectId)) {'update'} else {'create'}
  $jobArgs=@('scheduler','jobs',$verb,'http',$job,'--project',$ProjectId,'--location',$Region,
   '--schedule=*/5 * * * *','--time-zone=America/New_York',"--uri=$apiUrl/api/internal/automation/$kind",
   '--http-method=POST',"--oidc-service-account-email=$account","--oidc-token-audience=$apiUrl",
   '--attempt-deadline=180s','--max-retry-attempts=3','--min-backoff=30s','--max-backoff=60s','--quiet')
  Invoke-Gcloud $jobArgs
 }
 Write-Host 'Scheduled reminder/notification scans and Sheets runner configured on the existing API.'
 Write-Host 'Check Automation and notifications in Admin Settings after the next five-minute tick.'
 if (-not $EnableSheetsAutoApply) {Write-Host 'Sheets sources remain unchanged: only sources already marked auto_apply=true will write.'}
} finally {Pop-Location}
