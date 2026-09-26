from contextlib import contextmanager

import pytest

from ingest.copy_batches import chunked_copy


def test_copy_rotates_at_50000_rows_and_propagates_failure():
    batches, exits = [], []

    class Cursor:
        @contextmanager
        def copy(self, statement):
            assert statement == "copy fixture from stdin"
            rows = []
            batches.append(rows)
            class Stream:
                def write_row(self, row):
                    rows.append(row)
            try:
                yield Stream()
            except ValueError:
                exits.append("aborted")
                raise
            else:
                exits.append("completed")

    with pytest.raises(ValueError, match="bad row"):
        with chunked_copy(Cursor(), "copy fixture from stdin") as stream:
            for n in range(50_001):
                stream.write_row((n,))
            raise ValueError("bad row")
    assert [len(batch) for batch in batches] == [50_000, 1]
    assert exits == ["completed", "aborted"]
