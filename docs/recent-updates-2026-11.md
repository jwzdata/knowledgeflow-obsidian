# 2026-11 AI 原生与 Obsidian 原生架构演进汇总 (v2.0.0)

这份文档总结了从 2026 年 8 月 `v1.1.0` 发布到 2026 年 11 月 `v2.0.0` 期间，围绕“大规模真实知识库使用体感与 AI 智能体检索协同”打磨后沉淀进开源框架的核心升级。所有实现均保持零第三方依赖与非秘密公开配置。

## 核心演进能力

### 1. 非枢纽热缓存 (`hot-cache`)
传统目录地图（MOC）节点入链极高，极易误导图谱统计或让 AI Agent 在首跳浪费大量 Token 遍历目录。`./kb.sh hot-cache` 自动排除 `type: moc/index/dashboard/template` 枢纽节点，计算正文双向实质语义边，生成仅几十行的单次可读文件 `00-导航/01-智能体热启动上下文.md`。

### 2. 质量感知双语混合检索与预算受限打包 (`search` / `context-pack`)
- 零依赖纯 Python BM25 + 中英文术语同义桥（如 `碳关税 ↔ CBAM`、`大模型 ↔ LLM/Agent`、`架构决策 ↔ ADR`），避免中英混用查不到对应笔记；
- 严格遵守 `status: draft` 隔离红线，`needs-verification` 与自动入库卡自动降权并附带可信警示标签；
- `context-pack --budget N` 将检索结果按字符预算打包成“状态 + 可信标签 + 摘要 + 命中片段 + 一手来源 + 关联”的紧凑上下文包。

### 3. 方案红队对抗质询 (`challenge`)
借鉴对抗式审查思路，输入方案描述或技术选型后，跨库匹配 `type: decision`（ADR）、风险与合规规则及 `needs-verification` 时效预警，按“监管与合规红线 / 历史架构决策 / 风险警示 / 待核验提示”分桶输出，防止新方案与既有红线冲突。

### 4. 保守跨目录实体联动 (`crosslink`)
基于 `.knowledgeflow/config.json` 中可配置的 `entity_anchors`，使用英文词边界 regex 识别跨目录强概念实体并写入 `related` 字段，默认支持 `--dry-run` 预览与 `related: []` 显式退订。

### 5. Obsidian 原生能力全面补齐
- `.obsidian/types.json` + `.obsidian/graph.json`：统一字段属性类型并为 ADR、待核验、草稿、自动入库卡与活跃常青笔记配置图谱分区着色；
- `00-导航/知识台账.base`：零第三方插件的多维原生 Bases 视图（含 ADR 与图片附件卡片库）；
- `00-模板/01..04` 标准化模板 + `00-模板/WebClipper/knowledgeflow-web-clipper.json` 浏览器一键入库预设；
- `KnowledgeFlow Review 2.0.0` 插件内置混合检索、方案对抗弹窗及热缓存/台账快捷命令。
