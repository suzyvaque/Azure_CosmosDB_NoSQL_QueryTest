"""Reproduce a Cosmos DB cross-partition query with Entra ID authentication."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import uuid
from datetime import UTC, datetime
from typing import Any

from azure.cosmos import PartitionKey
from azure.cosmos.aio import CosmosClient
from azure.identity.aio import DefaultAzureCredential
from dotenv import load_dotenv

LOGGER = logging.getLogger("cosmos-query-test")


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


async def run_query(container: Any, session_id: str | None) -> int:
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

    items = container.query_items(
        query=query,
        parameters=parameters,
        partition_key=partition_key,
        max_item_count=10,
        populate_query_metrics=True,
    )
    result_count = 0
    async for _ in items:
        result_count += 1

    LOGGER.info("Query completed; returned %d documents", result_count)
    return result_count


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
        count = await run_query(container, args.session_id)
        print(json.dumps({"returnedDocuments": count, "mode": "Gateway"}))
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
