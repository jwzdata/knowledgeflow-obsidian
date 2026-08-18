"""Deterministic, file-backed knowledge inflow pipeline."""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import ssl
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

USER_AGENT = "KnowledgeFlow-Obsidian/1.1 (+https://github.com/jwzdata/knowledgeflow-obsidian)"
TRACKING_KEYS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid", "gclid"}
DETAIL_CONTAINER_TAGS = {"article", "main"}
DETAIL_SKIP_TAGS = {"script", "style", "svg", "noscript", "nav", "header", "footer", "aside", "form"}
DETAIL_SELECTOR_RE = re.compile(r"(?:article|main|content|detail|正文|正文内容|articlebody|mainbody|neirong)", re.I)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def today() -> str:
    return datetime.now().date().isoformat()


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text("utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", "utf-8")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]
    except FileNotFoundError:
        return []


def append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def save_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    """Atomically rewrite a JSONL ledger after deterministic enrichment."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), "utf-8")
    temporary.replace(path)


def canonical_url(value: str) -> str:
    value = html.unescape((value or "").strip())
    if not value.lower().startswith(("http://", "https://")):
        return ""
    parts = urllib.parse.urlsplit(value)
    query = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query) if k.lower() not in TRACKING_KEYS]
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    return urllib.parse.urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urllib.parse.urlencode(query), ""))


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "svg", "noscript"}:
            self.skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "svg", "noscript"} and self.skip:
            self.skip -= 1

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.parts.append(data)


def plain_text(value: str, limit: int = 1600) -> str:
    parser = _Text()
    try:
        parser.feed(value or "")
        value = " ".join(parser.parts)
    except Exception:
        value = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", html.unescape(value)).strip()[:limit]


class _DetailText(HTMLParser):
    """Extract readable text from likely article containers on HTML detail pages."""

    def __init__(self) -> None:
        super().__init__()
        self.candidate_depth = 0
        self.skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attrs_map = {key.lower(): value or "" for key, value in attrs}
        if self.candidate_depth:
            self.candidate_depth += 1
            if tag in DETAIL_SKIP_TAGS:
                self.skip_depth += 1
            return
        if tag in DETAIL_SKIP_TAGS:
            self.skip_depth += 1
            return
        marker = " ".join((attrs_map.get("id", ""), attrs_map.get("class", "")))
        if tag in DETAIL_CONTAINER_TAGS or DETAIL_SELECTOR_RE.search(marker):
            self.candidate_depth = 1

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self.skip_depth and tag in DETAIL_SKIP_TAGS:
            self.skip_depth -= 1
        if self.candidate_depth:
            self.candidate_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.candidate_depth and not self.skip_depth:
            text = re.sub(r"\s+", " ", html.unescape(data)).strip()
            if text:
                self.parts.append(text)


def extract_detail_summary(payload: str | bytes, limit: int = 1600) -> str:
    """Return a bounded article-body summary without navigation or scripts."""

    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", errors="ignore")
    parser = _DetailText()
    try:
        parser.feed(payload or "")
        parser.close()
    except Exception:
        return ""
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()[:limit]


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child_text(node: ET.Element, names: set[str]) -> str:
    for child in node:
        if _local(str(child.tag)) in names and child.text:
            return child.text.strip()
    return ""


def parse_feed(payload: bytes, base_url: str = "") -> list[dict[str, str]]:
    root = ET.fromstring(payload)
    rows: list[dict[str, str]] = []
    for node in root.iter():
        kind = _local(str(node.tag))
        if kind not in {"item", "entry"}:
            continue
        link = _child_text(node, {"link", "guid"})
        if kind == "entry":
            for child in node:
                if _local(str(child.tag)) == "link" and child.attrib.get("href"):
                    if child.attrib.get("rel", "alternate") == "alternate":
                        link = child.attrib["href"]
                        break
        rows.append({
            "title": plain_text(_child_text(node, {"title"}), 260),
            "url": canonical_url(urllib.parse.urljoin(base_url, link)),
            "summary": plain_text(_child_text(node, {"description", "summary", "content", "encoded"})),
            "published_at": _child_text(node, {"pubdate", "published", "updated", "date"}),
        })
    return rows


def normalized_date(value: str) -> str:
    if not value:
        return ""
    try:
        dt = parsedate_to_datetime(value)
        return dt.date().isoformat()
    except (TypeError, ValueError, OverflowError):
        pass
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        match = re.search(r"20\d{2}-\d{2}-\d{2}", value)
        return match.group(0) if match else ""


def slug(value: str, limit: int = 64) -> str:
    value = re.sub(r"[\\/:*?\"<>|#^\[\]]", "-", plain_text(value, limit))
    value = re.sub(r"\s+", "-", value).strip("-. ")
    return value[:limit] or "untitled"


def keyword_matches(haystack: str, keyword: str) -> bool:
    """Match short ASCII keywords as tokens; use phrases/substrings otherwise."""
    haystack = haystack.casefold()
    keyword = keyword.casefold().strip()
    if not keyword:
        return False
    if len(keyword) <= 3 and keyword.isascii() and keyword.isalnum():
        return re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", haystack) is not None
    return keyword in haystack


@dataclass
class Store:
    vault: Path

    @property
    def flow(self) -> Path:
        return self.vault / ".knowledgeflow"

    @property
    def config_file(self) -> Path:
        return self.flow / "config.json"

    @property
    def data(self) -> Path:
        return self.flow / "data"

    def config(self) -> dict[str, Any]:
        config = load_json(self.config_file, {})
        if not config.get("sources") or not config.get("topics"):
            raise ValueError(f"Invalid or missing config: {self.config_file}")
        return config


def _fetch(url: str, timeout: int = 25, *, accept: str = "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9") -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    with urllib.request.urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
        return response.read(4_000_000)


def fetch_detail_summary(url: str, timeout: int = 15, limit: int = 1600) -> str:
    """Best-effort extraction from an item's official HTML page.

    Detail fetches are deliberately non-fatal.  A feed item remains usable as
    a source card even when its page blocks automation or changes markup.
    """

    try:
        payload = _fetch(url, timeout=timeout, accept="text/html, application/xhtml+xml;q=0.9")
    except Exception:
        return ""
    return extract_detail_summary(payload, limit=limit)


def _detail_fallback_enabled(source: dict[str, Any]) -> bool:
    return bool(source.get("detail_fallback", source.get("kind") in {"html", "html_detail"}))


def _enrich_item_summary(item: dict[str, str], source: dict[str, Any], config: dict[str, Any]) -> tuple[dict[str, str], str]:
    policy = config.get("policy", {})
    minimum = int(policy.get("detail_fallback_min_summary_chars", 80))
    if not _detail_fallback_enabled(source) or len(item.get("summary", "")) >= minimum:
        return item, "not-needed"
    summary = fetch_detail_summary(
        item.get("url", ""),
        timeout=int(policy.get("detail_fallback_timeout", 15)),
        limit=int(policy.get("detail_fallback_summary_limit", 1600)),
    )
    if not summary:
        return item, "failed"
    enriched = dict(item)
    enriched["summary"] = summary
    enriched["detail_fallback"] = "true"
    topic, hits = _topic_for(enriched, source, config)
    enriched["topic_id"] = topic["id"]
    enriched["topic_title"] = topic["title"]
    enriched["topic_directory"] = topic["directory"]
    enriched["quality"] = score_item(enriched, source, hits, config)
    return enriched, "enriched"


def _topic_for(item: dict[str, str], source: dict[str, Any], config: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    haystack = f"{item.get('title', '')} {item.get('summary', '')}".casefold()
    allowed = set(source.get("topics", []))
    best: tuple[int, dict[str, Any], list[str]] | None = None
    fallback = config["topics"][-1]
    for topic in config["topics"]:
        keywords = [word for word in topic.get("keywords", []) if keyword_matches(haystack, word)]
        if allowed and topic["id"] not in allowed:
            continue
        rank = len(keywords)
        if best is None or rank > best[0]:
            best = (rank, topic, keywords)
    if best and (best[0] or best[1]["id"] in allowed):
        return best[1], best[2]
    return fallback, []


def score_item(item: dict[str, str], source: dict[str, Any], keyword_hits: list[str], config: dict[str, Any]) -> dict[str, Any]:
    tier = source.get("tier", "C").upper()
    authority = {"A": 100, "B": 82, "C": 65}.get(tier, 50)
    summary_len = len(item.get("summary", ""))
    structured = min(100, 35 + summary_len / 2) if item.get("url") and item.get("title") else 20
    relevance = min(100, 55 + len(keyword_hits) * 12) if keyword_hits else (72 if source.get("topics") else 45)
    published = normalized_date(item.get("published_at", ""))
    freshness = 65
    if published:
        try:
            age = max(0, (datetime.now().date() - datetime.fromisoformat(published).date()).days)
            max_age = int(config["policy"].get("max_age_days", 730))
            freshness = max(0, round(100 * (1 - min(age, max_age) / max_age), 1))
        except ValueError:
            pass
    overall = round(authority * 0.35 + relevance * 0.30 + freshness * 0.20 + structured * 0.15, 1)
    return {"overall": overall, "authority": authority, "relevance": round(relevance, 1), "freshness": freshness, "structured": round(structured, 1), "keyword_hits": keyword_hits}


def sync(store: Store, *, offline: bool = False) -> dict[str, Any]:
    config = store.config()
    existing = load_jsonl(store.data / "candidates.jsonl")
    seen = {row.get("id") for row in existing}
    new_rows: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    detail_fallbacks = 0
    detail_failures = 0
    for source in config["sources"]:
        if not source.get("active", True):
            continue
        result = {"source_id": source["id"], "title": source["title"], "status": "offline" if offline else "pending", "new": 0}
        if offline:
            results.append(result)
            continue
        try:
            items = parse_feed(_fetch(source["url"]), source["url"])
            limit = int(config["policy"].get("max_items_per_source", 8))
            for item in items[: max(20, limit * 5)]:
                url = item.get("url", "")
                if not url or not item.get("title"):
                    continue
                candidate_id = "ki-" + hashlib.sha256(url.encode()).hexdigest()[:16]
                if candidate_id in seen:
                    continue
                item, detail_status = _enrich_item_summary(item, source, config)
                if detail_status == "enriched":
                    detail_fallbacks += 1
                elif detail_status == "failed":
                    detail_failures += 1
                topic, hits = _topic_for(item, source, config)
                quality = score_item(item, source, hits, config)
                row = {
                    "id": candidate_id,
                    "status": "pending",
                    "title": item["title"],
                    "url": url,
                    "summary": item.get("summary", ""),
                    "published_at": normalized_date(item.get("published_at", "")),
                    "discovered_at": utc_now(),
                    "source_id": source["id"],
                    "source_title": source["title"],
                    "source_authority": source["authority"],
                    "source_tier": source.get("tier", "C"),
                    "topic_id": topic["id"],
                    "topic_title": topic["title"],
                    "topic_directory": topic["directory"],
                    "tags": source.get("tags", []),
                    "quality": quality,
                }
                new_rows.append(row)
                seen.add(candidate_id)
                result["new"] += 1
                if result["new"] >= limit:
                    break
            result.update({"status": "ok", "items": len(items)})
        except Exception as exc:
            result.update({"status": "error", "error": f"{type(exc).__name__}: {exc}"[:300]})
        results.append(result)
    append_jsonl(store.data / "candidates.jsonl", new_rows)
    report = {
        "ran_at": utc_now(),
        "offline": offline,
        "sources": len(results),
        "source_errors": sum(r["status"] == "error" for r in results),
        "new_candidates": len(new_rows),
        "detail_fallbacks": detail_fallbacks,
        "detail_failures": detail_failures,
        "results": results,
    }
    save_json(store.data / "sync_latest.json", report)
    return report


def _decisions(store: Store) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in load_jsonl(store.data / "decisions.jsonl"):
        latest[row["candidate_id"]] = row
    return latest


def _next_number(directory: Path) -> int:
    numbers = []
    for path in directory.glob("*.md"):
        match = re.match(r"(\d{3})-", path.name)
        if match:
            numbers.append(int(match.group(1)))
    return max(numbers, default=0) + 1


def _yaml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def render_note(candidate: dict[str, Any], number: int) -> str:
    stamp = candidate.get("published_at") or today()
    title = candidate["title"]
    summary = candidate.get("summary") or "订阅源未提供摘要，请打开原文核验后再引用。"
    quality = candidate["quality"]
    tags = list(dict.fromkeys([*candidate.get("tags", []), "自动入库", "来源卡", candidate["topic_id"]]))
    return f'''---
id: "kf-{candidate['id'].removeprefix('ki-')}"
title: {_yaml_string(f'[{stamp}] {title}')}
summary: {_yaml_string(summary[:280])}
type: "reference"
status: "published"
created: "{today()}"
updated: "{today()}"
content_updated: "{stamp}"
source_type: "curated"
source_coverage: "source-card"
verification: "automated-source-only"
content_level: "summary"
ingestion_mode: "auto"
auto_ingested: true
auto_quality_score: {quality['overall']}
review_status: "unreviewed"
knowledge_status: "evidence-only"
candidate_id: "{candidate['id']}"
source_feed: "{candidate['source_id']}"
tags: {json.dumps(tags, ensure_ascii=False)}
sources: [{_yaml_string(candidate['url'])}]
---

# [{stamp}] {title}

> [!WARNING] 自动入库 · 待抽检
> 本文由固定来源自动筛选并归档，属于“来源陈述”而非独立事实确认。引用数据、因果或预测前，请打开原文复核。

## 核心摘要

{summary}

## 为什么进入知识库

- 主题路由：[[00-知识地图|{candidate['topic_title']}]]
- 来源级别：{candidate['source_tier']}；发布主体：{candidate['source_authority']}
- 综合质量分：**{quality['overall']} / 100**
- 命中词：{', '.join(quality.get('keyword_hits', [])) or '固定窄领域来源'}

## 证据边界

- 当前只确认该来源发布了上述内容，尚未逐条验证其方法、数据口径与外部有效性。
- 若形成长期知识，应补充至少一个独立来源，并将 `review_status` 改为 `reviewed`。
- 内容价值不足时可直接删除；候选 ID 已记录，系统不会重复生成。

## 原始来源

- 原文：[{title}]({candidate['url']})
- 来源栏目：{candidate['source_title']}
- 发布日期：{candidate.get('published_at') or '订阅源未提供'}
- 自动发现：{candidate['discovered_at']}
- 候选 ID：`{candidate['id']}`
'''


def promote(store: Store, *, dry_run: bool = False, retry_rejected: bool = False) -> dict[str, Any]:
    config = store.config()
    policy = config["policy"]
    min_score = float(policy.get("min_score", 68))
    min_summary = int(policy.get("min_summary_chars", 60))
    decisions = _decisions(store)
    sources = {source["id"]: source for source in config["sources"]}
    candidate_rows = load_jsonl(store.data / "candidates.jsonl")
    candidates: list[dict[str, Any]] = []
    retry_events: list[dict[str, Any]] = []
    changed_candidates = False
    for row in candidate_rows:
        prior = decisions.get(row["id"])
        if prior is None:
            candidates.append(row)
            continue
        if not retry_rejected or prior.get("decision") != "rejected":
            continue
        source = sources.get(row.get("source_id"), {})
        enriched, detail_status = _enrich_item_summary(row, source, config)
        if detail_status == "enriched":
            candidates.append(enriched)
            retry_events.append({"candidate_id": row["id"], "decision": "requeued", "mode": "auto-retry", "reason": "自动补抓详情页摘要后重试", "decided_at": utc_now()})
            candidate_rows[candidate_rows.index(row)] = enriched
            changed_candidates = True
    candidates.sort(key=lambda row: row.get("quality", {}).get("overall", 0), reverse=True)
    limit = int(policy.get("max_promotions_per_run", 24))
    promoted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    decision_rows: list[dict[str, Any]] = [*retry_events]
    next_numbers: dict[str, int] = {}
    for candidate in candidates:
        reasons = []
        if float(candidate["quality"].get("overall", 0)) < min_score:
            reasons.append(f"score<{min_score:g}")
        if len(candidate.get("summary", "")) < min_summary:
            reasons.append(f"summary<{min_summary}")
        source = sources.get(candidate.get("source_id"), {})
        if source.get("require_keyword") and not candidate.get("quality", {}).get("keyword_hits"):
            reasons.append("required-topic-keyword-missing")
        if reasons:
            rejected.append({"id": candidate["id"], "title": candidate["title"], "reasons": reasons})
            decision_rows.append({"candidate_id": candidate["id"], "decision": "rejected", "reason": ",".join(reasons), "decided_at": utc_now()})
            continue
        if len(promoted) >= limit:
            continue
        directory = store.vault / candidate["topic_directory"]
        directory.mkdir(parents=True, exist_ok=True)
        directory_key = directory.as_posix()
        if directory_key not in next_numbers:
            next_numbers[directory_key] = _next_number(directory)
        number = next_numbers[directory_key]
        next_numbers[directory_key] += 1
        stamp = candidate.get("published_at") or today()
        relative = Path(candidate["topic_directory"]) / f"{number:03d}-{stamp}-{slug(candidate['title'])}.md"
        if not dry_run:
            (store.vault / relative).write_text(render_note(candidate, number), "utf-8")
        promoted.append({"id": candidate["id"], "title": candidate["title"], "path": relative.as_posix(), "score": candidate["quality"]["overall"]})
        decision_rows.append({"candidate_id": candidate["id"], "decision": "published", "path": relative.as_posix(), "decided_at": utc_now()})
    if not dry_run:
        if changed_candidates:
            save_jsonl(store.data / "candidates.jsonl", candidate_rows)
        append_jsonl(store.data / "decisions.jsonl", decision_rows)
    report = {
        "ran_at": utc_now(),
        "dry_run": dry_run,
        "retry_rejected": retry_rejected,
        "requeued": len(retry_events),
        "promoted": len(promoted),
        "rejected": len(rejected),
        "deferred": max(0, len(candidates) - len(promoted) - len(rejected)),
        "items": promoted,
        "rejected_items": rejected,
    }
    if not dry_run:
        save_json(store.data / "promote_latest.json", report)
    return report


def render_dashboard(store: Store) -> dict[str, Any]:
    config = store.config()
    candidates = load_jsonl(store.data / "candidates.jsonl")
    decisions = _decisions(store)
    published = [row for row in decisions.values() if row.get("decision") == "published"]
    rejected = [row for row in decisions.values() if row.get("decision") == "rejected"]
    pending = [row for row in candidates if row["id"] not in decisions]
    sync_report = load_json(store.data / "sync_latest.json", {})
    lines = [
        "---", "type: dashboard", f'updated: "{today()}"', "---", "", "# 知识流入流水线", "",
        "> [!INFO] 使用方式", "> 点击左侧丝带的 **KnowledgeFlow** 图标，或在终端运行 `./kb.sh run`。自动文章直接进入对应主题目录，并保留来源与删除防回流标记。", "",
        "## 当前状态", "",
        f"- 候选总数：**{len(candidates)}**", f"- 待处理：**{len(pending)}**", f"- 已自动入库：**{len(published)}**", f"- 已过滤：**{len(rejected)}**", f"- 来源异常：**{sync_report.get('source_errors', 0)}**", "",
        "## 最近自动入库", "",
    ]
    recent = list(reversed(published[-20:]))
    lines.extend([f"- [[{row['path'][:-3]}]]" for row in recent] or ["- 暂无。运行一次流水线后会出现在这里。"])
    lines += ["", "## 待处理候选", ""]
    lines.extend([f"- **{row['quality']['overall']}** · [{row['title']}]({row['url']}) · `{row['id']}`" for row in pending[:30]] or ["- 无待处理候选。"])
    lines += ["", "## 固定来源", ""]
    lines.extend([f"- **{s['title']}** · {s['tier']} 级 · {'启用' if s.get('active', True) else '停用'} · [主页]({s.get('homepage', s['url'])})" for s in config["sources"]])
    target = store.vault / config["inbox_note"]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", "utf-8")
    status = {"updated_at": utc_now(), "candidates": len(candidates), "pending": len(pending), "published": len(published), "rejected": len(rejected), "source_errors": sync_report.get("source_errors", 0), "inbox_note": config["inbox_note"]}
    save_json(store.data / "status.json", status)
    return status


def health(store: Store) -> dict[str, Any]:
    config = store.config()
    errors: list[str] = []
    generated = 0
    for path in store.vault.rglob("*.md"):
        if any(part.startswith(".") for part in path.relative_to(store.vault).parts):
            continue
        text = path.read_text("utf-8")
        if "auto_ingested: true" not in text:
            continue
        generated += 1
        for field in ("candidate_id:", "sources:", "review_status:", "verification:"):
            if field not in text:
                errors.append(f"{path.relative_to(store.vault)} missing {field[:-1]}")
    status = load_json(store.data / "status.json", {})
    report = {"checked_at": utc_now(), "healthy": not errors, "generated_notes": generated, "metadata_errors": errors, "source_errors": status.get("source_errors", 0)}
    save_json(store.data / "health_latest.json", report)
    return report


def run(store: Store, *, offline: bool = False, retry_rejected: bool = False) -> dict[str, Any]:
    sync_report = sync(store, offline=offline)
    promote_report = promote(store, retry_rejected=retry_rejected)
    dashboard = render_dashboard(store)
    health_report = health(store)
    report = {"ran_at": utc_now(), "sync": sync_report, "promote": promote_report, "dashboard": dashboard, "health": health_report}
    save_json(store.data / "run_latest.json", report)
    return report
