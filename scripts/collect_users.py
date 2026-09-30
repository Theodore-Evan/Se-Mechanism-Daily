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
    from .collect_papers import DEFAULT_JOURNAL_METRICS, call_gemini_native, call_openai_compatible, collect
except ImportError:  # Direct execution: python scripts/collect_users.py
    from collect_papers import DEFAULT_JOURNAL_METRICS, call_gemini_native, call_openai_compatible, collect


PROVIDER_SECRET_NAMES = {
    "zhipu": "ZHIPU_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "custom": "CUSTOM_LLM_API_KEY",
}

RESEARCH_MAP_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "thesis": {"type": "string"},
        "root": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "description": {"type": "string"}},
            "required": ["name", "description"],
        },
        "branches": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"}, "name": {"type": "string"},
                    "focus": {"type": "string"}, "priority": {"type": "string"},
                    "papers": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "paper_id": {"type": "string"}, "title": {"type": "string"},
                                "year": {"type": "integer"}, "role": {"type": "string"},
                                "finding": {"type": "string"}, "evidence": {"type": "string"},
                                "connection": {"type": "string"},
                                "methods": {"type": "array", "items": {"type": "string"}},
                                "models": {"type": "array", "items": {"type": "string"}},
                                "mechanisms": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["paper_id", "title", "year", "role", "finding", "evidence", "connection", "methods", "models", "mechanisms"],
                        },
                    },
                },
                "required": ["id", "name", "focus", "priority", "papers"],
            },
        },
        "cross_links": {"type": "array", "items": {"type": "object"}},
        "research_gaps": {"type": "array", "items": {"type": "string"}},
        "next_questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "thesis", "root", "branches", "cross_links", "research_gaps", "next_questions"],
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


def update_map_request(rest: SupabaseRest, request_id: int, status: str, error: str = "") -> None:
    rest.request(
        "research_map_requests",
        method="PATCH",
        query={"id": f"eq.{request_id}"},
        body={"status": status, "processed_at": dt.datetime.now(dt.UTC).isoformat(), "error_message": error[:1000]},
        prefer="return=minimal",
    )


def compact_starred_papers(rows: list[dict[str, Any]], limit: int = 30) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for row in rows[:limit]:
        paper = row.get("payload") or {}
        summary = paper.get("chinese_summary") or {}
        compact.append({
            "paper_id": str(row.get("paper_id") or paper_id(paper)),
            "title": str(paper.get("title") or "未命名文献")[:500],
            "published": str(paper.get("published") or ""),
            "journal": str((paper.get("journal_profile") or {}).get("name") or paper.get("journal") or ""),
            "abstract": str(paper.get("summary") or "")[:4000],
            "structured_summary": {
                key: str(summary.get(key) or "")[:1200]
                for key in ("problem", "method", "innovation", "evidence", "limitations", "why_relevant")
            },
            "topic": str((paper.get("best_match") or {}).get("topic_name") or ""),
            "categories": [str(item)[:120] for item in (paper.get("categories") or [])[:12]],
        })
    return compact


def build_research_map_prompt(papers: list[dict[str, Any]]) -> str:
    return f"""你是一名严谨的生物医学研究战略分析师。请仅根据输入文献构建一张中文“个人研究体系演化树”，返回严格 JSON。

目标不是罗列关键词，而是综合多篇论文形成可研究的机制体系：
1. 提炼一个共同主干（核心科学问题与总体机制假说）。
2. 将证据组织成 2–7 个重点分支；分支应是机制轴、疾病/表型轴或实验策略轴，而不是宽泛关键词。
3. 每篇论文只能引用输入中的 paper_id，可进入最主要的一个分支；说明它在体系中的 role、finding、methods、models、mechanisms、evidence 和 connection。
4. 按发表年份呈现演进。无法从摘要确认的模型、方法或因果关系必须写“摘要未说明”，不得补造。
5. cross_links 描述分支之间的真实联系，字段为 source_branch、target_branch、relationship、paper_ids。
6. research_gaps 和 next_questions 必须从现有证据缺口推出，并保持可验证。
7. priority 只允许 core、major、emerging。分支 id 使用简短英文或数字标识且唯一。

输入文献：
{json.dumps(papers, ensure_ascii=False)}
"""


