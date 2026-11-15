---
id: "adr-001-source-first"
title: "ADR-001：来源优先、草稿隔离与可审计知识边界"
summary: "确立 KnowledgeFlow 系统的核心架构红线：所有自动采集仅作为待抽检证据卡，未核验草稿绝不污染主 RAG 检索，跨区变更须可审计且幂等。"
type: "decision"
status: "active"
rag_priority: "primary"
created: "2026-07-22"
updated: "2026-11-15"
content_updated: "2026-11-15"
source_type: "curated"
content_level: "decision"
verification: "reviewed"
tags: ["ADR", "架构决策", "合规", "风控", "RAG"]
sources: ["docs/architecture.md", "docs/source-governance.md"]
related: ["[[10-知识库/01-AI与工程/000-Agentic-Knowledge-Architecture-and-Hybrid-RAG]]", "[[10-知识库/02-经济与政策/000-CBAM-and-Global-Carbon-Pricing-Overview]]"]
---

# ADR-001：来源优先、草稿隔离与可审计知识边界

## 1. 决策背景与约束问题

> 当外部订阅与大模型综合规模扩大时，最容易出现的失效模式是“未经核验的摘要伪装成确定性事实”，并污染智能体检索上下文。

## 2. 核心硬约束 (红线)

1. **来源优先与删除防回流**：自动入库内容保留 `candidate_id` 与一手 `sources`；人工删除后由 `decisions.jsonl` 永久防回流。
2. **草稿与时效分级隔离**：`status: draft` 笔记严格排除在 `search` 与 `context-pack` 主检索外；`needs-verification` 或纯 `auto_ingested` 卡片保留降权与待核验警示，不得冒充已验证结论。
3. **非枢纽热缓存**：AI Agent 首跳读取 `00-导航/01-智能体热启动上下文.md` 与 `context-pack` 预算打包，而非全库遍历目录索引或硬塞原始长文。

## 3. 适用检查与复核信号

- 任何涉及 RAG 索引构建、自动发布或跨境合规规则落地的方案，必须通过 `./kb.sh challenge` 红队质询检查是否触及上述边界。
