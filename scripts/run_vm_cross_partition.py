"""Run inside the VNet VM to generate repeatable Cosmos 400/1004 traffic."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import azure.cosmos
from applicationinsights import TelemetryClient
from azure.cosmos.aio import CosmosClient
from azure.identity.aio import ManagedIdentityCredential

ENDPOINT = "https://db-cosmos-basic-test.documents.azure.com:443/"
DATABASE = "chatbot-test"
CONTAINER = "sessions"
QUERY = "SELECT * FROM c ORDER BY c.created_at"
RUNS = 20


async def execute_once(
    container: Any, client: CosmosClient, telemetry: TelemetryClient
) -> dict[str, Any]:
    connection = client.client_connection
    original = connection._GetQueryPlanThroughGateway  # pylint: disable=protected-access
    query_plan_requests = 0

    async def wrapped(*args: Any, **kwargs: Any) -> Any:
        nonlocal query_plan_requests
        query_plan_requests += 1
        return await original(*args, **kwargs)

    connection._GetQueryPlanThroughGateway = wrapped  # type: ignore[method-assign]  # pylint: disable=protected-access
    started = time.perf_counter()
    try:
        items = container.query_items(query=QUERY, max_item_count=100)
        documents = [item async for item in items]
        result = {
            "timestampUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "documents": len(documents),
            "queryPlanRequests": query_plan_requests,
            "clientElapsedMs": round((time.perf_counter() - started) * 1000, 2),
        }
        if query_plan_requests:
            telemetry.track_event(
                "CosmosQueryPlanFallback",
                {
                    "statusCode": "400",
                    "substatusCode": "1004",
                    "expectedQueryPlanFallback": "true",
                    "connectionMode": "Gateway",
                    "partitionKeySupplied": "false",
                },
                {"queryPlanRequests": query_plan_requests},
            )
        return result
    finally:
        connection._GetQueryPlanThroughGateway = original  # type: ignore[method-assign]  # pylint: disable=protected-access


async def main() -> None:
    credential = ManagedIdentityCredential()
    client = CosmosClient(ENDPOINT, credential=credential, connection_mode="Gateway")
    telemetry = TelemetryClient(__import__("os").environ["APPINSIGHTS_INSTRUMENTATIONKEY"])
    try:
        container = client.get_database_client(DATABASE).get_container_client(CONTAINER)
        results = [await execute_once(container, client, telemetry) for _ in range(RUNS)]
        telemetry.flush()
        await asyncio.sleep(5)
        print(json.dumps({"azureCosmosVersion": azure.cosmos.VERSION, "runs": results}, indent=2))
    finally:
        await client.close()
        await credential.close()


if __name__ == "__main__":
    asyncio.run(main())
