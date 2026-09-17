[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidatePattern('^(?:\d{1,3}\.){3}\d{1,3}$')]
    [string]$IpAddress,
    [string]$AccountName = "db-cosmos-basic-test"
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

$rules = @($account.ipRules | ForEach-Object { $_.ipAddressOrRange })
if ($IpAddress -notin $rules) {
    $rules += $IpAddress
    & $az cosmosdb update `
        --name $AccountName `
        --resource-group $account.resourceGroup `
        --ip-range-filter ($rules -join ",") `
        --only-show-errors | Out-Null
    Write-Host "Added $IpAddress to $AccountName firewall rules."
} else {
    Write-Host "$IpAddress is already present in $AccountName firewall rules."
}
