"""Collect isolated paper feeds for every configured account.

The service role is used only inside GitHub Actions. Browser clients can read
their own rows through Row Level Security but cannot read any API credential.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

try:
    from .collect_papers import DEFAULT_JOURNAL_METRICS, collect
except ImportError:  # Direct execution: python scripts/collect_users.py
    from collect_papers import DEFAULT_JOURNAL_METRICS, collect


PROVIDER_SECRET_NAMES = {
    "zhipu": "ZHIPU_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "custom": "CUSTOM_LLM_API_KEY",
}


class SupabaseRest:
    def __init__(self, url: str, service_key: str) -> None:
        self.base = url.rstrip("/") + "/rest/v1"
        self.headers = {
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
        }

    def request(
        self,
        path: str,
        *,
        method: str = "GET",
        query: dict[str, str] | None = None,
        body: Any = None,
        prefer: str = "return=representation",
    ) -> Any:
        url = f"{self.base}/{path.lstrip('/')}"
        if query:
            url += "?" + urllib.parse.urlencode(query, safe="(),.*:")
        headers = dict(self.headers)
        if prefer:
            headers["Prefer"] = prefer
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                content = response.read()
                return json.loads(content) if content else None
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", "replace")
            raise RuntimeError(f"Supabase {method} {path} failed ({exc.code}): {details}") from exc


def decrypt_credentials(rows: list[dict[str, Any]], encoded_master_key: str) -> dict[str, str]:
    raw_key = base64.b64decode(encoded_master_key)
    if len(raw_key) != 32:
        raise ValueError("USER_SECRET_MASTER_KEY must decode to exactly 32 bytes")
    aes = AESGCM(raw_key)
    credentials: dict[str, str] = {}
    for row in rows:
        credentials[str(row["provider"])] = aes.decrypt(
            base64.b64decode(row["iv"]),
            base64.b64decode(row["ciphertext"]),
            None,
        ).decode("utf-8")
    return credentials


def paper_id(paper: dict[str, Any]) -> str:
    return str(paper.get("id") or paper.get("doi") or paper.get("paper_url") or paper.get("title") or "paper")


def current_dataset(rest: SupabaseRest, user_id: str, config: dict[str, Any]) -> dict[str, Any]:
    rows = rest.request(
        "user_papers",
        query={"select": "payload", "user_id": f"eq.{user_id}", "order": "last_seen_at.desc"},
    ) or []
    return {
        "papers": [row["payload"] for row in rows if row.get("payload")],
        "topics": config.get("topics", []),
        "sources": config.get("sources", []),
        "runtime": config.get("runtime", {}),
    }


def set_environment(config: dict[str, Any], credentials: dict[str, str]) -> None:
    for name in set(PROVIDER_SECRET_NAMES.values()) | {"LLM_API_KEY", "SERPAPI_API_KEY"}:
        os.environ.pop(name, None)
    runtime = config.get("runtime") if isinstance(config.get("runtime"), dict) else {}
    provider = str(runtime.get("provider") or "zhipu").lower()
    if provider in credentials and provider in PROVIDER_SECRET_NAMES:
        os.environ[PROVIDER_SECRET_NAMES[provider]] = credentials[provider]
        os.environ["LLM_API_KEY"] = credentials[provider]
    if credentials.get("serpapi"):
        os.environ["SERPAPI_API_KEY"] = credentials["serpapi"]
    os.environ.pop("GITHUB_REPOSITORY", None)
    os.environ.pop("GITHUB_TOKEN", None)


def update_request(rest: SupabaseRest, request_id: int, status: str, error: str = "") -> None:
    rest.request(
        "collection_requests",
        method="PATCH",
        query={"id": f"eq.{request_id}"},
        body={"status": status, "processed_at": dt.datetime.now(dt.UTC).isoformat(), "error_message": error[:1000]},
        prefer="return=minimal",
    )


def collect_one(
    rest: SupabaseRest,
    setting: dict[str, Any],
    credential_rows: list[dict[str, Any]],
    master_key: str,
    pending_requests: list[dict[str, Any]],
) -> None:
    user_id = str(setting["user_id"])
    config = setting.get("config") or {}
    credentials = decrypt_credentials(credential_rows, master_key)
    set_environment(config, credentials)
    clear_cache = any(bool(item.get("clear_cache")) for item in pending_requests)
    for item in pending_requests:
        update_request(rest, int(item["id"]), "running")

    started_at = dt.datetime.now(dt.UTC).isoformat()
    run_rows = rest.request(
        "collection_runs",
        method="POST",
        body={"user_id": user_id, "status": "running", "started_at": started_at},
    )
    run_id = int(run_rows[0]["id"])

    try:
        runtime = config.get("runtime") or {}
        with tempfile.TemporaryDirectory(prefix="se-user-") as temporary:
            temporary_path = Path(temporary)
            config_path = temporary_path / "config.json"
            output_path = temporary_path / "papers.json"
            config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
            output_path.write_text(json.dumps(current_dataset(rest, user_id, config), ensure_ascii=False), encoding="utf-8")
            result = collect(
                config_path,
                output_path,
                lookback_days=max(1, int(runtime.get("lookback_days", 7))),
                max_per_topic=max(1, int(runtime.get("max_per_topic", 10))),
                max_summaries=max(0, int(runtime.get("max_summaries", 12))),
                clear_cache=clear_cache,
                journal_metrics_path=DEFAULT_JOURNAL_METRICS,
            )

        rest.request(
            "rpc/replace_user_papers",
            method="POST",
            body={"target_user": user_id, "paper_rows": result.get("papers", [])},
            prefer="return=minimal",
        )
        rest.request(
            "collection_runs",
            method="PATCH",
            query={"id": f"eq.{run_id}"},
            body={
                "status": "completed",
                "completed_at": dt.datetime.now(dt.UTC).isoformat(),
                "stats": result.get("stats", {}),
            },
            prefer="return=minimal",
        )
        for item in pending_requests:
            update_request(rest, int(item["id"]), "completed")
        print(f"Collected {len(result.get('papers', []))} papers for user {user_id}")
    except Exception as exc:
        rest.request(
            "collection_runs",
            method="PATCH",
            query={"id": f"eq.{run_id}"},
            body={
                "status": "failed",
                "completed_at": dt.datetime.now(dt.UTC).isoformat(),
                "error_message": str(exc)[:1000],
            },
            prefer="return=minimal",
        )
        for item in pending_requests:
            update_request(rest, int(item["id"]), "failed", str(exc))
        raise


def main() -> int:
    url = os.environ["SUPABASE_URL"].strip()
    service_key = os.environ["SUPABASE_SERVICE_ROLE_KEY"].strip()
    master_key = os.environ["USER_SECRET_MASTER_KEY"].strip()
    pending_only = os.getenv("COLLECT_PENDING_ONLY", "false").lower() in {"1", "true", "yes"}
    rest = SupabaseRest(url, service_key)

    settings = rest.request("user_settings", query={"select": "user_id,config"}) or []
    credentials = rest.request(
        "user_api_credentials",
        query={"select": "user_id,provider,ciphertext,iv"},
    ) or []
    requests = rest.request(
        "collection_requests",
        query={"select": "id,user_id,clear_cache", "status": "eq.pending", "order": "requested_at.asc"},
    ) or []
    credentials_by_user: dict[str, list[dict[str, Any]]] = {}
    requests_by_user: dict[str, list[dict[str, Any]]] = {}
    for row in credentials:
        credentials_by_user.setdefault(str(row["user_id"]), []).append(row)
    for row in requests:
        requests_by_user.setdefault(str(row["user_id"]), []).append(row)

    failures = 0
    for setting in settings:
        user_id = str(setting["user_id"])
        if pending_only and user_id not in requests_by_user:
            continue
        try:
            collect_one(
                rest,
                setting,
                credentials_by_user.get(user_id, []),
                master_key,
                requests_by_user.get(user_id, []),
            )
        except Exception as exc:
            failures += 1
            print(f"Collection failed for user {user_id}: {exc}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
