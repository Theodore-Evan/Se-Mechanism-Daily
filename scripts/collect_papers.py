#!/usr/bin/env python3
"""Collect selenium-mechanism papers and build the static website dataset.

The collector intentionally uses only Python's standard library so that a fork can
run on GitHub Actions without installing application dependencies.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import datetime as dt
import email.utils
import html
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "interests.json"
DEFAULT_JOURNAL_METRICS = ROOT / "config" / "journal_metrics.json"
DEFAULT_OUTPUT = ROOT / "web" / "data" / "papers.json"
ARXIV_API = "https://export.arxiv.org/api/query"
PUBMED_EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
OPENALEX_API = "https://api.openalex.org/works"
CROSSREF_API = "https://api.crossref.org/works"
SERPAPI_API = "https://serpapi.com/search.json"
UTC = dt.timezone.utc


@dataclasses.dataclass(frozen=True)
class Topic:
    id: str
    name: str
    description: str
    keywords: list[str]
    arxiv_categories: list[str]


@dataclasses.dataclass(frozen=True)
class Source:
    type: str
    name: str


class APIRequestError(RuntimeError):
    def __init__(self, status: int, message: str, retry_after: float | None = None) -> None:
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.retry_after = retry_after


def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def utc_now() -> dt.datetime:
    return dt.datetime.now(UTC)


def parse_datetime(value: Any) -> dt.datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if re.fullmatch(r"\d{4}", text):
        text = f"{text}-01-01"
    if re.fullmatch(r"\d{4}-\d{2}", text):
        text = f"{text}-01"
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = dt.datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def request_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    timeout: float = 45,
) -> Any:
    request_headers = {
        "Accept": "application/json",
        "User-Agent": "se-mechanism-literature-tracker/1.0",
        **(headers or {}),
    }
    request = urllib.request.Request(url, headers=request_headers, data=data)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        message = body
        try:
            error_data = json.loads(body)
            error_value = error_data.get("error", error_data)
            message = error_value.get("message", str(error_value)) if isinstance(error_value, dict) else str(error_value)
        except json.JSONDecodeError:
            pass
        retry_after = None
        try:
            retry_after = float(exc.headers.get("Retry-After", ""))
        except (TypeError, ValueError):
            pass
        raise APIRequestError(exc.code, normalize_space(message)[:500], retry_after) from exc


def request_text(url: str, *, timeout: float = 45) -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "se-mechanism-literature-tracker/1.0"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def normalize_space(value: Any) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def strip_markup(value: Any) -> str:
    return normalize_space(re.sub(r"<[^>]+>", " ", str(value or "")))


def normalize_title(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).casefold().replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", "", text)


def normalize_journal_name(value: Any) -> str:
    text = unicodedata.normalize("NFKD", normalize_space(value)).casefold().replace("&", " and ")
    text = re.sub(r"\b(the|journal of)\b", " ", text)
    return re.sub(r"[^a-z0-9]+", "", text)


def load_journal_metrics(path: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    data = read_json(path, {})
    if not isinstance(data, dict):
        data = {}
    settings = {
        "metric_name": normalize_space(data.get("metric_name")) or "Journal Impact Factor",
        "metric_year": str(data.get("metric_year") or "").strip(),
        "quartile_system": normalize_space(data.get("quartile_system")) or "JCR",
        "source_url": normalize_space(data.get("source_url")),
        "note": normalize_space(data.get("note")),
    }
    index: dict[str, dict[str, Any]] = {}
    for item in data.get("journals", []):
        if not isinstance(item, dict) or not normalize_space(item.get("name")):
            continue
        entry = {
            **item,
            "name": normalize_space(item.get("name")),
            "family": normalize_space(item.get("family")).lower(),
            "tier": normalize_space(item.get("tier")).lower() or "standard",
            "metric_year": str(item.get("metric_year") or settings["metric_year"]).strip(),
            "metric_source": normalize_space(item.get("source_url")) or settings["source_url"],
            "quartile_system": normalize_space(item.get("quartile_system")) or settings["quartile_system"],
        }
        aliases = [entry["name"], *(item.get("aliases") or [])]
        for alias in aliases:
            key = normalize_journal_name(alias)
            if key:
                index[key] = entry
    return settings, index


SCIENCE_FAMILY = {
    "science advances",
    "science immunology",
    "science robotics",
    "science signaling",
    "science translational medicine",
}
CELL_FAMILY = {
    "cancer cell",
    "cell chemical biology",
    "cell host and microbe",
    "cell metabolism",
    "cell reports",
    "cell stem cell",
    "current biology",
    "immunity",
    "molecular cell",
    "neuron",
}


def inferred_journal_group(journal: str) -> tuple[str, str]:
    name = normalize_space(journal).casefold().replace("&", "and")
    if name in {"nature", "science", "cell"}:
        return name, "flagship"
    if (
        name.startswith("nature ")
        or name.startswith("nature reviews ")
        or name.startswith("npj ")
        or name in {"nature communications", "scientific data", "scientific reports"}
        or name.startswith("communications ")
    ):
        return "nature", "family"
    if name in SCIENCE_FAMILY:
        return "science", "family"
    if name in CELL_FAMILY or name.startswith("trends in "):
        return "cell", "family"
    return "", "standard"


def build_journal_profile(
    paper: dict[str, Any],
    settings: dict[str, Any],
    index: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    journal = normalize_space(paper.get("journal"))
    previous_profile = paper.get("journal_profile") if isinstance(paper.get("journal_profile"), dict) else {}
    if not journal:
        journal = normalize_space(previous_profile.get("name"))
    entry = index.get(normalize_journal_name(journal), {})
    family, tier = inferred_journal_group(journal)
    family = normalize_space(entry.get("family")).lower() or family
    tier = normalize_space(entry.get("tier")).lower() or tier
    impact_factor = entry.get("impact_factor")
    if not isinstance(impact_factor, (int, float)):
        impact_factor = None
    quartile = normalize_space(entry.get("quartile")).upper()
    labels = []
    if tier == "flagship":
        labels.append("CNS")
    elif family == "nature":
        labels.append("Nature 系列")
    elif family == "science":
        labels.append("Science 系列")
    elif family == "cell":
        labels.append("Cell 系列")
    if tier == "top" and "Top" not in labels:
        labels.append("Top")
    return {
        "name": normalize_space(entry.get("name")) or journal,
        "family": family,
        "tier": tier,
        "is_top": tier in {"flagship", "family", "top"},
        "labels": labels,
        "impact_factor": impact_factor,
        "metric_name": settings["metric_name"],
        "metric_year": str(entry.get("metric_year") or settings["metric_year"]),
        "metric_source": normalize_space(entry.get("metric_source")) or settings["source_url"],
        "quartile": quartile,
        "quartile_system": normalize_space(entry.get("quartile_system")) or settings["quartile_system"],
    }


def canonical_key(paper: dict[str, Any]) -> str:
    doi = str(paper.get("doi") or "").lower().removeprefix("https://doi.org/").strip()
    if doi:
        return f"doi:{doi}"
    identifier = str(paper.get("id") or "").strip()
    if identifier:
        return identifier.lower()
    return f"title:{normalize_title(paper.get('title'))}"


def parse_config(data: dict[str, Any]) -> tuple[list[Source], list[Topic]]:
    sources = [
        Source(type=str(item.get("type", "")).strip(), name=str(item.get("name", "")).strip())
        for item in data.get("sources", [])
        if isinstance(item, dict) and str(item.get("type", "")).strip()
    ]
    topics = []
    for item in data.get("topics", []):
        if not isinstance(item, dict) or not item.get("id") or not item.get("name"):
            continue
        topics.append(
            Topic(
                id=str(item["id"]),
                name=str(item["name"]),
                description=str(item.get("description", "")),
                keywords=[str(value).strip() for value in item.get("keywords", []) if str(value).strip()],
                arxiv_categories=[
                    str(value).strip() for value in item.get("arxiv_categories", []) if str(value).strip()
                ],
            )
        )
    if not sources:
        raise ValueError("配置文件至少需要一个 sources 条目。")
    if not topics:
        raise ValueError("配置文件至少需要一个 topics 条目。")
    return sources, topics


def issue_config(repository_config: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Use the JSON block in a matching GitHub issue when one is available."""
    repository = os.getenv("GITHUB_REPOSITORY", "").strip()
    token = os.getenv("GITHUB_TOKEN", "").strip()
    issue_title = os.getenv("CONFIG_ISSUE_TITLE", "Research Interests").strip()
    if not repository or not token:
        return repository_config, "repository"
    url = f"https://api.github.com/repos/{repository}/issues?state=open&per_page=100"
    try:
        issues = request_json(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
    except Exception as exc:  # GitHub issue configuration is optional.
        print(f"Warning: unable to read configuration issue: {exc}", file=sys.stderr)
        return repository_config, "repository"
    for issue in issues if isinstance(issues, list) else []:
        if str(issue.get("title", "")).strip() != issue_title:
            continue
        match = re.search(r"```json\s*(\{.*?\})\s*```", str(issue.get("body", "")), flags=re.DOTALL)
        if not match:
            continue
        try:
            candidate = json.loads(match.group(1))
            parse_config(candidate)
            return candidate, f"issue #{issue.get('number')}"
        except (json.JSONDecodeError, ValueError) as exc:
            print(f"Warning: invalid JSON in configuration issue: {exc}", file=sys.stderr)
    return repository_config, "repository"


def topic_query(topic: Topic) -> str:
    terms = topic.keywords or [topic.name]
    return " OR ".join(f'"{term}"' for term in terms)


def arxiv_query(topic: Topic) -> str:
    terms = [f'all:"{term}"' for term in (topic.keywords or [topic.name])]
    keyword_query = "(" + " OR ".join(terms) + ")"
    if env_flag("ARXIV_EXPAND_CATEGORY_SEARCH", False) and topic.arxiv_categories:
        category_query = "(" + " OR ".join(f"cat:{category}" for category in topic.arxiv_categories) + ")"
        return f"{keyword_query} OR {category_query}"
    return keyword_query


def xml_text(node: ET.Element | None, path: str, namespaces: dict[str, str]) -> str:
    if node is None:
        return ""
    child = node.find(path, namespaces)
    return normalize_space(child.text if child is not None else "")


def fetch_arxiv(topic: Topic, limit: int) -> list[dict[str, Any]]:
    params = {
        "search_query": arxiv_query(topic),
        "start": 0,
        "max_results": limit,
        "sortBy": os.getenv("ARXIV_SORT_BY", "lastUpdatedDate"),
        "sortOrder": "descending",
    }
    root = ET.fromstring(request_text(f"{ARXIV_API}?{urllib.parse.urlencode(params)}"))
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "arxiv": "http://arxiv.org/schemas/atom",
    }
    papers = []
    for entry in root.findall("atom:entry", ns):
        identifier = xml_text(entry, "atom:id", ns)
        links = {link.attrib.get("title", ""): link.attrib.get("href", "") for link in entry.findall("atom:link", ns)}
        authors = [
            xml_text(author, "atom:name", ns)
            for author in entry.findall("atom:author", ns)
            if xml_text(author, "atom:name", ns)
        ]
        papers.append(
            {
                "id": f"arxiv:{identifier.rstrip('/').split('/')[-1]}",
                "source": "arXiv",
                "title": xml_text(entry, "atom:title", ns),
                "summary": xml_text(entry, "atom:summary", ns),
                "authors": authors,
                "published": xml_text(entry, "atom:published", ns),
                "updated": xml_text(entry, "atom:updated", ns),
                "categories": [node.attrib.get("term", "") for node in entry.findall("atom:category", ns)],
                "journal": xml_text(entry, "arxiv:journal_ref", ns) or "arXiv",
                "paper_url": identifier,
                "pdf_url": links.get("pdf", ""),
            }
        )
    return papers


