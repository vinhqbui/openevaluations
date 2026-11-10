Both record store backends (`MemoryStore` and `JsonFileStore`) implement paging themselves, so every change to paging has to be made twice. Refactor it so paging lives in one place, `RecordStore` in `tallyho/store/base.py`:

- `RecordStore.list_page` becomes a concrete method, no longer abstract, built on two new abstract methods that every backend implements: `_ids(self, collection)`, which returns every id in the collection as a sorted list, and `_records(self, collection, ids)`, which returns the records with those ids, in that order.
- `MemoryStore` and `JsonFileStore` implement `_ids` and `_records` and no longer define `list_page` themselves.
- Any backend that implements `put`, `get`, `delete`, `_ids` and `_records` gets a working `list_page`.

This is a refactor: nothing a caller of either backend can observe may change. Pages, cursors, page-size limits, and what callers may do with the records they get back must all behave exactly as before.
