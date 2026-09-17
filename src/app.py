"""Streamlit UI for comparing partition-key and cross-partition queries."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import pandas as pd
import streamlit as st
from azure.cosmos import PartitionKey
from azure.cosmos.aio import CosmosClient
from azure.identity.aio import DefaultAzureCredential
from dotenv import load_dotenv

from cosmos_query_test import QueryResult, run_query, seed_documents


async def execute(mode: str, seed: bool) -> QueryResult:
    load_dotenv()
    endpoint = os.environ.get("COSMOS_ENDPOINT")
    if not endpoint:
        raise RuntimeError("COSMOS_ENDPOINT is required. Run scripts/setup-azure.ps1 first.")

    credential = DefaultAzureCredential()
    client = CosmosClient(endpoint, credential=credential, connection_mode="Gateway")
    try:
        database = client.get_database_client(os.getenv("COSMOS_DATABASE", "chatbot-test"))
        container = database.get_container_client(os.getenv("COSMOS_CONTAINER", "sessions"))
        if seed:
            await seed_documents(container, int(os.getenv("DOCUMENT_COUNT", "100")))
        return await run_query(container, "session-01" if mode == "PK 지정" else None, client)
    finally:
        await client.close()
        await credential.close()


def show_result(result: QueryResult) -> None:
    st.subheader("실행 결과")
    left, middle, right, last = st.columns(4)
    left.metric("Status code", ", ".join(str(item.status_code) for item in result.requests) or "—")
    middle.metric("Substatus code", ", ".join(str(item.substatus_code) for item in result.requests) or "—")
    right.metric("QueryPlan 요청 수", result.query_plan_requests)
    last.metric("반환 문서", result.returned_documents)

    charge, duration = st.columns(2)
    charge.metric("RequestCharge (합계)", f"{result.request_charge:.2f} RU")
    duration.metric("DurationMs (합계)", f"{result.duration_ms:.2f} ms")

    if result.error:
        st.error(result.error)
    if result.requests:
        st.dataframe(pd.DataFrame([item.__dict__ for item in result.requests]), use_container_width=True)
    if result.query_plan_requests:
        st.info("SDK 4.16.x가 400/1004를 받은 뒤 Gateway QueryPlan fallback을 수행했음을 의미합니다.")


def main() -> None:
    st.set_page_config(page_title="Cosmos query test", page_icon="☁️", layout="wide")
    st.title("Cosmos DB PK 쿼리 비교")
    st.caption("Gateway · Microsoft Entra ID · azure-cosmos 4.16.x (async)")

    with st.sidebar:
        st.header("샘플")
        mode = st.radio("실행할 쿼리", ("PK 지정", "PK 미지정"))
        st.caption("PK 지정: /session_id = session-01\n\nPK 미지정: cross-partition")
        seed = st.checkbox("실행 전 100개 샘플 문서 upsert", value=False)
        run = st.button("쿼리 실행", type="primary", use_container_width=True)

    st.markdown("선택한 샘플을 실행한 직후 SDK 응답 헤더를 표시합니다. 요청별 수치의 합계가 위 카드에 표시됩니다.")
    if run:
        with st.spinner("Cosmos DB query 실행 중..."):
            try:
                st.session_state.result = asyncio.run(execute(mode, seed))
            except Exception as error:  # noqa: BLE001
                st.error(str(error))
    if result := st.session_state.get("result"):
        show_result(result)


if __name__ == "__main__":
    logging.getLogger("azure").setLevel(logging.WARNING)
    main()