def pubmed_params(extra: dict[str, Any]) -> str:
    params: dict[str, Any] = {"db": "pubmed", "retmode": "json", **extra}
    if os.getenv("NCBI_API_KEY"):
        params["api_key"] = os.environ["NCBI_API_KEY"]
    contact = os.getenv("NCBI_EMAIL") or os.getenv("CONTACT_EMAIL")
    if contact:
        params["email"] = contact
    return urllib.parse.urlencode(params)


def pubmed_date(article: ET.Element, summary: dict[str, Any]) -> str:
    for path in (
        ".//ArticleDate",
        ".//JournalIssue/PubDate",
        ".//PubMedPubDate[@PubStatus='pubmed']",
        ".//PubMedPubDate[@PubStatus='entrez']",
    ):
        node = article.find(path)
        if node is None:
            continue
        year = normalize_space(node.findtext("Year"))
        month = normalize_space(node.findtext("Month")) or "01"
        day = normalize_space(node.findtext("Day")) or "01"
        if year:
            try:
                month_number = int(month)
            except ValueError:
                try:
                    month_number = list(calendar_months()).index(month[:3].title()) + 1
                except ValueError:
                    month_number = 1
            return f"{year}-{month_number:02d}-{int(day):02d}"
    return str(summary.get("pubdate") or "")


