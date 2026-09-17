[CmdletBinding()]
param(
    [string]$AccountName = "db-cosmos-basic-test",
    [string]$ResourceGroup = "rg-db-test",
    [string]$VnetName = "vm-working-dbtest-vnet",
    [string]$SubnetName = "default",
    [string]$PrivateEndpointName = "pe-cosmos-query-test",
    [string]$PrivateDnsZoneName = "privatelink.documents.azure.com"
)

$ErrorActionPreference = "Stop"
$az = (Get-Command az -ErrorAction SilentlyContinue).Source
if (-not $az) {
    $az = "C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"
}
if (-not (Test-Path $az)) {
    throw "Azure CLI (az) is required."
}

$accountId = & $az cosmosdb show --name $AccountName --resource-group $ResourceGroup --query id --output tsv --only-show-errors
$subnetId = & $az network vnet subnet show --resource-group $ResourceGroup --vnet-name $VnetName --name $SubnetName --query id --output tsv --only-show-errors
$vnetId = & $az network vnet show --resource-group $ResourceGroup --name $VnetName --query id --output tsv --only-show-errors
if (-not $accountId -or -not $subnetId -or -not $vnetId) {
    throw "Cosmos DB account, VNet, or subnet was not found."
}

$zoneExists = & $az network private-dns zone list --resource-group $ResourceGroup --query "[?name=='$PrivateDnsZoneName'] | length(@)" --output tsv --only-show-errors
if ($zoneExists -eq "0") {
    & $az network private-dns zone create --resource-group $ResourceGroup --name $PrivateDnsZoneName --only-show-errors | Out-Null
}

$linkName = "$VnetName-cosmos"
$linkExists = & $az network private-dns link vnet list --resource-group $ResourceGroup --zone-name $PrivateDnsZoneName --query "[?name=='$linkName'] | length(@)" --output tsv --only-show-errors
if ($linkExists -eq "0") {
    & $az network private-dns link vnet create --resource-group $ResourceGroup --zone-name $PrivateDnsZoneName --name $linkName --virtual-network $vnetId --registration-enabled false --only-show-errors | Out-Null
}

$endpointExists = & $az network private-endpoint list --resource-group $ResourceGroup --query "[?name=='$PrivateEndpointName'] | length(@)" --output tsv --only-show-errors
if ($endpointExists -eq "0") {
    & $az network private-endpoint create --resource-group $ResourceGroup --name $PrivateEndpointName --vnet-name $VnetName --subnet $SubnetName --private-connection-resource-id $accountId --group-ids Sql --connection-name "$PrivateEndpointName-connection" --no-wait --only-show-errors | Out-Null
}

$state = ""
for ($attempt = 1; $attempt -le 30 -and $state -ne "Succeeded"; $attempt++) {
    Start-Sleep -Seconds 10
    $state = & $az network private-endpoint show --resource-group $ResourceGroup --name $PrivateEndpointName --query provisioningState --output tsv --only-show-errors 2>$null
}
if ($state -ne "Succeeded") {
    throw "Private Endpoint provisioning did not complete within 5 minutes. Current state: $state"
}

$zoneGroupName = "cosmos-private-dns"
$zoneGroupExists = & $az network private-endpoint dns-zone-group list --resource-group $ResourceGroup --endpoint-name $PrivateEndpointName --query "[?name=='$zoneGroupName'] | length(@)" --output tsv --only-show-errors
if ($zoneGroupExists -eq "0") {
    & $az network private-endpoint dns-zone-group create --resource-group $ResourceGroup --endpoint-name $PrivateEndpointName --name $zoneGroupName --private-dns-zone $PrivateDnsZoneName --zone-name cosmos --only-show-errors | Out-Null
}

& $az cosmosdb update --name $AccountName --resource-group $ResourceGroup --public-network-access Disabled --only-show-errors | Out-Null
& $az network private-endpoint show --resource-group $ResourceGroup --name $PrivateEndpointName --query "{name:name,privateIp:customDnsConfigs[0].ipAddresses[0],connectionState:privateLinkServiceConnections[0].privateLinkServiceConnectionState.status}" --output json --only-show-errors
Write-Host "Private Endpoint is configured. Clients must run in, or be connected to, $VnetName and use its DNS path."
