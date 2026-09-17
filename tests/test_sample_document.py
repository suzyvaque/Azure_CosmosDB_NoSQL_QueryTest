from src.cosmos_query_test import sample_document


def test_sample_document_has_partition_key() -> None:
    document = sample_document(11)

    assert document["session_id"] == "session-01"
    assert document["message_index"] == 11
    assert document["id"]
