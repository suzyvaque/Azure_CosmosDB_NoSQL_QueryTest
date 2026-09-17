[CmdletBinding()]
param(
    [string]$AccountName = "db-cosmos-basic-test",
    [int]$Minutes = 30
)

$ErrorActionPreference = "Stop"
$az = (Get-Command az -ErrorAction SilentlyContinue).Source
if (-not $az) {
    $az = "C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"
}
$account = @(& $az cosmosdb list --query "[?name=='$AccountName']" --output json --only-show-errors | ConvertFrom-Json)[0]
if (-not $account) {
    throw "Cosmos DB account '$AccountName' was not found in the active subscription."
}

$end = (Get-Date).ToUniversalTime()
$start = $end.AddMinutes(-$Minutes)
& $az monitor metrics list `
    --resource $account.id `
    --metric ServiceAvailability `
    --interval PT1H `
    --aggregation Average `
    --start-time $start.ToString("o") `
    --end-time $end.ToString("o") `
    --output table `
    --only-show-errors
