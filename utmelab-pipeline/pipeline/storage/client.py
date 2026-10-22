"""Unified Async Turso (LibSQL HTTP) & SQLite Client."""

import asyncio
import sqlite3
from typing import Any, Dict, List, Optional, Union
import httpx
from pydantic import BaseModel


class QueryResult(BaseModel):
    columns: List[str] = []
    rows: List[Dict[str, Any]] = []
    affected_row_count: int = 0
    last_insert_rowid: Optional[int] = None


class TursoClient:
    """Async client for Turso / LibSQL over HTTP, with fallback to local SQLite."""

    def __init__(self, db_url: str, db_token: Optional[str] = None):
        self.raw_url = db_url.strip()
        self.token = db_token or ""
        self._sqlite_conn: Optional[sqlite3.Connection] = None
        self._is_sqlite = (
            self.raw_url.startswith("sqlite:")
            or self.raw_url.startswith("file:")
            or self.raw_url == ":memory:"
            or not self.raw_url.startswith(("http://", "https://", "libsql://", "turso://"))
        )

        if self._is_sqlite:
            # Clean path for sqlite3
            path = self.raw_url
            for prefix in ("sqlite:///", "sqlite://", "file://", "file:"):
                if path.startswith(prefix):
                    path = path[len(prefix) :]
            self.sqlite_path = path or ":memory:"
            self.http_url = None
        else:
            # Convert libsql:// or turso:// to https://
            url = self.raw_url
            if url.startswith("libsql://"):
                url = "https://" + url[len("libsql://") :]
            elif url.startswith("turso://"):
                url = "https://" + url[len("turso://") :]
            self.http_url = url.rstrip("/")
            self.sqlite_path = None

    def _get_sqlite_conn(self) -> sqlite3.Connection:
        if self._sqlite_conn is None:
            conn = sqlite3.connect(self.sqlite_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            self._sqlite_conn = conn
        return self._sqlite_conn

    async def execute(self, sql: str, args: Optional[Union[List[Any], Dict[str, Any]]] = None) -> QueryResult:
        """Executes a single SQL statement."""
        if self._is_sqlite:
            return await asyncio.to_thread(self._execute_sqlite, sql, args)
        return await self._execute_http(sql, args)

    async def batch(self, statements: List[Union[str, tuple]]) -> List[QueryResult]:
        """Executes a batch of SQL statements in sequence."""
        results = []
        for stmt in statements:
            if isinstance(stmt, tuple):
                sql, args = stmt[0], stmt[1] if len(stmt) > 1 else None
            else:
                sql, args = stmt, None
            res = await self.execute(sql, args)
            results.append(res)
        return results

    def _execute_sqlite(self, sql: str, args: Optional[Union[List[Any], Dict[str, Any]]] = None) -> QueryResult:
        conn = self._get_sqlite_conn()
        cursor = conn.cursor()
        param_args = args or []
        cursor.execute(sql, param_args)
        
        # Check if query returned rows
        columns = [d[0] for d in cursor.description] if cursor.description else []
        rows = [dict(row) for row in cursor.fetchall()] if columns else []
        affected = cursor.rowcount if cursor.rowcount != -1 else 0
        last_id = cursor.lastrowid
        conn.commit()
        return QueryResult(
            columns=columns,
            rows=rows,
            affected_row_count=affected,
            last_insert_rowid=last_id,
        )

    async def _execute_http(self, sql: str, args: Optional[Union[List[Any], Dict[str, Any]]] = None) -> QueryResult:
        """Execute against Turso HTTP API (/v2/pipeline)."""
        formatted_args = []
        if args:
            if isinstance(args, (list, tuple)):
                for val in args:
                    formatted_args.append(self._encode_arg(val))
            elif isinstance(args, dict):
                # LibSQL supports named args as well, but list is standard
                for k, val in args.items():
                    formatted_args.append(self._encode_arg(val))

        stmt_payload: Dict[str, Any] = {"sql": sql}
        if formatted_args:
            stmt_payload["args"] = formatted_args

        pipeline_req = {
            "requests": [
                {"type": "execute", "stmt": stmt_payload},
                {"type": "close"},
            ]
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.http_url}/v2/pipeline",
                json=pipeline_req,
                headers=headers,
            )
            if resp.status_code != 200:
                raise RuntimeError(
                    f"Turso HTTP error ({resp.status_code}): {resp.text}"
                )

            data = resp.json()
            first_result = data.get("results", [{}])[0]
            if first_result.get("type") == "error":
                err = first_result.get("error", {}).get("message", "Unknown error")
                raise RuntimeError(f"Turso SQL execution error: {err}")

            response_data = first_result.get("response", {}).get("result", {})
            cols = [c["name"] for c in response_data.get("cols", [])]
            raw_rows = response_data.get("rows", [])
            parsed_rows = []
            for row in raw_rows:
                row_dict = {}
                for idx, col_name in enumerate(cols):
                    row_dict[col_name] = self._decode_val(row[idx])
                parsed_rows.append(row_dict)

            return QueryResult(
                columns=cols,
                rows=parsed_rows,
                affected_row_count=response_data.get("affected_row_count", 0),
                last_insert_rowid=response_data.get("last_insert_rowid"),
            )

    @staticmethod
    def _encode_arg(val: Any) -> Dict[str, Any]:
        if val is None:
            return {"type": "null"}
        if isinstance(val, int):
            return {"type": "integer", "value": str(val)}
        if isinstance(val, float):
            return {"type": "float", "value": val}
        if isinstance(val, (bytes, bytearray)):
            import base64
            return {"type": "blob", "base64": base64.b64encode(val).decode("ascii")}
        return {"type": "text", "value": str(val)}

    @staticmethod
    def _decode_val(val_dict: Dict[str, Any]) -> Any:
        vtype = val_dict.get("type")
        if vtype == "null":
            return None
        if vtype == "integer":
            return int(val_dict.get("value", 0))
        if vtype == "float":
            return float(val_dict.get("value", 0.0))
        if vtype == "text":
            return val_dict.get("value", "")
        if vtype == "blob":
            import base64
            return base64.b64decode(val_dict.get("base64", ""))
        return val_dict.get("value")

    def close(self):
        if self._sqlite_conn:
            self._sqlite_conn.close()
            self._sqlite_conn = None
