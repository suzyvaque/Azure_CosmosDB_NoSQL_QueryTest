[CmdletBinding()]
param(
    [string]$AccountName = "db-cosmos-basic-test",
    [string]$DatabaseName = "chatbot-test",
    [string]$ContainerName = "sessions",
    [string]$WorkspaceName = "law-cosmos-query-test",
    [string]$PrincipalId,
    [switch]$SkipRoleAssignment
)

$ErrorActionPreference = "Stop"

$az = (Get-Command az -ErrorAction SilentlyContinue).Source
if (-not $az) {
    $installedAz = "C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"
    if (Test-Path $installedAz) {
        $az = $installedAz
    }
}
if (-not $az) {
    throw "Azure CLI (az) is required."
}

& $az account show --only-show-errors | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Azure CLI is not logged in. Run 'az login' and select the target subscription."
}
$accounts = @(& $az cosmosdb list --query "[?name=='$AccountName']" --output json --only-show-errors | ConvertFrom-Json)
if ($accounts.Count -eq 0) {
    throw "Cosmos DB account '$AccountName' was not found in the active subscription."
}
if ($accounts.Count -gt 1) {
    throw "More than one account named '$AccountName' was returned. Select the intended subscription first."
}

$account = $accounts[0]
$resourceGroup = $account.resourceGroup
$location = $account.location
$accountId = $account.id
$endpoint = $account.documentEndpoint

Write-Host "Using $accountId"
Write-Host "Creating database '$DatabaseName' and container '$ContainerName'..."
& $az cosmosdb sql database create `
    --account-name $AccountName `
    --resource-group $resourceGroup `
    --name $DatabaseName `
    --only-show-errors | Out-Null

& $az cosmosdb sql container create `
    --account-name $AccountName `
    --resource-group $resourceGroup `
    --database-name $DatabaseName `
    --name $ContainerName `
    --partition-key-path "/session_id" `
    --throughput 400 `
    --only-show-errors | Out-Null

if (-not $SkipRoleAssignment) {
    if (-not $PrincipalId) {
        $PrincipalId = & $az ad signed-in-user show --query id --output tsv --only-show-errors
    }
    if (-not $PrincipalId) {
        throw "Could not resolve a principal. Pass -PrincipalId with a user or managed identity object ID."
    }

    $roleDefinitionId = "$accountId/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002"
    $existingAssignment = & $az cosmosdb sql role assignment list `
        --account-name $AccountName `
        --resource-group $resourceGroup `
        --query "[?principalId=='$PrincipalId' && roleDefinitionId=='$roleDefinitionId'] | [0].id" `
        --output tsv `
        --only-show-errors

    if (-not $existingAssignment) {
        Write-Host "Assigning Cosmos DB Built-in Data Contributor to principal $PrincipalId..."
        & $az cosmosdb sql role assignment create `
            --account-name $AccountName `
            --resource-group $resourceGroup `
            --scope "/" `
            --principal-id $PrincipalId `
            --role-definition-id $roleDefinitionId `
            --only-show-errors | Out-Null
    }
}

$workspaceId = & $az monitor log-analytics workspace list `
    --resource-group $resourceGroup `
    --query "[?name=='$WorkspaceName'] | [0].id" `
    --output tsv `
    --only-show-errors

if (-not $workspaceId) {
    Write-Host "Creating Log Analytics workspace '$WorkspaceName'..."
    $workspaceId = & $az monitor log-analytics workspace create `
        --resource-group $resourceGroup `
        --workspace-name $WorkspaceName `
        --location $location `
        --query id `
        --output tsv `
        --only-show-errors
}

$diagnosticName = "cosmos-query-test-logs"
& $az monitor diagnostic-settings create `
    --name $diagnosticName `
    --resource $accountId `
    --workspace $workspaceId `
    --export-to-resource-specific true `
    --logs '[{"categoryGroup":"allLogs","enabled":true}]' `
    --metrics '[{"category":"AllMetrics","enabled":true}]' `
    --only-show-errors | Out-Null

@"
COSMOS_ENDPOINT=$endpoint
COSMOS_DATABASE=$DatabaseName
COSMOS_CONTAINER=$ContainerName
DOCUMENT_COUNT=100
"@ | Set-Content -Path ".env" -Encoding utf8

Write-Host "Azure setup complete. A credential-free .env file was generated and is ignored by Git."
Write-Host "For a user-assigned managed identity, rerun with -PrincipalId <managed-identity-object-id>."
