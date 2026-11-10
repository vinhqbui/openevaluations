"""Hidden test for store-paging-refactor: one paging implementation in RecordStore, same behaviour."""

import copy

import pytest

from tallyho.errors import NotFound
from tallyho.store import JsonFileStore, MemoryStore, Page, RecordStore
from tallyho.store.base import RecordStore as BaseStore


class DictStore(RecordStore):
    """A backend with only the primitives: put, get, delete, _ids and _records."""

    def __init__(self, max_page_size=100):
        self.max_page_size = max_page_size
        self.data = {}

    def put(self, collection, record):
        self.data.setdefault(collection, {})[record["id"]] = dict(record)

    def get(self, collection, record_id):
        try:
            return dict(self.data[collection][record_id])
        except KeyError:
            raise NotFound(f"{collection}/{record_id}") from None

    def delete(self, collection, record_id):
        self.data.get(collection, {}).pop(record_id, None)

    def _ids(self, collection):
        return sorted(self.data.get(collection, {}))

    def _records(self, collection, ids):
        return [dict(self.data[collection][i]) for i in ids]


def test_paging_lives_in_record_store_only():
    assert RecordStore is BaseStore
    assert "list_page" in vars(RecordStore)
    assert "list_page" not in RecordStore.__abstractmethods__
    assert {"_ids", "_records", "put", "get", "delete"} <= RecordStore.__abstractmethods__
    for backend in (MemoryStore, JsonFileStore):
        assert "list_page" not in vars(backend), backend.__name__
        assert "_ids" in vars(backend) and "_records" in vars(backend), backend.__name__


def test_a_backend_without_ids_and_records_cannot_be_built():
    class Partial(RecordStore):
        def put(self, collection, record): ...
        def get(self, collection, record_id): ...
        def delete(self, collection, record_id): ...

    with pytest.raises(TypeError):
        Partial()


@pytest.fixture(params=["memory", "json", "dict"])
def store(request, tmp_path):
    s = {"memory": lambda: MemoryStore(max_page_size=4), "json": lambda: JsonFileStore(tmp_path, max_page_size=4),
         "dict": lambda: DictStore(max_page_size=4)}[request.param]()
    for i in (7, 2, 9, 0, 5, 1, 8, 3, 6, 4):
        s.put("things", {"id": f"k{i:02d}", "n": i})
    return s


def _ids(page):
    return [r["id"] for r in page.records]


def test_pages_follow_cursors_and_stop_at_max_page_size(store):
    p = store.list_page("things")
    assert isinstance(p, Page)
    assert _ids(p) == ["k00", "k01", "k02", "k03"] and p.next_cursor == "k03"
    p = store.list_page("things", p.next_cursor, 50)
    assert _ids(p) == ["k04", "k05", "k06", "k07"] and p.next_cursor == "k07"
    p = store.list_page("things", p.next_cursor, 50)
    assert _ids(p) == ["k08", "k09"] and p.next_cursor is None
    assert p.records[0] == {"id": "k08", "n": 8}


def test_an_exactly_full_last_page_has_no_cursor(store):
    p = store.list_page("things", "k05", 4)
    assert _ids(p) == ["k06", "k07", "k08", "k09"] and p.next_cursor is None
    p = store.list_page("things", "k07", 2)
    assert _ids(p) == ["k08", "k09"] and p.next_cursor is None


def test_small_and_odd_limits(store):
    p = store.list_page("things", None, 3)
    assert _ids(p) == ["k00", "k01", "k02"] and p.next_cursor == "k02"
    for limit in (0, -5, 1):
        p = store.list_page("things", None, limit)
        assert _ids(p) == ["k00"] and p.next_cursor == "k00"


def test_cursors_that_are_not_ids(store):
    p = store.list_page("things", "k035", 2)
    assert _ids(p) == ["k04", "k05"] and p.next_cursor == "k05"
    p = store.list_page("things", "a", 2)
    assert _ids(p) == ["k00", "k01"]
    p = store.list_page("things", "z", 2)
    assert p.records == [] and p.next_cursor is None


def test_empty_and_missing_collections(store):
    p = store.list_page("nothing")
    assert p.records == [] and p.next_cursor is None
    for i in range(10):
        store.delete("things", f"k{i:02d}")
    p = store.list_page("things")
    assert p.records == [] and p.next_cursor is None


def test_deletes_and_replacements_show_in_the_next_page(store):
    store.delete("things", "k01")
    store.put("things", {"id": "k02", "n": 22})
    p = store.list_page("things", None, 2)
    assert p.records == [{"id": "k00", "n": 0}, {"id": "k02", "n": 22}]


@pytest.mark.parametrize("backend", ["memory", "json"])
def test_returned_records_are_the_callers_to_change(backend, tmp_path):
    s = MemoryStore() if backend == "memory" else JsonFileStore(tmp_path)
    s.put("things", {"id": "a", "tags": ["x"]})
    page = s.list_page("things")
    page.records[0]["tags"].append("y")
    page.records[0]["n"] = 1
    assert s.get("things", "a") == {"id": "a", "tags": ["x"]}
    assert s.list_page("things").records == [{"id": "a", "tags": ["x"]}]


def test_memory_store_still_copies_on_put():
    s = MemoryStore()
    rec = {"id": "a", "tags": ["x"]}
    s.put("things", rec)
    rec["tags"].append("y")
    assert s.list_page("things").records == [{"id": "a", "tags": ["x"]}]
    assert copy.deepcopy(s.get("things", "a")) == {"id": "a", "tags": ["x"]}
