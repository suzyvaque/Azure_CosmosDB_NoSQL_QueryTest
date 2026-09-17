from src.cosmos_query_test import response_metric, sample_document


def test_sample_document_has_partition_key() -> None:
    document = sample_document(11)

    assert document["session_id"] == "session-01"
    assert document["message_index"] == 11
    assert document["id"]


def test_response_metric_reads_cosmos_headers() -> None:
    metric = response_metric(
        {
            "x-ms-status-code": "200",
            "x-ms-substatus": "0",
            "x-ms-request-charge": "3.25",
            "x-ms-request-duration-ms": "14.5",
        }
    )

    assert metric.status_code == 200
    assert metric.substatus_code == 0
    assert metric.request_charge == 3.25
    assert metric.duration_ms == 14.5