def calendar_months() -> tuple[str, ...]:
    return ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def fetch_pubmed(topic: Topic, limit: int) -> list[dict[str, Any]]:
    search_url = f"{PUBMED_EUTILS}/esearch.fcgi?{pubmed_params({'term': topic_query(topic), 'retmax': limit, 'sort': 'pub date'})}"
    identifiers = request_json(search_url).get("esearchresult", {}).get("idlist", [])
    if not identifiers:
        return []
    joined = ",".join(identifiers)
    summary_url = f"{PUBMED_EUTILS}/esummary.fcgi?{pubmed_params({'id': joined})}"
    summaries = request_json(summary_url).get("result", {})
    fetch_params = {"db": "pubmed", "id": joined, "retmode": "xml"}
    if os.getenv("NCBI_API_KEY"):
        fetch_params["api_key"] = os.environ["NCBI_API_KEY"]
    if os.getenv("NCBI_EMAIL") or os.getenv("CONTACT_EMAIL"):
        fetch_params["email"] = os.getenv("NCBI_EMAIL") or os.getenv("CONTACT_EMAIL")
    root = ET.fromstring(request_text(f"{PUBMED_EUTILS}/efetch.fcgi?{urllib.parse.urlencode(fetch_params)}"))
    papers = []
    for article in root.findall(".//PubmedArticle"):
        pmid = normalize_space(article.findtext(".//PMID"))
        if not pmid:
            continue
        summary = summaries.get(pmid, {})
        title_node = article.find(".//ArticleTitle")
        title = normalize_space("".join(title_node.itertext()) if title_node is not None else summary.get("title"))
        abstract_parts = []
        for node in article.findall(".//Abstract/AbstractText"):
            label = normalize_space(node.attrib.get("Label"))
            text = normalize_space("".join(node.itertext()))
            if text:
                abstract_parts.append(f"{label}: {text}" if label else text)
        authors = []
        for author in article.findall(".//Author"):
            collective = normalize_space(author.findtext("CollectiveName"))
            personal = normalize_space(
                " ".join(filter(None, [author.findtext("ForeName"), author.findtext("LastName")]))
            )
            if collective or personal:
                authors.append(collective or personal)
        doi = ""
        for node in article.findall(".//ArticleId"):
            if node.attrib.get("IdType") == "doi":
                doi = normalize_space(node.text)
                break
        papers.append(
            {
                "id": f"pubmed:{pmid}",
                "source": "PubMed",
                "title": title,
                "summary": normalize_space(" ".join(abstract_parts)),
                "authors": authors,
                "published": pubmed_date(article, summary),
                "updated": str(summary.get("sortpubdate") or ""),
                "categories": [
                    normalize_space(node.text)
                    for node in article.findall(".//MeshHeading/DescriptorName")
                    if normalize_space(node.text)
                ],
                "journal": normalize_space(article.findtext(".//Journal/Title"))
                or normalize_space(summary.get("fulljournalname"))
                or normalize_space(summary.get("source")),
                "paper_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                "pdf_url": "",
                "doi": doi,
            }
        )
    return papers


