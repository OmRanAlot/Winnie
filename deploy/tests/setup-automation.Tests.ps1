# Offline regression checks; runs the deployment helpers without changing cloud resources.
param([string]$PythonPath)
$ErrorActionPreference='Stop'
$repoRoot=Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if (-not $PythonPath) {$PythonPath=Join-Path $repoRoot 'backend/.venv/Scripts/python.exe'}
$tokens=$null
$parseErrors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile(
 (Join-Path $repoRoot 'deploy/setup-automation.ps1'),[ref]$tokens,[ref]$parseErrors)
if ($parseErrors.Count) {throw ($parseErrors | Out-String)}
$ast.FindAll({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst]},$false) |
 ForEach-Object {Invoke-Expression $_.Extent.Text}
function Assert($Condition,[string]$Message) {if (-not $Condition) {throw $Message}}

$testRoot=Join-Path ([IO.Path]::GetTempPath()) ('automation test '+[guid]::NewGuid().ToString('N'))
$null=New-Item -ItemType Directory -Path $testRoot
$capturePath=Join-Path $testRoot 'capture.py'
$resultPath=Join-Path $testRoot 'result.json'
try {
 # Model gcloud.ps1 launching Python, including the native Windows argument boundary.
 @'
import json
import pathlib
import sys
result_path, exit_code, *args = sys.argv[1:]
flags_path = pathlib.Path(args[args.index("--flags-file") + 1])
flags = json.loads(flags_path.read_text(encoding="utf-8"))
pathlib.Path(result_path).write_text(json.dumps({"path": str(flags_path), "flags": flags}), encoding="utf-8")
sys.exit(int(exit_code))
'@ | Set-Content -LiteralPath $capturePath
 $script:exitCode=0
 function gcloud { & $PythonPath $capturePath $resultPath $script:exitCode @args }
 $source=@{key='tracker';spreadsheet_id='test-sheet';semester_code='fall-2026';tab_name=('Budget, "Sponsors"  '+[char]0x00e9);auto_apply=$true}
 $sourceJson=ConvertTo-Json -InputObject @($source) -Compress
 Invoke-GcloudWithEnvironment -Arguments @('run','services','update','test-api') -Environment @{
  WINNIE_SHEET_SYNC_SOURCES=$sourceJson;WINNIE_REMINDERS_ENABLED='true'
 }
 $captured=Get-Content -LiteralPath $resultPath -Raw -Encoding UTF8 | ConvertFrom-Json
 Assert ($captured.flags.'--update-env-vars'.WINNIE_SHEET_SYNC_SOURCES -ceq $sourceJson) 'JSON changed across native process boundary.'
 Assert (-not (Test-Path -LiteralPath $captured.path)) 'Flags file was not removed after success.'
 Assert ($captured.flags.PSObject.Properties.Name -notcontains '--env-vars-file') 'Update must not replace unrelated environment variables.'
 $script:exitCode=1
 $caught=$false
 try {Invoke-GcloudWithEnvironment -Arguments @('run','services','update','test-api') -Environment @{TEST='value'}} catch {$caught=$true}
 Assert $caught 'A failed gcloud command must stop setup.'
 $captured=Get-Content -LiteralPath $resultPath -Raw | ConvertFrom-Json
 Assert (-not (Test-Path -LiteralPath $captured.path)) 'Flags file was not removed after failure.'
 Assert ($ErrorActionPreference -eq 'Stop') 'Native error preference leaked.'

 # Recover a corrupted template from the healthy revision, without borrowing its other vars.
 $source.auto_apply=$false
 $healthySources=ConvertTo-Json -InputObject @($source) -Compress
 $script:revisionJson=ConvertTo-Json -Depth 12 -InputObject @{
  spec=@{containers=@(@{env=@(@{name='WINNIE_SHEET_SYNC_SOURCES';value=$healthySources},@{name='UNRELATED';value='keep-private'})})}
 }
 $script:lookupCount=0
 function Invoke-Gcloud([string[]]$Arguments) {
  Assert ($Arguments[0..3] -join ' ' -eq 'run revisions describe healthy-revision') 'Wrong revision lookup.'
  $script:lookupCount++
  return $script:revisionJson
 }
 $service=@{
  spec=@{template=@{spec=@{containers=@(@{env=@(@{name='WINNIE_SHEET_SYNC_SOURCES';value='[{key:broken}]'})})}}}
  status=@{latestReadyRevisionName='healthy-revision'}
 }
 $recovered=Get-AutomationSheetSources $service 'test-project' 'us-east1'
 $parsed=ConvertFrom-Json -InputObject $recovered
 $parsed=@($parsed)
 Assert ($recovered.StartsWith('[') -and $parsed.Count -eq 1) 'Single source must remain a JSON array.'
 Assert ($parsed[0].auto_apply -eq $true) 'Recovered source must enable auto-apply.'
 Assert ($parsed[0].tab_name -ceq $source.tab_name) 'Recovery changed the source selector.'
 Assert ($script:lookupCount -eq 1) 'Recovery did not read the healthy revision.'
 $service.spec.template.spec.containers[0].env[0].value=$healthySources
 $null=Get-AutomationSheetSources $service 'test-project' 'us-east1'
 Assert ($script:lookupCount -eq 1) 'Valid current configuration must not be replaced from a revision.'
 $otherSource=$source.Clone()
 $otherSource.key='second'
 $service.spec.template.spec.containers[0].env[0].value=ConvertTo-Json -InputObject @($source,$otherSource) -Compress
 $multiple=Get-AutomationSheetSources $service 'test-project' 'us-east1' | ConvertFrom-Json
 Assert ($multiple.Count -eq 2 -and $multiple[0].auto_apply -and $multiple[1].auto_apply) 'Every source must enable auto-apply.'
 $service.spec.template.spec.containers[0].env[0].value='[]'
 $caught=$false
 try {Get-AutomationSheetSources $service 'test-project' 'us-east1'} catch {$caught=$true}
 Assert $caught 'Empty source lists must stop setup.'
 $service.spec.template.spec.containers[0].env[0].value='[{key:broken}]'
 $service.status.latestReadyRevisionName=$null
 $caught=$false
 try {Get-AutomationSheetSources $service 'test-project' 'us-east1'} catch {$caught=$true}
 Assert $caught 'Corrupted JSON without a healthy revision must stop setup.'
 Write-Host 'PASS: native JSON round trip, cleanup, command failure, recovery, and source arrays.'
} finally {
 foreach ($path in @($capturePath,$resultPath)) {
  if (Test-Path -LiteralPath $path) {Remove-Item -LiteralPath $path -Force}
 }
 Remove-Item -LiteralPath $testRoot
}
