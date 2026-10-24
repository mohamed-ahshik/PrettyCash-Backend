from postgrest.exceptions import APIError

from app.store.base import JobStatus
from app.store.supabase import SupabaseJobStore


class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, client):
        self._client = client

    def insert(self, data):
        self._client.calls.append(("insert", data))
        return self

    def update(self, data):
        self._client.calls.append(("update", data))
        return self

    def select(self, *cols):
        self._client.calls.append(("select", cols))
        return self

    def eq(self, col, val):
        self._client.calls.append(("eq", col, val))
        return self

    def limit(self, count):
        self._client.calls.append(("limit", count))
        return self

    def execute(self):
        if self._client.data_queue:
            return FakeResponse(self._client.data_queue.pop(0))
        return FakeResponse(self._client.next_data)


class FakeSupabaseClient:
    def __init__(self):
        self.calls = []
        self.next_data = []
        self.data_queue = []

    def table(self, name):
        return FakeQuery(self)


class UniqueViolationQuery(FakeQuery):
    def execute(self):
        if self._client.calls[-1][0] == "insert":
            raise APIError({"message": "duplicate key", "code": "23505"})
        self._client.selects += 1
        if self._client.selects == 1:
            return FakeResponse([])
        return FakeResponse([{"id": "winner"}])


class UniqueViolationClient(FakeSupabaseClient):
    def __init__(self):
        super().__init__()
        self.selects = 0

    def table(self, name):
        return UniqueViolationQuery(self)


def test_create_returns_created_job():
    client = FakeSupabaseClient()
    client.next_data = [{"id": "abc"}]
    store = SupabaseJobStore(client)
    result = store.create()
    assert result.job_id == "abc"
    assert result.created is True
    assert client.calls[0] == ("insert", {"status": JobStatus.PENDING.value})


def test_create_with_existing_request_id_returns_existing_job():
    client = FakeSupabaseClient()
    client.next_data = [{"id": "existing"}]
    store = SupabaseJobStore(client)
    result = store.create("request-1")
    assert result.job_id == "existing"
    assert result.created is False
    assert not any(call[0] == "insert" for call in client.calls)


def test_create_with_new_request_id_inserts_request_id():
    client = FakeSupabaseClient()
    client.data_queue = [[], [{"id": "abc"}]]
    store = SupabaseJobStore(client)
    result = store.create("request-1")
    assert result.job_id == "abc"
    assert result.created is True
    assert (
        "insert",
        {"status": JobStatus.PENDING.value, "request_id": "request-1"},
    ) in client.calls


def test_create_recovers_from_unique_violation():
    client = UniqueViolationClient()
    store = SupabaseJobStore(client)
    result = store.create("request-1")
    assert result.job_id == "winner"
    assert result.created is False


def test_mark_processing():
    client = FakeSupabaseClient()
    store = SupabaseJobStore(client)
    store.mark_processing("abc")
    assert client.calls[0] == ("update", {"status": JobStatus.PROCESSING.value})
    assert client.calls[1] == ("eq", "id", "abc")


def test_complete_updates_result():
    client = FakeSupabaseClient()
    store = SupabaseJobStore(client)
    store.complete("abc", {"merchant": "X", "amount": 1.0})
    assert client.calls[0] == (
        "update",
        {"status": JobStatus.COMPLETED.value, "result": {"merchant": "X", "amount": 1.0}},
    )


def test_fail_updates_error():
    client = FakeSupabaseClient()
    store = SupabaseJobStore(client)
    store.fail("abc", "INTERNAL", "boom")
    assert client.calls[0] == (
        "update",
        {"status": JobStatus.FAILED.value, "error_code": "INTERNAL", "error_message": "boom"},
    )


def test_record_classification_updates_score_and_model():
    client = FakeSupabaseClient()
    store = SupabaseJobStore(client)
    store.record_classification("abc", 0.42, "typesafe/jev-1.14")
    assert client.calls[0] == (
        "update",
        {"classifier_score": 0.42, "classifier_model": "typesafe/jev-1.14"},
    )
    assert client.calls[1] == ("eq", "id", "abc")


def test_reject_updates_status_and_error():
    client = FakeSupabaseClient()
    store = SupabaseJobStore(client)
    store.reject(
        "abc", "NOT_A_RECEIPT", "This image doesn't look like a receipt or invoice."
    )
    assert client.calls[0] == (
        "update",
        {
            "status": JobStatus.REJECTED.value,
            "error_code": "NOT_A_RECEIPT",
            "error_message": "This image doesn't look like a receipt or invoice.",
        },
    )
    assert client.calls[1] == ("eq", "id", "abc")


def test_get_returns_row_or_none():
    client = FakeSupabaseClient()
    store = SupabaseJobStore(client)
    client.next_data = [{"id": "abc", "status": "completed"}]
    assert store.get("abc") == {"id": "abc", "status": "completed"}
    client.next_data = []
    assert store.get("abc") is None
