"""Configuration and raw Parquet storage shared by batch sources."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import boto3
import duckdb
import pandas as pd
from botocore.config import Config
from botocore.exceptions import ClientError
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
R2_VARIABLES = ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET")


@dataclass(frozen=True)
class Settings:
    local_root: Path
    r2_account_id: str = ""
    r2_access_key_id: str = field(default="", repr=False)
    r2_secret_access_key: str = field(default="", repr=False)
    r2_bucket: str = ""

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        # Passing an explicit mapping also isolates tests from the user's .env.
        env = {**dotenv_values(ROOT / ".env"), **os.environ} if environ is None else environ
        values = [str(env.get(name) or "").strip() for name in R2_VARIABLES]
        if any(values) and not all(values):
            missing = ", ".join(name for name, value in zip(R2_VARIABLES, values) if not value)
            raise ValueError(f"Incomplete R2 configuration; missing: {missing}")
        local_root = Path(env.get("INGEST_LOCAL_ROOT") or ".local/ingest").expanduser()
        if not local_root.is_absolute():
            local_root = ROOT / local_root
        return cls(local_root.resolve(), *values)

    @property
    def uses_r2(self) -> bool:
        return bool(self.r2_bucket)


def raw_key(source: str, month: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9_]*", source):
        raise ValueError("Source must use lowercase letters, digits, and underscores")
    if not re.fullmatch(r"\d{4}-\d{2}", month):
        raise ValueError("Month must use YYYY-MM")
    datetime.strptime(month, "%Y-%m")
    return f"raw/{source}/{month}.parquet"


class StorageError(RuntimeError):
    """Storage failure with credentials excluded from the public message."""


class RawStore:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _local_path(self, key: str) -> Path:
        root = self.settings.local_root.resolve()
        path = (root / key).resolve()
        if not path.is_relative_to(root):
            raise ValueError("Raw path must stay within INGEST_LOCAL_ROOT")
        return path

    def location(self, source: str, month: str) -> str:
        key = raw_key(source, month)
        if self.settings.uses_r2:
            return f"s3://{self.settings.r2_bucket}/{key}"
        return str(self._local_path(key))

    def publish_file(self, source: str, month: str, path: Path) -> dict:
        """Publish a validated Parquet without materializing it as a DataFrame.

        R2 snapshots are immutable here: reuse identical bytes, refuse a different
        existing object. Multipart upload exposes the new object only on completion.
        """
        key = raw_key(source, month)
        with duckdb.connect() as connection:
            connection.read_parquet(str(path)).limit(0).fetchall()
        with path.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        size = path.stat().st_size
        status = "published"
        if not self.settings.uses_r2:
            target = self._local_path(key)
            target.parent.mkdir(parents=True, exist_ok=True)
            if path.resolve() != target:
                with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as temporary:
                    temporary_path = Path(temporary.name)
                try:
                    shutil.copyfile(path, temporary_path)
                    os.replace(temporary_path, target)
                finally:
                    temporary_path.unlink(missing_ok=True)
            else:
                status = "reused"
        else:
            settings = self.settings
            try:
                client = boto3.client(
                    "s3", endpoint_url=f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
                    aws_access_key_id=settings.r2_access_key_id,
                    aws_secret_access_key=settings.r2_secret_access_key, region_name="auto",
                    config=Config(retries={"max_attempts": 3, "mode": "standard"}),
                )
                try:
                    old = client.head_object(Bucket=settings.r2_bucket, Key=key)
                except ClientError as error:
                    if error.response["Error"]["Code"] not in {"404", "NoSuchKey", "NotFound"}:
                        raise
                    old = None
                if old is not None:
                    if (old.get("Metadata", {}).get("sha256") != digest
                            or old["ContentLength"] != size):
                        raise StorageError("Existing R2 snapshot differs; refusing to overwrite")
                    status = "reused"
                else:
                    client.upload_file(str(path), settings.r2_bucket, key,
                                       ExtraArgs={"Metadata": {"sha256": digest}})
                result = client.head_object(Bucket=settings.r2_bucket, Key=key)
                if (result["ContentLength"] != size
                        or result.get("Metadata", {}).get("sha256") != digest):
                    raise StorageError("R2 uploaded object metadata does not match")
            except StorageError:
                raise
            except Exception:
                raise StorageError("R2 publication failed; local fallback was not used") from None
        return {"key": key, "bytes": size, "sha256": digest, "status": status}

    def write_parquet(self, source: str, month: str, frame: pd.DataFrame) -> str:
        """Publish only a complete file; a failed write keeps the previous snapshot."""
        key = raw_key(source, month)
        if frame.columns.empty or not frame.columns.is_unique:
            raise ValueError("Raw data needs nonempty, unique columns")
        target = None if self.settings.uses_r2 else self._local_path(key)
        if target is not None:
            target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            suffix=".parquet", dir=target.parent if target else None, delete=False
        ) as temp:
            temp_path = Path(temp.name)
        try:
            with duckdb.connect() as connection:
                connection.register("incoming", frame)
                connection.table("incoming").write_parquet(str(temp_path), compression="zstd")
            if target is not None:
                os.replace(temp_path, target)
            else:
                settings = self.settings
                try:
                    client = boto3.client(
                        "s3",
                        endpoint_url=f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
                        aws_access_key_id=settings.r2_access_key_id,
                        aws_secret_access_key=settings.r2_secret_access_key,
                        region_name="auto",
                        config=Config(retries={"max_attempts": 3, "mode": "standard"}),
                    )
                    client.upload_file(str(temp_path), settings.r2_bucket, key)
                except Exception:
                    raise StorageError("R2 upload failed; local fallback was not used") from None
        finally:
            temp_path.unlink(missing_ok=True)
        return self.location(source, month)

    @contextmanager
    def connection(self, *, config=None):
        """DuckDB is in-memory; remote credentials are never persisted to disk."""
        connection = duckdb.connect(config=config or {})
        try:
            if self.settings.uses_r2:
                try:
                    connection.execute("INSTALL httpfs")
                    connection.execute("LOAD httpfs")
                    settings = self.settings
                    # SQL literals are escaped; connection setup errors must not echo secrets.
                    def literal(value: str) -> str:
                        return "'" + value.replace("'", "''") + "'"

                    connection.execute(
                        "CREATE SECRET (TYPE S3, KEY_ID "
                        + literal(settings.r2_access_key_id)
                        + ", SECRET " + literal(settings.r2_secret_access_key)
                        + ", ENDPOINT "
                        + literal(f"{settings.r2_account_id}.r2.cloudflarestorage.com")
                        + ", REGION 'auto', URL_STYLE 'path')"
                    )
                except Exception:
                    raise StorageError("DuckDB R2 setup failed") from None
            yield connection
        finally:
            connection.close()
