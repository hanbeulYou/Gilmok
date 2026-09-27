"""Bound COPY streams without committing the caller's transaction."""

from contextlib import ExitStack, contextmanager


class CopyBatches:
    def __init__(self, cursor, statement, stack, batch_size):
        if batch_size < 1:
            raise ValueError("COPY batch size must be positive")
        self.cursor, self.statement, self.stack = cursor, statement, stack
        self.batch_size, self.rows, self.stream = batch_size, 0, None

    def write_row(self, row):
        if self.rows % self.batch_size == 0:
            self.stack.close()
            self.stream = self.stack.enter_context(self.cursor.copy(self.statement))
        self.stream.write_row(row)
        self.rows += 1


@contextmanager
def chunked_copy(cursor, statement, *, batch_size=50_000):
    with ExitStack() as stack:
        yield CopyBatches(cursor, statement, stack, batch_size)