def reconstruct_abstract(index: dict[str, list[int]] | None) -> str:
    if not index:
        return ""
    words = [(position, word) for word, positions in index.items() for position in positions]
    return normalize_space(" ".join(word for _, word in sorted(words)))


def fetch_openalex(topic: Topic, limit: int) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "search": topic_query(topic),
        "per-page": min(limit, 200),
        "sort": "publication_date:desc",
    }
    if os.getenv("OPENALEX_EMAIL") or os.getenv("CONTACT_EMAIL"):
        params["mailto"] = os.getenv("OPENALEX_EMAIL") or os.getenv("CONTACT_EMAIL")
    data = request_json(f"{OPENALEX_API}?{urllib.parse.urlencode(params)}")
    papers = []
    for item in data.get("results", []):
        primary = item.get("primary_location") or {}
        best = item.get("best_oa_location") or {}
        doi = str(item.get("doi") or "").removeprefix("https://doi.org/")
        papers.append(
            {
                "id": f"openalex:{str(item.get('id', '')).rstrip('/').split('/')[-1]}",
                "source": "OpenAlex",
                "title": normalize_space(item.get("display_name")),
                "summary": reconstruct_abstract(item.get("abstract_inverted_index")),
                "authors": [
                    normalize_space(authorship.get("author", {}).get("display_name"))
                    for authorship in item.get("authorships", [])
                    if normalize_space(authorship.get("author", {}).get("display_name"))
                ],
                "published": str(item.get("publication_date") or ""),
                "updated": str(item.get("updated_date") or item.get("publication_date") or ""),
                "categories": [
                    normalize_space(topic_item.get("display_name"))
                    for topic_item in item.get("topics", [])
                    if normalize_space(topic_item.get("display_name"))
                ],
                "journal": normalize_space((primary.get("source") or {}).get("display_name")),
                "paper_url": primary.get("landing_page_url") or item.get("doi") or item.get("id") or "",
                "pdf_url": best.get("pdf_url") or primary.get("pdf_url") or "",
                "doi": doi,
            }
        )
    return papers


def crossref_date(item: dict[str, Any]) -> str:
    for key in ("published-online", "published-print", "published", "issued", "created"):
        parts = (item.get(key) or {}).get("date-parts") or []
        if parts and parts[0]:
            values = list(parts[0]) + [1, 1]
            return f"{int(values[0]):04d}-{int(values[1]):02d}-{int(values[2]):02d}"
    return ""


def fetch_crossref(topic: Topic, limit: int) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "query.bibliographic": topic_query(topic),
        "rows": min(limit, 1000),
        "sort": "published",
        "order": "desc",
        "select": "DOI,title,abstract,author,published,published-online,published-print,issued,created,URL,link,subject,container-title",
    }
    contact = os.getenv("CROSSREF_EMAIL") or os.getenv("CONTACT_EMAIL")
    headers = {"User-Agent": f"se-mechanism-literature-tracker/1.0 (mailto:{contact})"} if contact else None
    data = request_json(f"{CROSSREF_API}?{urllib.parse.urlencode(params)}", headers=headers)
    papers = []
    for item in data.get("message", {}).get("items", []):
        doi = normalize_space(item.get("DOI"))
        links = item.get("link") or []
        pdf_url = next(
            (str(link.get("URL")) for link in links if "pdf" in str(link.get("content-type", "")).lower()),
            "",
        )
        authors = [
            normalize_space(" ".join(filter(None, [author.get("given"), author.get("family")])))
            for author in item.get("author", [])
        ]
        papers.append(
            {
                "id": f"doi:{doi.lower()}" if doi else f"crossref:{normalize_title((item.get('title') or [''])[0])}",
                "source": "Crossref",
                "title": normalize_space((item.get("title") or [""])[0]),
                "summary": strip_markup(item.get("abstract")),
                "authors": [author for author in authors if author],
                "published": crossref_date(item),
                "updated": crossref_date(item),
                "categories": [normalize_space(value) for value in item.get("subject", []) if normalize_space(value)],
                "journal": normalize_space((item.get("container-title") or [""])[0]),
                "paper_url": item.get("URL") or (f"https://doi.org/{doi}" if doi else ""),
                "pdf_url": pdf_url,
                "doi": doi,
            }
        )
    return papers


