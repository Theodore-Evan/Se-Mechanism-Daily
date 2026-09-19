"""Write the public browser configuration used by the GitHub Pages build."""

from __future__ import annotations

import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "web" / "runtime-config.js"


def main() -> int:
    require_auth = os.getenv("MULTI_USER_MODE", "false").strip().lower() in {"1", "true", "yes", "on"}
    payload = {
        "supabaseUrl": os.getenv("SUPABASE_URL", "").strip(),
        "supabasePublishableKey": os.getenv("SUPABASE_PUBLISHABLE_KEY", "").strip(),
        "requireAuth": require_auth,
    }
    OUTPUT.write_text(
        "window.SE_MECHANISM_CONFIG = Object.freeze(" + json.dumps(payload, ensure_ascii=False) + ");\n",
        encoding="utf-8",
    )
    if require_auth:
        papers_path = ROOT / "web" / "data" / "papers.json"
        if papers_path.exists():
            existing = json.loads(papers_path.read_text(encoding="utf-8"))
            public_template = {
                "data_kind": existing.get("data_kind", "selenium_mechanism"),
                "sources": existing.get("sources", []),
                "topics": existing.get("topics", []),
                "runtime": existing.get("runtime", {}),
                "papers": [],
                "stats": {},
            }
            papers_path.write_text(json.dumps(public_template, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
