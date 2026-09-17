[CmdletBinding()]
param(
    [string]$ResourceGroup = "rg-db-test",
    [string]$WorkspaceName = "law-cosmos-query-test",
    [string]$RuleName = "cosmos-actionable-errors-excluding-400-1004"
)

$ErrorActionPreference = "Stop"
$az = (Get-Command az -ErrorAction SilentlyContinue).Source
if (-not $az) { $az = "C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd" }

$workspaceId = & $az monitor log-analytics workspace show --resource-group $ResourceGroup --workspace-name $WorkspaceName --query id --output tsv --only-show-errors
$subscriptionId = & $az account show --query id --output tsv --only-show-errors
$query = @'
AppEvents
| where Name in ("CosmosQueryPlanFallback", "CosmosRequest")
| where TimeGenerated >= ago(5m)
| extend Cosmos = parse_json(Properties)
| extend StatusCode = toint(Cosmos.statusCode), SubstatusCode = toint(Cosmos.substatusCode)
| where StatusCode >= 400
| where not(StatusCode == 400 and SubstatusCode == 1004)
| summarize AggregatedValue = sum(ItemCount)
'@

$body = @{ location = "koreacentral"; properties = @{
    description = "Alerts on custom Cosmos request telemetry after excluding expected Gateway query-plan 400/1004 responses."
    enabled = $true; severity = 2; evaluationFrequency = "PT5M"; windowSize = "PT5M"
    scopes = @($workspaceId); targetResourceTypes = @("Microsoft.OperationalInsights/workspaces")
    criteria = @{ allOf = @(@{ query = $query; timeAggregation = "Count"; operator = "GreaterThan"; threshold = 0; failingPeriods = @{ numberOfEvaluationPeriods = 1; minFailingPeriodsToAlert = 1 } }) }
    autoMitigate = $true; actions = @{ actionGroups = @(); customProperties = @{} }
} } | ConvertTo-Json -Depth 10

$bodyPath = Join-Path $env:TEMP "$RuleName.json"
$body | Set-Content -Path $bodyPath -Encoding utf8
$uri = "/subscriptions/$subscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.Insights/scheduledQueryRules/$RuleName"
& $az rest --method put --uri $uri --url-parameters "api-version=2021-08-01" --body "@$bodyPath" --only-show-errors --output json
Remove-Item $bodyPath -Force