def scholar_year(result: dict[str, Any]) -> str:
    summary = str((result.get("publication_info") or {}).get("summary") or "")
    matches = re.findall(r"\b(?:19|20)\d{2}\b", summary)
    return matches[-1] if matches else ""


def scholar_journal(result: dict[str, Any]) -> str:
    summary = normalize_space((result.get("publication_info") or {}).get("summary"))
    parts = [part.strip(" ,") for part in summary.split(" - ") if part.strip(" ,")]
    if len(parts) < 2:
        return ""
    candidate = re.sub(r",?\s*\b(?:19|20)\d{2}\b.*$", "", parts[1]).strip(" ,")
    return candidate


def fetch_google_scholar(topic: Topic, limit: int) -> list[dict[str, Any]]:
    api_key = os.getenv("SERPAPI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("SERPAPI_API_KEY is not configured")
    params = {
        "engine": "google_scholar",
        "q": topic_query(topic),
        "num": min(limit, 20),
        "scisbd": 2,
        "api_key": api_key,
    }
    data = request_json(f"{SERPAPI_API}?{urllib.parse.urlencode(params)}")
    if data.get("error"):
        raise RuntimeError(str(data["error"]))
    papers = []
    for result in data.get("organic_results", []):
        info = result.get("publication_info") or {}
        identifier = normalize_space(result.get("result_id")) or normalize_title(result.get("title"))
        link = str(result.get("link") or "")
        resources = result.get("resources") or []
        pdf_url = next(
            (str(resource.get("link")) for resource in resources if str(resource.get("file_format", "")).upper() == "PDF"),
            "",
        )
        papers.append(
            {
                "id": f"scholar:{identifier}",
                "source": "Google Scholar",
                "title": normalize_space(result.get("title")),
                "summary": normalize_space(result.get("snippet")),
                "authors": [normalize_space(author.get("name")) for author in info.get("authors", []) if author.get("name")],
                "published": scholar_year(result),
                "updated": utc_now().isoformat(),
                "categories": [],
                "journal": scholar_journal(result),
                "paper_url": link,
                "pdf_url": pdf_url,
            }
        )
    return papers


SOURCE_FETCHERS: dict[str, Callable[[Topic, int], list[dict[str, Any]]]] = {
    "arxiv": fetch_arxiv,
    "pubmed": fetch_pubmed,
    "openalex": fetch_openalex,
    "crossref": fetch_crossref,
    "google_scholar_serpapi": fetch_google_scholar,
}


def merge_paper(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    merged = dict(left)
    sources = [value.strip() for value in f"{left.get('source', '')} + {right.get('source', '')}".split("+") if value.strip()]
    merged["source"] = " + ".join(dict.fromkeys(sources))
    for key in ("summary", "title"):
        if len(str(right.get(key) or "")) > len(str(merged.get(key) or "")):
            merged[key] = right[key]
    for key in ("paper_url", "pdf_url", "doi", "published", "updated", "journal"):
        if not merged.get(key) and right.get(key):
            merged[key] = right[key]
    merged["authors"] = list(dict.fromkeys([*(left.get("authors") or []), *(right.get("authors") or [])]))
    merged["categories"] = list(dict.fromkeys([*(left.get("categories") or []), *(right.get("categories") or [])]))
    return merged


def deduplicate(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    title_keys: dict[str, str] = {}
    for paper in papers:
        if not paper.get("title"):
            continue
        key = canonical_key(paper)
        title_key = normalize_title(paper.get("title"))
        existing_key = title_keys.get(title_key, key)
        if existing_key in by_key:
            by_key[existing_key] = merge_paper(by_key[existing_key], paper)
        else:
            by_key[key] = paper
            title_keys[title_key] = key
    return list(by_key.values())


def score_topic(topic: Topic, paper: dict[str, Any]) -> dict[str, Any]:
    title = str(paper.get("title") or "").casefold()
    summary = str(paper.get("summary") or "").casefold()
    categories = " ".join(paper.get("categories") or []).casefold()
    title_hits = [term for term in topic.keywords if term.casefold() in title]
    summary_hits = [term for term in topic.keywords if term.casefold() in summary]
    category_hits = [category for category in topic.arxiv_categories if category.casefold() in categories]
    score = min(0.95, 0.22 * len(title_hits) + 0.09 * len(summary_hits) + 0.04 * len(category_hits))
    if title_hits or summary_hits:
        score += 0.12
    score = min(score, 0.99)
    level = "high" if score >= 0.55 else "medium" if score >= 0.30 else "low"
    matches = list(dict.fromkeys([*title_hits, *summary_hits]))[:5]
    reason = f"匹配关键词：{', '.join(matches)}" if matches else "仅有弱相关分类信号"
    return {
        "topic_id": topic.id,
        "topic_name": topic.name,
        "score": round(score, 3),
        "level": level,
        "reason": reason,
    }


def attach_best_match(topics: list[Topic], paper: dict[str, Any]) -> dict[str, Any]:
    matches = [score_topic(topic, paper) for topic in topics]
    best = max(matches, key=lambda item: item["score"])
    output = dict(paper)
    output["best_match"] = best
    output["matches"] = sorted(matches, key=lambda item: item["score"], reverse=True)
    return output


def basic_summary(paper: dict[str, Any], best_match: dict[str, Any]) -> dict[str, str]:
    abstract = normalize_space(paper.get("summary"))
    excerpt = abstract[:520] + ("…" if len(abstract) > 520 else "")
    unavailable = "来源未提供摘要，建议打开原文核对研究设计与结论。"
    return {
        "problem": excerpt or unavailable,
        "method": "请根据原文的方法部分确认实验模型、样本、处理方式和统计设计。",
        "innovation": "自动基础模式不推断创新点；请结合全文判断。",
        "evidence": "自动基础模式不推断证据强度；请核对结果、图表与补充材料。",
        "limitations": "当前仅依据题录和可用摘要，不能替代全文阅读或人工证据评价。",
        "why_relevant": best_match.get("reason", ""),
    }


def ai_enabled() -> bool:
    return bool(os.getenv("LLM_API_KEY", "").strip())


def ai_provider_name() -> str:
    configured = os.getenv("LLM_PROVIDER_NAME", "").strip()
    if configured:
        return configured
    base_url = os.getenv("LLM_BASE_URL", "").lower()
    if "bigmodel.cn" in base_url:
        return "智谱 GLM"
    if "generativelanguage.googleapis.com" in base_url:
        return "Gemini"
    return "AI"


SUMMARY_FIELDS = ("problem", "method", "innovation", "evidence", "limitations", "why_relevant")
SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        field: {"type": "string"}
        for field in SUMMARY_FIELDS
    },
    "required": list(SUMMARY_FIELDS),
    "additionalProperties": False,
}


def parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if not match:
        raise ValueError("model response did not contain a JSON object")
    return json.loads(match.group(0))


def build_summary_prompt(topic: Topic, paper: dict[str, Any]) -> str:
    return f"""你是一名生物医学文献编辑。只根据下列题录和摘要，用中文返回严格 JSON。
字段必须是 problem、method、innovation、evidence、limitations、why_relevant；每个值是一段简洁文字。
不得补造摘要中没有的实验、数字或因果结论。缺失信息应明确写“摘要未说明”。

研究方向：{topic.name}
方向说明：{topic.description}
论文标题：{paper.get('title', '')}
作者：{', '.join(paper.get('authors') or [])}
摘要：{paper.get('summary') or '来源未提供摘要'}
"""


def call_gemini_native(prompt: str, api_key: str, base_url: str, model: str) -> dict[str, Any]:
    api_root = base_url.split("/openai", 1)[0].rstrip("/")
    endpoint = f"{api_root}/models/{urllib.parse.quote(model, safe='')}:generateContent"
    current_payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "responseFormat": {
                "text": {
                    "mimeType": "application/json",
                    "schema": SUMMARY_SCHEMA,
                }
            },
        },
    }
    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
    try:
        data = request_json(
            endpoint,
            headers=headers,
            data=json.dumps(current_payload).encode("utf-8"),
            timeout=float(os.getenv("LLM_TIMEOUT_SECONDS", "90")),
        )
    except APIRequestError as exc:
        if exc.status != 400:
            raise
        legacy_payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
                "responseSchema": SUMMARY_SCHEMA,
            },
        }
        data = request_json(
            endpoint,
            headers=headers,
            data=json.dumps(legacy_payload).encode("utf-8"),
            timeout=float(os.getenv("LLM_TIMEOUT_SECONDS", "90")),
        )
    parts = data["candidates"][0]["content"]["parts"]
    content = "".join(str(part.get("text") or "") for part in parts)
    return parse_json_object(content)


