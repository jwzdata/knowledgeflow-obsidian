---
id: "kf-guide-agentic-rag"
title: "Agentic Knowledge Architecture：非枢纽热缓存与预算受限上下文打包"
summary: "梳理大模型 Agent 与 Obsidian 知识库协同的四大核心模式：Non-Hub Hot Cache、BM25+同义词混合检索、Token 预算受限 Context-Pack 与 Challenge 红队对抗。"
type: "domain"
status: "active"
rag_priority: "primary"
created: "2026-08-18"
updated: "2026-11-15"
content_updated: "2026-11-15"
source_type: "curated"
content_level: "guide"
verification: "reviewed"
tags: ["AI", "Agent", "RAG", "BM25", "知识架构"]
aliases: ["Agentic知识架构", "Hybrid RAG"]
sources: ["docs/architecture.md", "docs/recent-updates-2026-11.md"]
related: ["[[10-知识库/03-架构决策/001-ADR-001-Source-First-and-Draft-Isolation]]"]
---

# Agentic Knowledge Architecture：非枢纽热缓存与预算受限上下文打包

## 1. 核心结论

> 知识库的检索瓶颈通常不在模型参数量，而在 **目录/MOC枢纽节点噪声**、**中英文术语断层** 与 **无上限上下文塞入导致的注意力衰减**。

## 2. 四项关键工程机制

1. **非枢纽热缓存 (`hot-cache`)**：计算语义图谱度数时剔除 `index`、`dashboard`、`template` 与 `MOC`，让 Agent 在 1 次读取内定位真实高连接核心笔记。
2. **中英同义扩展检索 (`search`)**：通过零依赖 BM25 + 术语同义桥（如 `大模型 ↔ LLM/Agent`、`碳关税 ↔ CBAM`、`架构决策 ↔ ADR`）消除中英缩写不命中问题，并对自动来源卡标注证据边界。
3. **字符预算打包 (`context-pack`)**：按 `--budget` 截断并结构化组装“状态 + 可信标签 + 摘要 + 命中片段 + 来源”，典型压缩比 `10%~25%`。
4. **对抗质询 (`challenge`)**：在执行新方案前主动扫描 [[10-知识库/03-架构决策/001-ADR-001-Source-First-and-Draft-Isolation|ADR-001]] 与风险笔记，提前暴露冲突边界。
