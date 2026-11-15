"""AI-native agent tools for KnowledgeFlow Obsidian.

Zero-dependency implementation of:
- Quality-aware hybrid BM25 + bilingual synonym search (`search_vault`)
- Character/token-bounded evidence packing (`context_pack`)
- Adversarial proposal review against ADRs and compliance/risk rules (`challenge_proposal`)
- Conservative cross-folder entity linking (`crosslink_vault`)
- Non-hub semantic graph analysis and single-read hot cache (`build_hot_cache`)
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .pipeline import Store, load_json, today


def _load_config(store: Store) -> dict[str, Any]:
    """Read vault config permissively so agent tools also work before feeds are configured."""
    return load_json(store.config_file, {})

DEFAULT_SYNONYMS: list[tuple[list[str], list[str]]] = [
    (["碳关税", "碳边境", "碳边境调节"], ["cbam", "carbon"]),
    (["大模型", "大语言模型"], ["llm", "gpt", "agent"]),
    (["智能体", "多智能体"], ["agent", "agents", "agentic"]),
    (["检索增强", "知识检索"], ["rag", "bm25", "search"]),
    (["利率互换", "利率掉期", "货币政策"], ["irs", "monetary", "fomc"]),
    (["主数据", "数据治理"], ["mdm", "schema"]),
    (["架构决策", "决策记录"], ["adr", "architecture"]),
    (["零信任", "供应链安全"], ["zero-trust", "security"]),
]

DEFAULT_RISK_PREFIXES = (
    "10-知识库/03-架构决策/",
    "10-知识库/04-合规与风险/",
    "13-项目决策记录/",
    "14-合规制度/",
)

RISK_KEYWORDS = (
    "红线",
    "风控",
    "合规",
    "决策",
    "约束",
    "禁止",
    "反例",
    "失效",
    "隔离",
    "待核验",
    "warning",
    "risk",
    "constraint",
    "adr",
)

STOP_TOKENS = {
    "如何",
    "什么",
    "哪些",
    "是否",
    "怎么",
    "可以",
    "这个",
    "一个",
    "以及",
    "进行",
    "需要",
    "the",
    "and",
    "for",
    "with",
    "this",
    "that",
    "from",
}

EXCLUDE_TOP_DIRS = {".obsidian", ".knowledgeflow", ".git", ".venv", "src", "tests", "docs", "examples"}
EXCLUDE_ROOT_DOCS = {"README.md", "CHANGELOG.md", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md", "SECURITY.md", "LICENSE"}


def split_frontmatter(text: str) -> tuple[str, str]:
    """Split YAML frontmatter block and markdown body cleanly."""
    if not text.startswith("---\n"):
        return "", text
    end = text.find("\n---\n", 4)
    if end == -1:
        if text.endswith("\n---"):
            return text[4:-4], ""
        return "", text
    return text[4:end], text[end + 5 :]


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def parse_fields(frontmatter: str) -> dict[str, Any]:
    """Parse lightweight YAML scalar and list fields without external dependencies."""
    fields: dict[str, Any] = {}
    if not frontmatter:
        return fields
    lines = frontmatter.splitlines()
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if not match:
            idx += 1
            continue
        key, raw_val = match.group(1), match.group(2).strip()
        if raw_val.startswith("[") and raw_val.endswith("]"):
            inner = raw_val[1:-1].strip()
            if not inner:
                fields[key] = []
            else:
                try:
                    parsed = json.loads(raw_val)
                    fields[key] = [str(item) for item in parsed] if isinstance(parsed, list) else [str(parsed)]
                except json.JSONDecodeError:
                    fields[key] = [_strip_quotes(part) for part in inner.split(",") if part.strip()]
            idx += 1
        elif raw_val == "":
            items: list[str] = []
            idx += 1
            while idx < len(lines) and re.match(r"^\s+-\s+", lines[idx]):
                item_text = re.sub(r"^\s+-\s+", "", lines[idx]).strip()
                items.append(_strip_quotes(item_text))
                idx += 1
            fields[key] = items
        else:
            if raw_val.lower() == "true":
                fields[key] = True
            elif raw_val.lower() == "false":
                fields[key] = False
            else:
                fields[key] = _strip_quotes(raw_val)
            idx += 1
    return fields


def replace_frontmatter_list(frontmatter: str, key: str, values: list[str]) -> str:
    """Insert or replace a YAML key with a JSON-formatted string list."""
    rendered = f"{key}: {json.dumps(values, ensure_ascii=False)}"
    lines = frontmatter.splitlines()
    out: list[str] = []
    idx = 0
    replaced = False
    while idx < len(lines):
        line = lines[idx]
        if re.match(rf"^{re.escape(key)}:\s*", line):
            out.append(rendered)
            replaced = True
            idx += 1
            while idx < len(lines) and re.match(r"^\s+-\s+", lines[idx]):
                idx += 1
            continue
        out.append(line)
        idx += 1
    if not replaced:
        out.append(rendered)
    return "\n".join(out)


def replace_frontmatter_scalar(frontmatter: str, key: str, value: str) -> str:
    """Insert or replace a scalar YAML string field."""
    rendered = f"{key}: {json.dumps(value, ensure_ascii=False)}"
    lines = frontmatter.splitlines()
    out: list[str] = []
    replaced = False
    for line in lines:
        if re.match(rf"^{re.escape(key)}:\s*", line):
            out.append(rendered)
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(rendered)
    return "\n".join(out)


def field_str(fields: dict[str, Any], key: str, default: str = "") -> str:
    val = fields.get(key, default)
    if isinstance(val, list):
        return ", ".join(str(x) for x in val)
    if isinstance(val, bool):
        return "true" if val else "false"
    return str(val) if val is not None else default


def field_list(fields: dict[str, Any], key: str) -> list[str]:
    val = fields.get(key)
    if isinstance(val, list):
        return [str(x) for x in val if str(x).strip()]
    if isinstance(val, str) and val.strip():
        return [val.strip()]
    return []


def iter_vault_markdown(vault: Path) -> list[Path]:
    """Iterate substantive and hub Markdown files inside a vault, excluding repo tooling files."""
    files: list[Path] = []
    for path in sorted(vault.rglob("*.md")):
        rel = path.relative_to(vault)
        parts = rel.parts
        if any(part.startswith(".") for part in parts):
            continue
        if parts[0] in EXCLUDE_TOP_DIRS:
            continue
        if len(parts) == 1 and path.name in EXCLUDE_ROOT_DOCS:
            continue
        files.append(path)
    return files


def is_bookkeeping(rel_path: str, fields: dict[str, Any]) -> bool:
    """Return True if a note is a navigation hub, dashboard, index, or template."""
    tp = field_str(fields, "type").lower()
    st = field_str(fields, "status").lower()
    src_type = field_str(fields, "source_type").lower()
    parts = Path(rel_path).parts
    name = Path(rel_path).name
    return (
        tp in {"index", "dashboard", "template", "moc"}
        or st in {"generated", "archived"}
        or src_type == "generated"
        or name.startswith("00-")
        or (len(parts) > 0 and parts[0] in {"00-模板", "00-导航", "20-知识流入"})
    )


def visible_title(rel_path: str, fields: dict[str, Any], body: str) -> str:
    title = field_str(fields, "title").strip()
    if title:
        return title
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return Path(rel_path).stem


def extract_snippet(body: str, query_tokens: list[str], limit: int = 240) -> str:
    clean = re.sub(r"```.*?```", " ", body, flags=re.DOTALL)
    clean = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", clean)
    clean = re.sub(r"\[\[([^\]]+)\]\]", r"\1", clean)
    lines = [re.sub(r"\s+", " ", line).strip() for line in clean.splitlines()]
    lines = [line for line in lines if line and not line.startswith("> [!") and line != "---"]
    for line in lines:
        low = line.lower()
        if any(tok in low for tok in query_tokens):
            return line[:limit]
    return " ".join(lines)[:limit]


def extract_tokens(text: str) -> list[str]:
    """Tokenize bilingual text into lowercase ASCII words and CJK unigrams/bigrams."""
    raw = re.findall(r"[A-Za-z0-9_+-]{2,}|[\u4e00-\u9fff]+", (text or "").lower())
    out: list[str] = []
    for item in raw:
        if item in STOP_TOKENS:
            continue
        if re.match(r"^[\u4e00-\u9fff]+$", item):
            if len(item) >= 2 and item not in out:
                out.append(item)
            for i in range(len(item) - 1):
                bg = item[i : i + 2]
                if bg not in STOP_TOKENS and bg not in out:
                    out.append(bg)
            if len(item) == 1 and item not in out:
                out.append(item)
        else:
            if item not in out:
                out.append(item)
    return out


def _synonym_groups(config: dict[str, Any]) -> list[tuple[list[str], list[str]]]:
    groups = list(DEFAULT_SYNONYMS)
    for item in config.get("synonyms", []):
        if isinstance(item, dict) and item.get("terms") and item.get("expansions"):
            groups.append(([str(x).lower() for x in item["terms"]], [str(x).lower() for x in item["expansions"]]))
    return groups


def expand_query_tokens(query: str, config: dict[str, Any]) -> list[tuple[str, float]]:
    """Return weighted tokens including discounted bilingual synonym expansions."""
    base_tokens = extract_tokens(query)
    if not base_tokens:
        return []
    weights: dict[str, float] = {tok: 1.0 for tok in base_tokens}
    lower_q = query.lower()
    for triggers, targets in _synonym_groups(config):
        hit_a = any(t in lower_q for t in triggers)
        hit_b = any(t in lower_q for t in targets)
        if hit_a:
            for exp in targets:
                for tok in extract_tokens(exp):
                    weights[tok] = max(weights.get(tok, 0.0), 0.72)
        if hit_b:
            for exp in triggers:
                for tok in extract_tokens(exp):
                    weights[tok] = max(weights.get(tok, 0.0), 0.72)
    return sorted(weights.items(), key=lambda pair: (-pair[1], pair[0]))


def _extract_wikilinks(text: str) -> list[str]:
    stripped = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    stripped = re.sub(r"`[^`\n]+`", "", stripped)
    return re.findall(r"\[\[([^\]]+)\]\]", stripped)


def resolve_wikilink(
    raw_target: str,
    source_rel: str,
    by_rel: dict[str, str],
    by_stem: dict[str, list[str]],
) -> str | None:
    """Resolve an Obsidian wikilink target string to a vault-relative Markdown path."""
    target = raw_target.split("|", 1)[0].split("#", 1)[0].strip()
    if not target or target.startswith("http") or "!" in target and target.endswith((".png", ".jpg", ".svg")):
        return None
    if re.search(r"\.(png|jpe?g|gif|svg|webp|pdf|base|csv|xlsx?)$", target, re.I):
        return None
    clean = target.removesuffix(".md").lstrip("./")
    if clean in by_rel:
        return by_rel[clean]
    parent_rel = Path(source_rel).parent.as_posix()
    if parent_rel and parent_rel != ".":
        joined = f"{parent_rel}/{clean}"
        if joined in by_rel:
            return by_rel[joined]
    stem = Path(clean).name
    matches = by_stem.get(stem, [])
    if len(matches) == 1:
        return matches[0]
    if matches:
        top = Path(source_rel).parts[0]
        same_top = [m for m in matches if Path(m).parts[0] == top]
        return same_top[0] if len(same_top) == 1 else matches[0]
    return None


def _build_graph_maps(vault: Path) -> tuple[dict[str, dict[str, Any]], dict[str, set[str]], dict[str, set[str]], int]:
    """Scan all vault markdown notes and build non-hub semantic connectivity maps."""
    paths = iter_vault_markdown(vault)
    notes: dict[str, dict[str, Any]] = {}
    by_rel: dict[str, str] = {}
    by_stem: dict[str, list[str]] = defaultdict(list)

    for path in paths:
        rel = path.relative_to(vault).as_posix()
        raw = path.read_text("utf-8", errors="ignore")
        fm, body = split_frontmatter(raw)
        fields = parse_fields(fm)
        stem = path.stem
        rel_no_ext = rel[:-3]
        by_rel[rel_no_ext] = rel
        by_rel[rel] = rel
        by_stem[stem].append(rel)
        notes[rel] = {
            "path": path,
            "rel": rel,
            "fields": fields,
            "fm": fm,
            "body": body,
            "title": visible_title(rel, fields, body),
            "summary": field_str(fields, "summary"),
            "status": field_str(fields, "status", "active"),
            "rag_priority": field_str(fields, "rag_priority", "primary"),
            "bookkeeping": is_bookkeeping(rel, fields),
        }

    sem_out: dict[str, set[str]] = defaultdict(set)
    sem_in: dict[str, set[str]] = defaultdict(set)
    for rel, info in notes.items():
        if info["bookkeeping"]:
            continue
        fields = info["fields"]
        links = _extract_wikilinks(info["body"]) + field_list(fields, "related")
        for raw_link in links:
            resolved = resolve_wikilink(raw_link, rel, by_rel, by_stem)
            if not resolved or resolved == rel or resolved not in notes:
                continue
            if notes[resolved]["bookkeeping"]:
                continue
            sem_out[rel].add(resolved)
            sem_in[resolved].add(rel)

    total_edges = sum(len(targets) for targets in sem_out.values())
    return notes, sem_out, sem_in, total_edges


def search_vault(store: Store, query: str, limit: int = 12) -> dict[str, Any]:
    """Run zero-dependency quality-aware BM25 + synonym search across the vault."""
    config = _load_config(store)
    weighted_terms = expand_query_tokens(query, config)
    if not weighted_terms:
        return {"query": query, "count": 0, "engine": "knowledgeflow-bm25-synonym-v2", "results": []}

    notes, _, _, _ = _build_graph_maps(store.vault)
    docs: list[dict[str, Any]] = []
    df: Counter[str] = Counter()

    for rel, info in notes.items():
        fields = info["fields"]
        status = info["status"].lower()
        rag_priority = info["rag_priority"].lower()
        if info["bookkeeping"]:
            continue
        if status in {"draft", "archived", "generated", "excluded"} or rag_priority == "excluded":
            continue

        title = info["title"]
        summary = info["summary"]
        tags_text = " ".join(field_list(fields, "tags") + field_list(fields, "aliases"))
        content = f"{title}\n{tags_text}\n{summary}\n{info['body'][:4000]}"
        toks = extract_tokens(content)
        if not toks:
            continue
        tf = Counter(toks)
        for unique_tok in tf:
            df[unique_tok] += 1
        docs.append({
            "rel": rel,
            "info": info,
            "tf": tf,
            "length": len(toks),
            "title_low": title.lower(),
            "tags_low": tags_text.lower(),
        })

    n_docs = len(docs)
    if n_docs == 0:
        return {"query": query, "count": 0, "engine": "knowledgeflow-bm25-synonym-v2", "results": []}

    avg_dl = sum(d["length"] for d in docs) / n_docs
    k1, b = 1.4, 0.7
    lower_q = query.lower().strip()
    query_tok_list = [tok for tok, _ in weighted_terms]

    scored: list[dict[str, Any]] = []
    for doc in docs:
        bm25 = 0.0
        matched_base = 0
        for tok, weight in weighted_terms:
            freq = doc["tf"].get(tok, 0)
            if not freq:
                continue
            if weight >= 0.99:
                matched_base += 1
            idf = math.log(1.0 + (n_docs - df[tok] + 0.5) / (df[tok] + 0.5))
            denom = freq + k1 * (1.0 - b + b * (doc["length"] / avg_dl))
            bm25 += weight * idf * ((freq * (k1 + 1.0)) / denom)

        if bm25 <= 0.0:
            continue

        score = bm25 * 10.0
        if lower_q and lower_q in doc["title_low"]:
            score += 24.0
        for tok, weight in weighted_terms:
            if tok in doc["title_low"]:
                score += 6.0 * weight
            elif tok in doc["tags_low"]:
                score += 3.0 * weight

        info = doc["info"]
        fields = info["fields"]
        status = info["status"].lower()
        rag_priority = info["rag_priority"].lower()
        auto_ingested = bool(fields.get("auto_ingested")) or status == "published"
        quality_labels: list[str] = []
        if status == "needs-verification":
            quality_labels.append("待核验")
            score *= 0.78
        elif auto_ingested or rag_priority == "secondary":
            quality_labels.append("自动来源卡(仅代表来源陈述)")
            score *= 0.82
        if info["fields"].get("as_of"):
            quality_labels.append(f"基准日:{info['fields']['as_of']}")

        scored.append({
            "source": doc["rel"],
            "title": info["title"],
            "status": info["status"],
            "rag_priority": rag_priority,
            "quality_labels": quality_labels,
            "score": round(score, 2),
            "summary": info["summary"],
            "snippet": extract_snippet(info["body"], query_tok_list),
            "sources": field_list(fields, "sources")[:3],
            "related": field_list(fields, "related")[:3],
        })

    scored.sort(key=lambda item: item["score"], reverse=True)
    return {
        "query": query,
        "count": len(scored),
        "engine": "knowledgeflow-bm25-synonym-v2",
        "results": scored[:limit],
    }


def context_pack(store: Store, query: str, budget: int = 4000, limit: int = 6) -> dict[str, Any]:
    """Pack search results into a character-bounded summary + evidence bundle."""
    res = search_vault(store, query, limit=limit)
    results = res.get("results", [])
    per_item_cap = max(320, budget // max(1, min(limit, len(results) or 1)))

    lines = [
        f"# Context Pack: `{query}`",
        f"- 检索命中：`{res.get('count', 0)}` 条 · 打包预算：`{budget}` 字符 · 引擎：`{res.get('engine', '')}`",
        "",
    ]
    used_chars = sum(len(x) + 1 for x in lines)
    raw_total_chars = 0
    packed: list[dict[str, Any]] = []

    for idx, hit in enumerate(results, 1):
        rel = hit["source"]
        abs_path = store.vault / rel
        if not abs_path.is_file():
            continue
        raw_total_chars += len(abs_path.read_text("utf-8", errors="ignore"))
        label_str = " / ".join(hit["quality_labels"]) if hit["quality_labels"] else "已核验或可用"
        header = f"## [{idx}] [[{rel[:-3]}|{hit['title']}]]"
        meta = f"- **状态/优先级**：`{hit['status']}` / `{hit['rag_priority']}` · **可信提示**：`{label_str}` · **Score**：`{hit['score']}`"
        sum_line = f"- **摘要**：{hit['summary'][:200]}" if hit["summary"] else ""
        remain = max(100, per_item_cap - len(header) - len(meta) - len(sum_line) - 80)
        snip_line = f"- **命中片段**：{hit['snippet'][:remain]}" if hit["snippet"] else ""
        src_line = f"- **来源**：{', '.join(hit['sources'][:2])}" if hit["sources"] else ""
        rel_line = f"- **关联**：{', '.join(hit['related'][:3])}" if hit["related"] else ""

        block = [line for line in (header, meta, sum_line, snip_line, src_line, rel_line, "") if line]
        block_len = sum(len(x) + 1 for x in block)
        if packed and used_chars + block_len > budget:
            break
        lines.extend(block)
        used_chars += block_len
        packed.append({
            "source": rel,
            "title": hit["title"],
            "status": hit["status"],
            "rag_priority": hit["rag_priority"],
            "quality_labels": hit["quality_labels"],
            "score": hit["score"],
        })

    markdown = "\n".join(lines).strip() + "\n"
    ratio = round(len(markdown) / raw_total_chars, 3) if raw_total_chars else 0.0
    return {
        "query": query,
        "budget_chars": budget,
        "used_chars": len(markdown),
        "raw_source_chars": raw_total_chars,
        "compression_ratio": ratio,
        "packed_count": len(packed),
        "items": packed,
        "markdown": markdown,
    }


def challenge_proposal(store: Store, proposal: str, limit: int = 8) -> dict[str, Any]:
    """Red-team a proposal against ADRs, compliance red lines, risks, and unverified warnings."""
    config = _load_config(store)
    risk_prefixes = tuple(config.get("challenge_risk_prefixes") or DEFAULT_RISK_PREFIXES)
    q_tokens = [tok for tok, _ in expand_query_tokens(proposal, config) if len(tok) >= 2]
    search_hits = {
        item["source"]: item
        for item in search_vault(store, f"{proposal} 决策 风险 合规 约束", limit=15).get("results", [])
    }

    notes, _, _, _ = _build_graph_maps(store.vault)
    findings: list[dict[str, Any]] = []
    for rel, info in notes.items():
        if info["bookkeeping"]:
            continue
        fields = info["fields"]
        status = info["status"].lower()
        note_type = field_str(fields, "type").lower()
        if status in {"archived", "generated"}:
            continue

        is_decision = note_type == "decision" or "adr" in rel.lower()
        is_risk_zone = rel.startswith(risk_prefixes) or any(k in rel.lower() for k in ("合规", "风控", "红线", "复盘", "risk", "decision"))
        is_warn = status == "needs-verification"
        if not (is_decision or is_risk_zone or is_warn or rel in search_hits):
            continue

        haystack = f"{info['title']} {info['summary']} {info['body'][:1500]}".lower()
        matched = [tok for tok in q_tokens if tok in haystack]
        if not matched and rel not in search_hits:
            continue

        risk_hits = [rk for rk in RISK_KEYWORDS if rk in haystack]
        score = len(matched) * 4.0 + (10.0 if is_decision else 0.0) + (8.0 if is_risk_zone else 0.0) + min(6.0, len(risk_hits) * 2.0)
        if rel in search_hits:
            score += min(15.0, float(search_hits[rel]["score"]) * 0.25)
        if status == "draft":
            # Keep draft compliance/ADR rules visible as advisory constraints without polluting RAG.
            score += 2.0

        if is_decision:
            bucket = "历史架构决策 (ADR)"
        elif is_warn:
            bucket = "时效与待核验警示"
        elif any(k in rel for k in ("合规", "红线", "监管")) or "红线" in risk_hits or "禁止" in risk_hits:
            bucket = "监管与合规红线"
        else:
            bucket = "风险与失效警示"

        findings.append({
            "source": rel,
            "title": info["title"],
            "bucket": bucket,
            "status": info["status"],
            "matched_terms": matched[:6],
            "risk_signals": risk_hits[:5],
            "score": round(score, 2),
            "summary": info["summary"] or extract_snippet(info["body"], matched, limit=180),
        })

    findings.sort(key=lambda item: item["score"], reverse=True)
    selected = findings[:limit]

    lines = [
        f"# 方案红队对抗报告 (Knowledge Challenge): `{proposal}`",
        f"- 匹配到约束、ADR 与风险边界：**{len(selected)}** 条（候选池 {len(findings)} 条）",
        "",
    ]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in selected:
        grouped[item["bucket"]].append(item)
    for bucket, group_items in grouped.items():
        lines.append(f"## {bucket}")
        lines.append("")
        for item in group_items:
            terms_str = ", ".join(item["matched_terms"]) or "语义检索"
            lines.append(f"- [[{item['source'][:-3]}|{item['title']}]]（命中：`{terms_str}` · Score `{item['score']}`）")
            if item["summary"]:
                lines.append(f"  - 要点约束：{item['summary']}")
        lines.append("")

    return {
        "proposal": proposal,
        "total_candidates": len(findings),
        "selected_count": len(selected),
        "items": selected,
        "markdown": "\n".join(lines).strip() + "\n",
    }


def crosslink_vault(store: Store, apply: bool = False, limit: int = 120) -> dict[str, Any]:
    """Conservatively link distinct folders via configured entity anchors."""
    config = _load_config(store)
    notes, _, _, _ = _build_graph_maps(store.vault)
    by_rel_no_ext = {rel[:-3]: rel for rel in notes}
    by_stem: dict[str, list[str]] = defaultdict(list)
    for rel in notes:
        by_stem[Path(rel).stem].append(rel)

    anchors: list[tuple[list[str], str]] = []
    for entry in config.get("entity_anchors", []):
        kws = [str(k).lower() for k in entry.get("keywords", []) if str(k).strip()]
        target = str(entry.get("target", "")).removesuffix(".md")
        resolved = by_rel_no_ext.get(target)
        if not resolved or not kws:
            continue
        target_status = notes[resolved]["status"].lower()
        if target_status in {"active", "maintained", "published", "needs-verification"}:
            anchors.append((kws, resolved))

    planned: list[dict[str, Any]] = []
    changed_files = 0
    for rel, info in notes.items():
        if len(planned) >= limit:
            break
        if info["bookkeeping"]:
            continue
        status = info["status"].lower()
        fields = info["fields"]
        if status not in {"active", "maintained", "published", "needs-verification"}:
            continue
        # Respect explicit empty opt-out `related: []`.
        if "related" in fields and not field_list(fields, "related"):
            continue

        existing_targets: set[str] = set()
        for raw_link in _extract_wikilinks(info["body"]) + field_list(fields, "related"):
            resolved = resolve_wikilink(raw_link, rel, {**by_rel_no_ext, **{r: r for r in notes}}, by_stem)
            if resolved:
                existing_targets.add(resolved)

        top_dir = str(Path(rel).parent)
        haystack = f"{info['title']} {info['summary']} {info['body'][:3500]}".lower()
        additions: list[str] = []
        for kws, anchor_rel in anchors:
            if anchor_rel == rel or str(Path(anchor_rel).parent) == top_dir:
                continue
            if anchor_rel in existing_targets:
                continue
            hit = any(
                (re.search(rf"(?<![a-z0-9]){re.escape(k)}(?![a-z0-9])", haystack) if re.match(r"^[a-z0-9._+-]+$", k) else k in haystack)
                for k in kws
            )
            if hit:
                additions.append(anchor_rel)
                existing_targets.add(anchor_rel)
            if len(additions) >= 2:
                break

        if not additions:
            continue
        planned.append({"source": rel, "add": additions})
        if apply:
            current_related = field_list(fields, "related")
            new_related = current_related + [f"[[{a[:-3]}]]" for a in additions]
            fm = info["fm"]
            new_fm = replace_frontmatter_list(fm, "related", new_related)
            new_fm = replace_frontmatter_scalar(new_fm, "relations_updated", today())
            path = store.vault / rel
            path.write_text(f"---\n{new_fm.rstrip()}\n---\n\n{info['body'].lstrip()}", "utf-8")
            changed_files += 1

    return {
        "applied": apply,
        "anchors_active": len(anchors),
        "candidates": len(planned),
        "changed_files": changed_files,
        "samples": planned[:15],
    }


def _note_link(rel: str, label: str, in_table: bool = False) -> str:
    safe_label = label.replace("|", "-")
    sep = "\\|" if in_table else "|"
    return f"[[{rel[:-3]}{sep}{safe_label}]]"


def build_hot_cache(store: Store) -> dict[str, Any]:
    """Generate single-read non-hub Agent Hot Cache markdown dashboard."""
    config = _load_config(store)
    notes, sem_out, sem_in, total_edges = _build_graph_maps(store.vault)

    total_notes = len(notes)
    active_notes = 0
    needs_ver = 0
    auto_cards = 0
    drafts = 0
    substantive_nodes: list[dict[str, Any]] = []
    active_orphans: list[dict[str, Any]] = []
    ver_queue: list[dict[str, Any]] = []
    draft_queue: list[dict[str, Any]] = []

    for rel, info in notes.items():
        st = info["status"].lower()
        fields = info["fields"]
        if st == "draft":
            drafts += 1
            if not info["bookkeeping"]:
                draft_queue.append(info)
            continue
        if fields.get("auto_ingested"):
            auto_cards += 1
        elif st == "needs-verification":
            needs_ver += 1
            if not info["bookkeeping"]:
                ver_queue.append(info)
        elif st in {"active", "maintained"} and not info["bookkeeping"]:
            active_notes += 1

        if info["bookkeeping"]:
            continue

        in_deg = len(sem_in.get(rel, ()))
        out_deg = len(sem_out.get(rel, ()))
        updated_str = field_str(fields, "content_updated") or field_str(fields, "updated") or "1970-01-01"
        substantive_nodes.append({
            **info,
            "in_deg": in_deg,
            "out_deg": out_deg,
            "deg": in_deg + out_deg,
            "updated_str": updated_str,
        })
        if st in {"active", "maintained"} and in_deg == 0 and out_deg == 0:
            active_orphans.append(info)

    hubs = sorted(substantive_nodes, key=lambda x: (-x["deg"], -x["in_deg"], x["rel"]))[:15]
    recent = sorted(substantive_nodes, key=lambda x: (x["updated_str"], x["deg"]), reverse=True)[:10]

    lines = [
        "---",
        'id: "kf-agent-hot-cache"',
        'title: "智能体热启动上下文"',
        'type: "dashboard"',
        'status: "maintained"',
        f'updated: "{today()}"',
        'source_type: "generated"',
        'content_level: "index"',
        'rag_priority: "excluded"',
        'tags: ["智能体", "热启动", "图谱"]',
        "---",
        "",
        f"# 🧠 智能体热启动上下文 (Hot Cache) · {today()}",
        "",
        "> 借鉴非枢纽图谱（Non-Hub Graph）设计：自动排除目录/MOC/模板等索引节点，帮助 AI Agent 与用户在 **1 次读取**内掌握全库核心结构、近期更新与治理队列。",
        "",
        "## 1. 全库与非枢纽图谱快照",
        "",
        "| 指标 | 当前值 | 说明 |",
        "|---|---:|---|",
        f"| 总 Markdown 笔记 | {total_notes} | 全库（不含隐藏目录与源码） |",
        f"| 核心常青 / 活跃 (`active` / `maintained`) | {active_notes} | 进入主检索的核心知识与决策记录 |",
        f"| 待核验 (`needs-verification`) | {needs_ver} | 时效性判断，`rag_priority: secondary` |",
        f"| 自动来源卡 / 草稿 | {auto_cards} / {drafts} | 自动入库证据卡与隔离草稿 |",
        f"| 非枢纽语义边 (`semantic edges`) | {total_edges} | 排除 MOC/目录/模板后的实质正文连接 |",
        f"| 无关联活跃孤岛 | {len(active_orphans)} | 零入/出语义链的 `active` 笔记 |",
        "",
        "## 2. 非枢纽语义核心节点 Top 15",
        "",
        "| 笔记 | 状态 | 语义入/出链 | 摘要要点 |",
        "|---|---|---:|---|",
    ]
    for item in hubs:
        summary_short = (item["summary"] or "-")[:70].replace("|", " ")
        lines.append(f"| {_note_link(item['rel'], item['title'], in_table=True)} | `{item['status']}` | {item['in_deg']} / {item['out_deg']} | {summary_short} |")
    if not hubs:
        lines.append("| 暂无实质笔记 | - | 0 / 0 | 运行 `./kb.sh run` 或新建知识笔记后自动汇总 |")

    lines.extend(["", "## 3. 近期实质内容更新 Top 10", ""])
    for item in recent:
        lines.append(f"- `{item['updated_str']}` · {_note_link(item['rel'], item['title'])} (`{item['status']}`)")
    if not recent:
        lines.append("- 暂无近期更新")

    lines.extend([
        "",
        "## 4. 开放治理队列",
        "",
        f"- **待核验 (`needs-verification`)**: {len(ver_queue)} 篇" + (
            "：" + "、".join(_note_link(x["rel"], x["title"]) for x in ver_queue[:5]) if ver_queue else ""
        ),
        f"- **草稿隔离 (`draft`)**: {len(draft_queue)} 篇" + (
            "：" + "、".join(_note_link(x["rel"], x["title"]) for x in draft_queue[:5]) if draft_queue else ""
        ),
        "",
        "## 5. 台账、模板与智能体命令入口",
        "",
        "- **可视化台账与地图**：[[00-导航/知识台账.base|多维知识台账 (.base)]] · [[20-知识流入/00-流水线收件箱|流水线收件箱]] · [[10-知识库/00-知识地图|全局知识地图]]",
        "- **标准模板库**：`00-模板/01-T-领域研究与常青笔记.md` · `02-T-决策记录(ADR).md` · `03-T-前瞻追踪与待核验笔记.md` · `04-T-阶段复盘(40-Questions).md`",
        "- **浏览器采集预设**：`00-模板/WebClipper/knowledgeflow-web-clipper.json`",
        "- **CLI 入口**：`./kb.sh context-pack \"主题\"` · `./kb.sh challenge \"方案描述\"` · `./kb.sh crosslink --dry-run` · `./kb.sh search \"关键词\"` · `./kb.sh hot-cache` · `./kb.sh health`",
    ])

    hot_note_rel = str(config.get("hot_cache_note", "00-导航/01-智能体热启动上下文.md"))
    out_path = store.vault / hot_note_rel
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", "utf-8")
    return {
        "generated_at": datetime.now().astimezone().replace(microsecond=0).isoformat(),
        "path": hot_note_rel,
        "total_notes": total_notes,
        "active_notes": active_notes,
        "semantic_edges": total_edges,
        "active_orphans": len(active_orphans),
    }