def call_openai_compatible(prompt: str, api_key: str, base_url: str, model: str) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    data = request_json(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        data=json.dumps(payload).encode("utf-8"),
        timeout=float(os.getenv("LLM_TIMEOUT_SECONDS", "90")),
    )
    content = data["choices"][0]["message"]["content"]
    return parse_json_object(content)


def summarize_with_ai(topic: Topic, paper: dict[str, Any]) -> dict[str, str]:
    api_key = os.getenv("LLM_API_KEY", "").strip()
    base_url = os.getenv("LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4").rstrip("/")
    model = os.getenv("LLM_MODEL", "glm-4-flash-250414")
    prompt = build_summary_prompt(topic, paper)
    request_delay = max(0.0, float(os.getenv("LLM_REQUEST_DELAY_SECONDS", "0")))
    if request_delay:
        time.sleep(request_delay)
    retries = max(1, int(os.getenv("LLM_RETRIES", "2")))
    retry_base = max(1.0, float(os.getenv("LLM_RETRY_BASE_SECONDS", "15")))
    for attempt in range(retries):
        try:
            if "generativelanguage.googleapis.com" in base_url:
                result = call_gemini_native(prompt, api_key, base_url, model)
            else:
                result = call_openai_compatible(prompt, api_key, base_url, model)
            return {
                field: normalize_space(result.get(field)) or "摘要未说明。"
                for field in SUMMARY_FIELDS
            }
        except APIRequestError as exc:
            retryable = exc.status == 429 or 500 <= exc.status < 600
            if not retryable or attempt == retries - 1:
                raise
            time.sleep(exc.retry_after or retry_base * (2**attempt))
    raise RuntimeError("AI summary request failed")


