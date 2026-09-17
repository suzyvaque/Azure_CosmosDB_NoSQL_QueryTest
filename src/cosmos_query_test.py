"""Reproduce a Cosmos DB cross-partition query with Entra ID authentication."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable, Mapping

from azure.cosmos import PartitionKey
from azure.cosmos.aio import CosmosClient
from azure.identity.aio import DefaultAzureCredential
from dotenv import load_dotenv

LOGGER = logging.getLogger("cosmos-query-test")


@dataclass
class RequestMetric:
    request_type: str
    status_code: int
    substatus_code: int
    request_charge: float = 0.0
    duration_ms: float = 0.0


@dataclass
class QueryResult:
    mode: str
    returned_documents: int = 0
    query_plan_requests: int = 0
    requests: list[RequestMetric] = field(default_factory=list)
    error: str | None = None

    @property
    def request_charge(self) -> float:
        return sum(request.request_charge for request in self.requests)

    @property
    def duration_ms(self) -> float:
        return sum(request.duration_ms for request in self.requests)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "returnedDocuments": self.returned_documents,
            "queryPlanRequests": self.query_plan_requests,
            "requestCharge": self.request_charge,
            "durationMs": self.duration_ms,
            "error": self.error,
            "requests": [asdict(request) for request in self.requests],
        }


def header_value(headers: Mapping[str, Any], name: str, default: str = "0") -> str:
    return str(next((value for key, value in headers.items() if key.lower() == name), default))


def response_metric(headers: Mapping[str, Any]) -> RequestMetric:
    """Convert Cosmos response headers into a UI-safe page metric."""
    return RequestMetric(
        request_type="Query page",
        status_code=int(header_value(headers, "x-ms-status-code", "200")),
        substatus_code=int(header_value(headers, "x-ms-substatus", "0")),
        request_charge=float(header_value(headers, "x-ms-request-charge")),
        duration_ms=float(header_value(headers, "x-ms-request-duration-ms")),
    )


def instrument_query_plan_requests(client: CosmosClient, result: QueryResult) -> Callable[[], None]:
    """Count SDK 4.16 Gateway query-plan fallbacks without logging credentials.

    The SDK calls this private method only after it catches the service's
    400/1004 CROSS_PARTITION_QUERY_NOT_SERVABLE response. The instrumentation
    is intentionally pinned to the project's azure-cosmos 4.16.x dependency.
    """
    connection = client.client_connection
    original = connection._GetQueryPlanThroughGateway  # pylint: disable=protected-access

    async def wrapped(*args: Any, **kwargs: Any) -> Any:
        result.query_plan_requests += 1
        result.requests.append(
            RequestMetric("Initial query (SDK fallback)", 400, 1004)
        )
        return await original(*args, **kwargs)

    connection._GetQueryPlanThroughGateway = wrapped  # type: ignore[method-assign]  # pylint: disable=protected-access

    def restore() -> None:
        connection._GetQueryPlanThroughGateway = original  # type: ignore[method-assign]  # pylint: disable=protected-access

    return restore


def configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger("azure.cosmos").setLevel(level)
    logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(level)


def sample_document(index: int) -> dict[str, Any]:
    session_id = f"session-{index % 10:02d}"
    return {
        "id": str(uuid.uuid4()),
        "session_id": session_id,
        "message_index": index,
        "role": "user" if index % 2 == 0 else "assistant",
        "content": f"Synthetic chatbot message {index}",
        "created_at": datetime.now(UTC).isoformat(),
    }


async def seed_documents(container: Any, count: int) -> None:
    LOGGER.info("Upserting %d synthetic documents", count)
    await asyncio.gather(
        *(container.upsert_item(sample_document(index)) for index in range(count))
    )
    LOGGER.info("Seed completed")


async def run_query(container: Any, session_id: str | None, client: CosmosClient) -> QueryResult:
    parameters: list[dict[str, str]] = []
    query = "SELECT * FROM c ORDER BY c.created_at"
    partition_key: str | None = None

    if session_id:
        query = "SELECT * FROM c WHERE c.session_id = @session_id ORDER BY c.created_at"
        parameters = [{"name": "@session_id", "value": session_id}]
        partition_key = session_id
        LOGGER.info("Running single-partition query for %s", session_id)
    else:
        LOGGER.info("Running cross-partition query without a partition key")

    result = QueryResult(mode="PK specified" if session_id else "No PK (cross-partition)")
    restore_query_plan_instrumentation = instrument_query_plan_requests(client, result)

    def on_response(headers: Mapping[str, Any], _: Any) -> None:
        result.requests.append(response_metric(headers))

    try:
        items = container.query_items(
            query=query,
            parameters=parameters,
            partition_key=partition_key,
            max_item_count=10,
            populate_query_metrics=True,
            response_hook=on_response,
        )
        async for _ in items:
            result.returned_documents += 1
    except Exception as error:  # UI presents Azure SDK failures without credentials.
        result.error = str(error)
        LOGGER.exception("Query failed")
    finally:
        restore_query_plan_instrumentation()

    LOGGER.info("Query completed; returned %d documents", result.returned_documents)
    return result


async def main(args: argparse.Namespace) -> None:
    load_dotenv()
    endpoint = os.environ.get("COSMOS_ENDPOINT")
    if not endpoint:
        raise RuntimeError("COSMOS_ENDPOINT is required; copy .env.example to .env")

    database_name = os.getenv("COSMOS_DATABASE", "chatbot-test")
    container_name = os.getenv("COSMOS_CONTAINER", "sessions")
    document_count = int(os.getenv("DOCUMENT_COUNT", "100"))

    credential = DefaultAzureCredential()
    client = CosmosClient(
        endpoint,
        credential=credential,
        connection_mode="Gateway",
        enable_diagnostics_logging=args.verbose,
        logger=logging.getLogger("azure.cosmos"),
    )
    try:
        database = await client.create_database_if_not_exists(database_name)
        container = await database.create_container_if_not_exists(
            id=container_name,
            partition_key=PartitionKey(path="/session_id"),
            offer_throughput=400,
        )
        if args.seed:
            await seed_documents(container, document_count)
        result = await run_query(container, args.session_id, client)
        print(json.dumps(result.to_dict()))
    finally:
        await client.close()
        await credential.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", action="store_true", help="upsert synthetic documents")
    parser.add_argument(
        "--session-id",
        help="set /session_id for a single-partition control query; omit for cross-partition",
    )
    parser.add_argument("--verbose", action="store_true", help="enable SDK diagnostics")
    return parser.parse_args()


if __name__ == "__main__":
    configure_logging("--verbose" in os.sys.argv)
    asyncio.run(main(parse_args()))
