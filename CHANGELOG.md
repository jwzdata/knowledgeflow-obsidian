# Changelog

本项目遵循 [Semantic Versioning](https://semver.org/)。

## 2.0.0 - 2026-11-15

- 新增 `agent_tools.py` 零依赖 AI 原生工具引擎与 5 个新 CLI 子命令：`search`、`hot-cache`、`context-pack`、`challenge`、`crosslink`。
- **非枢纽热缓存 (`hot-cache`)**：生成单次可读的 `00-导航/01-智能体热启动上下文.md`，自动排除 MOC/仪表盘/模板枢纽，统计正文语义边、活跃孤岛与治理队列，并在 `./kb.sh run` 中自动刷新。
- **双语混合检索与预算打包 (`search` / `context-pack`)**：内置可配置中英同义扩展桥（BM25 + 标题/标签加权）、严格 `draft` 检索隔离、`needs-verification` / 自动卡降权警示与字符预算紧凑打包。
- **方案红队对抗质询 (`challenge`)**：将方案设想与 `type: decision`（ADR）、合规红线、风险警示及待核验笔记对撞分桶输出。
- **跨目录实体联动 (`crosslink`)**：按 `entity_anchors` 配置保守补全跨目录 `related` 关联（支持 `--dry-run` 预览与 `related: []` 退订）。
- **Obsidian 原生套件升级**：新增 `.obsidian/types.json`、颜色分组 `.obsidian/graph.json`、`00-导航/知识台账.base` 多维台账、标准模板体系 `00-模板/01..04` 及 Obsidian Web Clipper 预设。
- **桌面插件 `KnowledgeFlow Review 2.0.0`**：新增双语混合检索弹窗、方案对抗质询弹窗及热缓存/`.base` 快捷命令。
- 新增 `tests/test_agent_tools.py` 与 `tests/test_plugin_smoke.js`，并纳入 GitHub Actions CI 流水线。

## 1.1.0 - 2026-08-18

- 增加 HTML 详情页摘要补抓：RSS/Atom 摘要不足时，可按来源类型自动提取正文容器，失败不阻断整条流水线。
- 增加 `--retry-rejected`：对因摘要不足被过滤的候选执行详情页重试，并写入 `requeued` 审计事件。
- 详情页重试后的候选账本采用原子写回，避免中断时留下半行 JSONL。
- 扩展运行报告，记录详情页补抓成功数与失败数。
- 增加生产运行与 macOS LaunchAgent 调度指南，明确将日志放在云盘目录之外以规避系统沙箱限制。
- 增加生产来源包示例、自动证据草稿和知识转化队列的部署说明。
- 新增详情页提取、重试审计和幂等行为回归测试。

## 1.0.0 - 2026-07-22

- 发布可直接打开的 Obsidian 示例知识库。
- 提供 RSS/Atom 抓取、URL 规范化、幂等去重与来源账本。
- 提供可信度、相关性、时效性和结构化程度评分。
- 提供自动过滤、主题路由、连续编号与日期标题。
- 提供 Obsidian 桌面端操作台、收件箱和健康检查。
- 提供零网络依赖的测试、GitHub Actions 与开源治理文件。