def normalize_research_map(result: dict[str, Any], papers: list[dict[str, Any]]) -> dict[str, Any]:
    valid_ids = {item["paper_id"] for item in papers}
    branches: list[dict[str, Any]] = []
    for index, raw_branch in enumerate((result.get("branches") or [])[:7]):
        if not isinstance(raw_branch, dict):
            continue
        branch_id = str(raw_branch.get("id") or f"branch-{index + 1}")[:80]
        branch_papers: list[dict[str, Any]] = []
        for item in (raw_branch.get("papers") or []):
            if not isinstance(item, dict) or str(item.get("paper_id") or "") not in valid_ids:
                continue
            cleaned = dict(item)
            cleaned["paper_id"] = str(item["paper_id"])
            try:
                cleaned["year"] = int(item.get("year") or 0)
            except (TypeError, ValueError):
                cleaned["year"] = 0
            for field in ("methods", "models", "mechanisms"):
                cleaned[field] = [str(value)[:180] for value in (item.get(field) or [])[:8]]
            for field in ("title", "role", "finding", "evidence", "connection"):
                cleaned[field] = str(item.get(field) or "摘要未说明")[:1200]
            branch_papers.append(cleaned)
        if branch_papers:
            branches.append({
                "id": branch_id,
                "name": str(raw_branch.get("name") or f"研究分支 {index + 1}")[:160],
                "focus": str(raw_branch.get("focus") or "")[:1200],
                "priority": str(raw_branch.get("priority") or "major") if str(raw_branch.get("priority") or "major") in {"core", "major", "emerging"} else "major",
                "papers": branch_papers,
            })
    if not branches:
        raise ValueError("模型未生成包含有效文献的研究分支")
    known_branches = {item["id"] for item in branches}
    links = []
    for link in (result.get("cross_links") or [])[:20]:
        if not isinstance(link, dict):
            continue
        source = str(link.get("source_branch") or "")
        target = str(link.get("target_branch") or "")
        if source in known_branches and target in known_branches and source != target:
            links.append({
                "source_branch": source, "target_branch": target,
                "relationship": str(link.get("relationship") or "")[:800],
                "paper_ids": [str(value) for value in (link.get("paper_ids") or []) if str(value) in valid_ids][:10],
            })
    root = result.get("root") if isinstance(result.get("root"), dict) else {}
    return {
        "title": str(result.get("title") or "我的研究体系")[:200],
        "thesis": str(result.get("thesis") or "")[:2000],
        "root": {"name": str(root.get("name") or "核心研究问题")[:200], "description": str(root.get("description") or "")[:1600]},
        "branches": branches,
        "cross_links": links,
        "research_gaps": [str(value)[:1000] for value in (result.get("research_gaps") or [])[:12]],
        "next_questions": [str(value)[:1000] for value in (result.get("next_questions") or [])[:12]],
    }


def build_research_map_one(
    rest: SupabaseRest,
    setting: dict[str, Any],
    credential_rows: list[dict[str, Any]],
    master_key: str,
    pending_requests: list[dict[str, Any]],
) -> None:
    user_id = str(setting["user_id"])
    for item in pending_requests:
        update_map_request(rest, int(item["id"]), "running")
    try:
        config = setting.get("config") or {}
        runtime = config.get("runtime") if isinstance(config.get("runtime"), dict) else {}
        provider = str(runtime.get("provider") or "zhipu").lower()
        credentials = decrypt_credentials(credential_rows, master_key)
        api_key = credentials.get(provider, "").strip()
        if not api_key:
            raise ValueError(f"{provider} API Key 未配置")
        rows = rest.request(
            "user_starred_papers",
            query={"select": "paper_id,payload,created_at", "user_id": f"eq.{user_id}", "order": "created_at.desc"},
        ) or []
        papers = compact_starred_papers(rows)
        if not papers:
            raise ValueError("请至少 Star 一篇文献后再构建研究体系")
        base_url = str(runtime.get("base_url") or "https://open.bigmodel.cn/api/paas/v4").rstrip("/")
        model = str(runtime.get("model") or "glm-4-flash-250414")
        prompt = build_research_map_prompt(papers)
        if "generativelanguage.googleapis.com" in base_url:
            raw = call_gemini_native(prompt, api_key, base_url, model, RESEARCH_MAP_SCHEMA)
        else:
            raw = call_openai_compatible(prompt, api_key, base_url, model)
        payload = normalize_research_map(raw, papers)
        now = dt.datetime.now(dt.UTC).isoformat()
        rest.request(
            "user_research_maps",
            method="POST",
            body={"user_id": user_id, "payload": payload, "source_count": len(papers), "generated_at": now, "updated_at": now},
            prefer="resolution=merge-duplicates,return=minimal",
        )
        for item in pending_requests:
            update_map_request(rest, int(item["id"]), "completed")
        print(f"Built research map from {len(papers)} starred papers for user {user_id}")
    except Exception as exc:
        for item in pending_requests:
            update_map_request(rest, int(item["id"]), "failed", str(exc))
        raise


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
    try:
        map_requests = rest.request(
            "research_map_requests",
            query={"select": "id,user_id", "status": "eq.pending", "order": "requested_at.asc"},
        ) or []
    except RuntimeError as exc:
        # Keep collection and Pages deployment working while an existing
        # installation is applying the optional research-map migration.
        if "research_map_requests" not in str(exc) or "(404)" not in str(exc):
            raise
        print("Warning: research map tables are not installed yet; skipping map requests")
        map_requests = []
    credentials_by_user: dict[str, list[dict[str, Any]]] = {}
    requests_by_user: dict[str, list[dict[str, Any]]] = {}
    map_requests_by_user: dict[str, list[dict[str, Any]]] = {}
    for row in credentials:
        credentials_by_user.setdefault(str(row["user_id"]), []).append(row)
    for row in requests:
        requests_by_user.setdefault(str(row["user_id"]), []).append(row)
    for row in map_requests:
        map_requests_by_user.setdefault(str(row["user_id"]), []).append(row)

    failures = 0
    for setting in settings:
        user_id = str(setting["user_id"])
        collection_requested = user_id in requests_by_user
        map_requested = user_id in map_requests_by_user
        if pending_only and not collection_requested and not map_requested:
            continue
        if not pending_only or collection_requested:
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
        if map_requested:
            try:
                build_research_map_one(
                    rest,
                    setting,
                    credentials_by_user.get(user_id, []),
                    master_key,
                    map_requests_by_user[user_id],
                )
            except Exception as exc:
                failures += 1
                print(f"Research map failed for user {user_id}: {exc}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