def paper_activity(paper: dict[str, Any]) -> dt.datetime | None:
    return parse_datetime(paper.get("updated")) or parse_datetime(paper.get("published"))


def within_days(paper: dict[str, Any], now: dt.datetime, days: int) -> bool:
    activity = paper_activity(paper)
    return bool(activity and activity >= now - dt.timedelta(days=max(days, 1)))


def collect(
    config_path: Path,
    output_path: Path,
    *,
    lookback_days: int,
    max_per_topic: int,
    max_summaries: int,
    clear_cache: bool,
    journal_metrics_path: Path = DEFAULT_JOURNAL_METRICS,
) -> dict[str, Any]:
    now = utc_now()
    repository_config = read_json(config_path, {})
    config, config_source = issue_config(repository_config)
    sources, topics = parse_config(config)
    journal_settings, journal_index = load_journal_metrics(journal_metrics_path)
    allowed_sources = {
        value.strip().lower()
        for value in os.getenv("PAPER_SOURCES", "").split(",")
        if value.strip()
    }
    if allowed_sources:
        sources = [source for source in sources if source.type.lower() in allowed_sources]

    previous = {} if clear_cache else read_json(output_path, {})
    previous_papers = previous.get("papers", []) if isinstance(previous, dict) else []
    previous_by_key = {canonical_key(paper): paper for paper in previous_papers}
    fetched: list[dict[str, Any]] = []
    source_stats: list[dict[str, Any]] = []
    delay = max(0.0, float(os.getenv("SOURCE_DELAY_SECONDS", "1")))

    for source_index, source in enumerate(sources):
        fetcher = SOURCE_FETCHERS.get(source.type.lower())
        if not fetcher:
            source_stats.append({"source": source.name, "status": "unsupported", "fetched": 0})
            continue
        source_count = 0
        failures = []
        for topic_index, topic in enumerate(topics):
            if source_index + topic_index > 0 and delay:
                time.sleep(delay)
            try:
                papers = fetcher(topic, max_per_topic)
                fetched.extend(papers)
                source_count += len(papers)
            except Exception as exc:
                failures.append(f"{topic.name}: {exc}")
                print(f"Warning: {source.name} failed for {topic.name}: {exc}", file=sys.stderr)
        source_stats.append(
            {
                "source": source.name,
                "status": "partial" if failures and source_count else "failed" if failures else "ok",
                "fetched": source_count,
                "errors": failures,
            }
        )

    scored = [attach_best_match(topics, paper) for paper in deduplicate(fetched)]
    minimum_score = float(os.getenv("MIN_MATCH_SCORE", "0.12"))
    primary = [paper for paper in scored if paper["best_match"]["score"] >= minimum_score and within_days(paper, now, lookback_days)]
    minimum_daily = max(0, int(os.getenv("MIN_DAILY_PAPERS", "8")))
    if len(primary) < minimum_daily:
        backfill_days = max(lookback_days, int(os.getenv("DAILY_BACKFILL_DAYS", "14")))
        primary_keys = {canonical_key(paper) for paper in primary}
        backfill = [
            paper
            for paper in scored
            if canonical_key(paper) not in primary_keys
            and paper["best_match"]["score"] >= minimum_score
            and within_days(paper, now, backfill_days)
        ]
        backfill.sort(key=lambda item: (item["best_match"]["score"], paper_activity(item) or dt.datetime.min.replace(tzinfo=UTC)), reverse=True)
        primary.extend(backfill[: max(0, minimum_daily - len(primary))])

    seen_at = now.isoformat()
    candidates = []
    for paper in primary:
        key = canonical_key(paper)
        prior = previous_by_key.get(key)
        if prior:
            paper = merge_paper(prior, paper)
        paper["first_seen_at"] = (prior or {}).get("first_seen_at") or seen_at
        paper["last_seen_at"] = seen_at
        paper["chinese_summary"] = (prior or {}).get("chinese_summary") or basic_summary(paper, paper["best_match"])
        paper["summary_engine"] = (prior or {}).get("summary_engine") or "basic"
        candidates.append(paper)

    new_limit = max(1, int(os.getenv("MAX_NEW_PAPERS", "50")))
    candidates.sort(
        key=lambda item: (item["best_match"]["score"], paper_activity(item) or dt.datetime.min.replace(tzinfo=UTC)),
        reverse=True,
    )
    candidates = candidates[:new_limit]

    retained = []
    candidate_keys = {canonical_key(paper) for paper in candidates}
    history_days = max(1, int(os.getenv("RECENT_HISTORY_DAYS", "45")))
    for paper in previous_papers:
        if canonical_key(paper) in candidate_keys:
            continue
        last_seen = parse_datetime(paper.get("last_seen_at") or paper.get("first_seen_at"))
        level = str((paper.get("best_match") or {}).get("level", "low"))
        if level in {"high", "medium"} or (last_seen and last_seen >= now - dt.timedelta(days=history_days)):
            retained.append(paper)

    papers = candidates + retained
    papers.sort(
        key=lambda item: (
            parse_datetime(item.get("last_seen_at")) or dt.datetime.min.replace(tzinfo=UTC),
            float((item.get("best_match") or {}).get("score", 0)),
        ),
        reverse=True,
    )
    papers = papers[: max(1, int(os.getenv("MAX_STORED_PAPERS", "50")))]
    for paper in papers:
        paper["journal_profile"] = build_journal_profile(paper, journal_settings, journal_index)

    jobs: list[tuple[int, Topic, dict[str, Any]]] = []
    topics_by_id = {topic.id: topic for topic in topics}
    if ai_enabled():
        for index, paper in enumerate(papers):
            key = canonical_key(paper)
            prior = previous_by_key.get(key, {})
            if prior.get("chinese_summary") and prior.get("summary_engine") == "ai":
                continue
            topic = topics_by_id.get((paper.get("best_match") or {}).get("topic_id"))
            if topic:
                jobs.append((index, topic, paper))
            if len(jobs) >= max_summaries:
                break

    summary_attempted = len(jobs)
    summary_succeeded = 0
    summary_failed = 0
    summary_last_error = ""
    if jobs:
        concurrency = max(1, int(os.getenv("LLM_CONCURRENCY", "1")))
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {
                executor.submit(summarize_with_ai, topic, paper): index
                for index, topic, paper in jobs
            }
            for future, index in list(futures.items()):
                try:
                    papers[index]["chinese_summary"] = future.result()
                    papers[index]["summary_engine"] = "ai"
                    papers[index]["summary_provider"] = ai_provider_name()
                    summary_succeeded += 1
                except Exception as exc:
                    print(f"Warning: AI summary failed for {papers[index].get('id')}: {exc}", file=sys.stderr)
                    papers[index]["summary_engine"] = "basic"
                    summary_failed += 1
                    summary_last_error = normalize_space(str(exc))[:240]

    ai_summary_count = sum(1 for paper in papers if paper.get("summary_engine") == "ai")
    basic_summary_count = len(papers) - ai_summary_count

    topic_payload = [dataclasses.asdict(topic) for topic in topics]
    payload = {
        "generated_at": email.utils.format_datetime(now),
        "generated_at_iso": now.isoformat(),
        "config_source": config_source,
        "data_kind": "selenium_mechanism",
        "topics": topic_payload,
        "papers": papers,
        "stats": {
            "collection_mode": "fresh" if clear_cache or not previous_papers else "incremental",
            "ai_summary_enabled": ai_enabled(),
            "ai_provider": ai_provider_name(),
            "ai_summary_count": ai_summary_count,
            "basic_summary_count": basic_summary_count,
            "ai_summary_attempted": summary_attempted,
            "ai_summary_succeeded": summary_succeeded,
            "ai_summary_failed": summary_failed,
            "ai_summary_last_error": summary_last_error,
            "paper_count": len(papers),
            "new_or_refreshed_count": len(candidates),
            "journal_metric_name": journal_settings["metric_name"],
            "journal_metric_year": journal_settings["metric_year"],
            "journal_quartile_system": journal_settings["quartile_system"],
            "journal_metric_source": journal_settings["source_url"],
            "journal_metric_note": journal_settings["note"],
            "source_stats": source_stats,
        },
    }
    write_json(output_path, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect selenium-mechanism literature for a static website.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--journal-metrics", type=Path, default=DEFAULT_JOURNAL_METRICS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--lookback-days", type=int, default=int(os.getenv("LOOKBACK_DAYS", "7")))
    parser.add_argument("--max-per-topic", type=int, default=int(os.getenv("MAX_PER_TOPIC", "10")))
    parser.add_argument("--max-summaries", type=int, default=int(os.getenv("MAX_SUMMARIES", "20")))
    parser.add_argument("--clear-cache", action="store_true", default=env_flag("CLEAR_PAPER_CACHE", False))
    args = parser.parse_args()
    payload = collect(
        args.config,
        args.output,
        lookback_days=max(1, args.lookback_days),
        max_per_topic=max(1, args.max_per_topic),
        max_summaries=max(0, args.max_summaries),
        clear_cache=args.clear_cache,
        journal_metrics_path=args.journal_metrics,
    )
    print(f"Wrote {len(payload['papers'])} papers to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
