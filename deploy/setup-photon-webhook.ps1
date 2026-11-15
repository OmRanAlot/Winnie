# Run from the repository root after applying the webhook SQL migration.
# Uses an existing gcloud login; updates the existing API and creates only a request-driven queue.
param(
 [string]$ProjectId='hack-princeton-514716',
 [string]$Region='us-east1',
 [string]$Service='api',
 [string]$Queue='winnie-photon',
 [string]$WebhookUrl='https://hack-princeton-514716.web.app/api/photon/webhook'
)
$ErrorActionPreference='Continue'
$repoRoot=Split-Path $PSScriptRoot -Parent
$backendPath=Join-Path $repoRoot 'backend'
if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) {throw 'Install Google Cloud CLI and run gcloud auth login first.'}
$pythonCandidates=@((Join-Path $backendPath '.venv-auth/Scripts/python.exe'),(Join-Path $backendPath '.venv/Scripts/python.exe'))
$pythonPath=$pythonCandidates | Where-Object {Test-Path -LiteralPath $_} | Select-Object -First 1
if (-not $pythonPath) {throw 'Run uv sync in backend first so its Python dependencies are available.'}
function Invoke-Gcloud([Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments) {
 & gcloud @Arguments
 if ($LASTEXITCODE -ne 0) {throw 'Google Cloud command failed. No later setup steps were run.'}
}
Push-Location $backendPath
try {
 # An absent migration fails before a deployment or webhook registration.
 & $pythonPath -c 'from app.integrations.photon import PhotonInbox; PhotonInbox()._execute("photon_inbox", lambda q: q.select("id").limit(0)); print("Webhook inbox migration verified.")'
 if ($LASTEXITCODE -ne 0) {throw 'Apply 20261115170000_photon_webhook_inbox.sql first (after the shared workflow migrations).'}
 # This first deploy adds the route, initially disabled until credentials are configured.
 Invoke-Gcloud @('run','deploy',$Service,'--source','.','--project',$ProjectId,'--region',$Region,'--quiet')
 $runtime=& gcloud run services describe $Service --project $ProjectId --region $Region --format='value(spec.template.spec.serviceAccountName)'
 if ($LASTEXITCODE -ne 0) {throw 'Could not identify the API runtime service account.'}
 if (-not $runtime) {
  $number=& gcloud projects describe $ProjectId --format='value(projectNumber)'
  if ($LASTEXITCODE -ne 0) {throw 'Could not identify project number.'}
  $runtime="$number-compute@developer.gserviceaccount.com"
 }
 $apiUrl=& gcloud run services describe $Service --project $ProjectId --region $Region --format='value(status.url)'
 if ($LASTEXITCODE -ne 0 -or -not $apiUrl) {throw 'Could not identify API URL.'}
 Invoke-Gcloud @('services','enable','cloudtasks.googleapis.com','secretmanager.googleapis.com','--project',$ProjectId)
 & gcloud tasks queues describe $Queue --location $Region --project $ProjectId 2>$null | Out-Null
 if ($LASTEXITCODE -ne 0) {
  Invoke-Gcloud @('tasks','queues','create',$Queue,'--location',$Region,'--project',$ProjectId,'--max-concurrent-dispatches=1','--max-dispatches-per-second=2','--max-attempts=20','--min-backoff=10s','--max-backoff=60s')
 }
 # Scope enqueue permission to this queue, not the whole project.
 Invoke-Gcloud @('tasks','queues','add-iam-policy-binding',$Queue,'--location',$Region,'--project',$ProjectId,"--member=serviceAccount:$runtime",'--role=roles/cloudtasks.enqueuer','--quiet')
 & $pythonPath -m app.cli.photon_webhook --url $WebhookUrl
 if ($LASTEXITCODE -ne 0) {throw 'Webhook registration not completed; check deployed route and Photon credentials.'}
 # Capture private settings in memory, never print them to the terminal.
 $configText=& $pythonPath -c 'import json; from app.core.settings import Settings; s=Settings(); print(json.dumps({"project_id":s.photon_project_id,"project_secret":s.photon_project_secret.get_secret_value(),"webhook_id":s.photon_webhook_id,"webhook_secret":s.photon_webhook_secret.get_secret_value()}))'
 if ($LASTEXITCODE -ne 0) {throw 'Could not load saved Photon settings.'}
 $config=$configText | ConvertFrom-Json
 $secrets=@{'WINNIE_PHOTON_PROJECT_SECRET'=$config.project_secret;'WINNIE_PHOTON_WEBHOOK_SECRET'=$config.webhook_secret}
 foreach ($name in $secrets.Keys) {
  $secretTemp=[IO.Path]::GetTempFileName()
  try {
   [IO.File]::WriteAllText($secretTemp,$secrets[$name],(New-Object Text.UTF8Encoding $false))
   & gcloud secrets describe $name --project $ProjectId 2>$null | Out-Null
   if ($LASTEXITCODE -eq 0) {Invoke-Gcloud @('secrets','versions','add',$name,"--data-file=$secretTemp",'--project',$ProjectId)}
   else {Invoke-Gcloud @('secrets','create',$name,"--data-file=$secretTemp",'--replication-policy=automatic','--project',$ProjectId)}
   Invoke-Gcloud @('secrets','add-iam-policy-binding',$name,'--project',$ProjectId,"--member=serviceAccount:$runtime",'--role=roles/secretmanager.secretAccessor','--quiet')
  } finally {Remove-Item -LiteralPath $secretTemp -Force -ErrorAction SilentlyContinue}
 }
 $envVars=@('WINNIE_PHOTON_ENABLED=true',"WINNIE_PHOTON_PROJECT_ID=$($config.project_id)","WINNIE_PHOTON_WEBHOOK_ID=$($config.webhook_id)","WINNIE_PHOTON_QUEUE=projects/$ProjectId/locations/$Region/queues/$Queue", "WINNIE_PHOTON_TASK_URL=$apiUrl/api/photon/work",'WINNIE_MESSAGE_AI_ENABLED=true','WINNIE_HELP_WORKFLOW_ENABLED=true')
 Invoke-Gcloud @('run','services','update',$Service,'--project',$ProjectId,'--region',$Region,'--update-env-vars',($envVars -join ','),'--update-secrets','WINNIE_PHOTON_PROJECT_SECRET=WINNIE_PHOTON_PROJECT_SECRET:latest,WINNIE_PHOTON_WEBHOOK_SECRET=WINNIE_PHOTON_WEBHOOK_SECRET:latest','--quiet')
 $status=Invoke-RestMethod -Uri $WebhookUrl
 if (-not $status.enabled -or -not $status.configured) {throw 'Route deployed, but readiness is incomplete. Check Cloud Run settings.'}
 Write-Host 'Webhook route is enabled and configured. Stop the local Photon listener, then text ping to verify end-to-end delivery.'
} finally {Pop-Location}
