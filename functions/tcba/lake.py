"""Abstraksi penyimpanan: satu API untuk folder lokal dan ADLS Gen2.

LAKE_MODE=local  -> file disimpan di LAKE_ROOT (default ./_lake/<container>/<path>)
LAKE_MODE=adls   -> file disimpan di ADLS Gen2 akun LAKE_ACCOUNT, autentikasi Entra ID
                    (Managed Identity di Azure Function, `az login` di laptop/Codespaces).
"""
from __future__ import annotations

import io
import json
import os
from typing import Iterable

import pandas as pd


def _parquet_engine_ok() -> bool:
    try:
        import pyarrow  # noqa: F401
        return True
    except ImportError:
        return False


# Hanya untuk sandbox tanpa pyarrow (bukan untuk dipakai di Azure). Lihat README.
_DEV_NO_PYARROW = os.getenv("TCBA_DEV_NO_PYARROW") == "1" and not _parquet_engine_ok()


class Lake:
    def __init__(self, mode: str | None = None, root: str | None = None, account: str | None = None):
        self.mode = (mode or os.getenv("LAKE_MODE", "local")).lower()
        if self.mode == "local":
            self.root = os.path.abspath(root or os.getenv("LAKE_ROOT", "./_lake"))
        elif self.mode == "adls":
            from azure.identity import DefaultAzureCredential
            from azure.storage.filedatalake import DataLakeServiceClient
            self.account = account or os.environ["LAKE_ACCOUNT"]
            self._svc = DataLakeServiceClient(
                f"https://{self.account}.dfs.core.windows.net",
                credential=DefaultAzureCredential(exclude_interactive_browser_credential=True))
        else:
            raise ValueError("LAKE_MODE harus 'local' atau 'adls'")

    # ------------------------------------------------------------------ util
    def _local(self, container: str, path: str) -> str:
        return os.path.join(self.root, container, *path.strip("/").split("/"))

    def _fs(self, container: str):
        return self._svc.get_file_system_client(container)

    # ------------------------------------------------------------------ bytes
    def write_bytes(self, container: str, path: str, data: bytes, overwrite: bool = True) -> str:
        if self.mode == "local":
            p = self._local(container, path)
            if not overwrite and os.path.exists(p):
                raise FileExistsError(f"{container}/{path} sudah ada (Bronze bersifat immutable)")
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as f:
                f.write(data)
        else:
            if not overwrite and self.exists(container, path):
                raise FileExistsError(f"{container}/{path} sudah ada (Bronze bersifat immutable)")
            self._fs(container).get_file_client(path).upload_data(data, overwrite=True)
        return f"{container}/{path}"

    def read_bytes(self, container: str, path: str) -> bytes:
        if self.mode == "local":
            with open(self._local(container, path), "rb") as f:
                return f.read()
        return self._fs(container).get_file_client(path).download_file().readall()

    def exists(self, container: str, path: str) -> bool:
        if self.mode == "local":
            return os.path.exists(self._local(container, path))
        try:
            self._fs(container).get_file_client(path).get_file_properties()
            return True
        except Exception:
            return False

    def list_paths(self, container: str, prefix: str = "") -> list[str]:
        """Daftar file (bukan direktori) di bawah prefix, terurut, relatif terhadap container."""
        prefix = prefix.strip("/")
        if self.mode == "local":
            base = self._local(container, prefix) if prefix else os.path.join(self.root, container)
            out = []
            for dirpath, _, files in os.walk(base):
                for fn in files:
                    full = os.path.join(dirpath, fn)
                    rel = os.path.relpath(full, os.path.join(self.root, container)).replace(os.sep, "/")
                    out.append(rel)
            return sorted(out)
        try:
            paths = self._fs(container).get_paths(path=prefix or None, recursive=True)
            return sorted(p.name for p in paths if not p.is_directory)
        except Exception as e:  # folder belum ada
            if "PathNotFound" in str(e) or "FilesystemNotFound" in str(e) or "ResourceNotFound" in type(e).__name__:
                return []
            raise

    # ------------------------------------------------------------------ json
    def write_json(self, container: str, path: str, obj, overwrite: bool = True) -> str:
        return self.write_bytes(container, path, json.dumps(obj, ensure_ascii=False, default=str).encode(), overwrite)

    def read_json(self, container: str, path: str):
        return json.loads(self.read_bytes(container, path))

    # ------------------------------------------------------------------ parquet
    def write_parquet(self, container: str, path: str, df: pd.DataFrame) -> str:
        buf = io.BytesIO()
        if _DEV_NO_PYARROW:
            df.to_pickle(buf)
        else:
            df.to_parquet(buf, index=False, compression="snappy")
        return self.write_bytes(container, path, buf.getvalue(), overwrite=True)

    def read_parquet(self, container: str, path: str) -> pd.DataFrame:
        data = io.BytesIO(self.read_bytes(container, path))
        if _DEV_NO_PYARROW:
            return pd.read_pickle(data)
        return pd.read_parquet(data)

    def read_parquet_or_empty(self, container: str, path: str, columns: Iterable[str] = ()) -> pd.DataFrame:
        if self.exists(container, path):
            return self.read_parquet(container, path)
        return pd.DataFrame(columns=list(columns))
