-- Remote cold first calls exceeded 3s; all six warm SQL p95 values were < 1s.
-- Allow the product's anonymous signed-in users to complete cold calls.
alter role authenticated set statement_timeout = '15s';
notify pgrst, 'reload config';
-- Rollback, if required, via a new migration:
-- alter role authenticated set statement_timeout = '8s';
-- notify pgrst, 'reload config';
