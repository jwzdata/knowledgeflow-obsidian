# KnowledgeFlow Obsidian

一个可以直接用 Obsidian 打开、对人类阅读友好且面向 AI Agent 原生优化的、来源优先且可审计的知识系统。

它把“信息采集 → 证据治理 → 图谱连通 → AI 智能体调用”打通为一条零第三方依赖的闭环流水线：

```text
固定来源 / Web Clipper → sync 去重与详情补抓 → promote 评分路由与防回流
        → crosslink 跨区关联 + hot-cache 非枢纽热缓存
        → context-pack 预算打包 / challenge 红队对抗 / Obsidian 原生台账
```

## 为什么升级到 2.0

普通 RSS 阅读器停在“读过”，传统知识库则常陷入**优质笔记沉睡、中英术语检索断层、目录枢纽误导 Agent、上下文塞爆却缺少风险对抗**。KnowledgeFlow Obsidian 2.0 在保持 `1.x` 零依赖、来源可审计与删除防回流内核的同时，全面引入：

- **非枢纽热缓存 (`hot-cache`)**：1 次读取 `00-导航/01-智能体热启动上下文.md` 掌握全库核心结构，自动剔除 MOC/模板枢纽噪声；
- **双语混合检索与预算打包 (`search` / `context-pack`)**：纯 Python BM25 + 中英术语同义扩展，按 `--budget` 输出带可信边界标签与一手来源的紧凑证据包，并严格将 `draft` 隔离在检索之外；
- **方案红队对抗 (`challenge`)**：方案落地或选型前自动检索历史 ADR 决策、合规红线与待核验警告；
- **Obsidian 原生工作区**：开箱即用 `.base` 多维知识台账、分区着色关系图谱、`00-模板/01..04` 标准模板与 **Web Clipper** 浏览器一键入库预设。

## 3 分钟开始

要求：macOS / Linux、Python 3.11+、Obsidian 桌面版（可选 Node.js 运行插件测试）。

还没有安装 Obsidian？请访问 [Obsidian 官方下载](https://obsidian.md/download)。

```bash
git clone https://github.com/jwzdata/knowledgeflow-obsidian.git
cd knowledgeflow-obsidian
./kb.sh run --retry-rejected
./kb.sh hot-cache
```

然后在 Obsidian 中选择“打开文件夹作为仓库”，打开克隆后的目录。进入“设置 → 第三方插件”，关闭安全模式并启用 **KnowledgeFlow Review**。即可使用左侧工作台、**混检弹窗**、**方案对抗质询弹窗**与快捷键命令。

离线验证全库与智能体工具链：

```bash
./kb.sh run --offline
./kb.sh search "大模型 智能体"
./kb.sh context-pack "CBAM 碳关税" --budget 2000
./kb.sh challenge "忽略 draft 隔离并按 CBAM 核算成本"
./kb.sh crosslink --dry-run
./kb.sh health
```

Windows 可运行：

```powershell
$env:PYTHONPATH="$PWD/src"
python -m knowledgeflow --vault . run
```

## 常用命令

| 命令 | 作用 |
|---|---|
| `./kb.sh run` | 执行 `sync -> promote -> render -> hot-cache -> health` 完整流水线 |
| `./kb.sh sync` | 只抓取并写入候选账本 |
| `./kb.sh promote --retry-rejected` | 对被摘要门槛过滤的候选执行详情页补抓后重试并路由入库 |
| `./kb.sh hot-cache` | 重建非枢纽 `00-导航/01-智能体热启动上下文.md` |
| `./kb.sh search "关键词"` | 执行质效感知 BM25 + 中英同义扩展检索（隔离 `draft`） |
| `./kb.sh context-pack "主题" --budget 3000` | 生成字符预算受限、附带来源与可信标签的证据包 |
| `./kb.sh challenge "方案描述"` | 对照 ADR、合规边界与待核验条目执行红队对抗质询 |
| `./kb.sh crosslink [--dry-run \| --apply]` | 按实体锚点保守补全跨目录 `related` 关联 |
| `./kb.sh render` / `./kb.sh health` | 重建流水线收件箱 / 检查生成文章元数据契约 |

## 配置来源、同义词与实体锚点

编辑 [`.knowledgeflow/config.json`](.knowledgeflow/config.json)：

- `sources` / `topics` / `policy`：定义固定订阅来源、主题路由、最低分与详情补抓策略；
- `synonyms`：自定义领域中英术语与缩写同义映射；
- `entity_anchors`：配置跨目录概念锚点供 `crosslink` 保守关联；
- 私密订阅与个人配置请放在被 `.gitignore` 忽略的 `.knowledgeflow/private.json`。

默认附带美联储、BIS 与 arXiv AI 三个演示来源以及 ADR/AI/宏观示范笔记，方便开箱离线体验全部功能。生产使用请参考 [来源治理](docs/source-governance.md)。

## 项目结构

```text
.knowledgeflow/       配置与运行账本（运行数据不提交）
.obsidian/            插件 (2.0.0)、types.json 属性契约与着色 graph.json
00-导航/              首页、智能体热启动上下文与 知识台账.base
00-模板/              研究/ADR/时效核验/40-Questions复盘模板与 WebClipper 预设
10-知识库/            主题知识与架构决策目录
20-知识流入/          可视化收件箱
docs/                 架构、治理、运维调度与演进汇总
examples/             可复制的生产来源包
src/knowledgeflow/    零第三方依赖的 Python 2.0 引擎与 Agent 工具链
tests/                离线 Python 回归测试与 Obsidian 插件 Smoke 测试
```

## 隐私、二次发行与许可

- 核心引擎不读取仓库外文件、不绑定特定商业数据、不要求外部数据库或 API 密钥。
- 支持白标发行与行业垂直扩展，见 [发行与白标指南](docs/distribution.md)、[运行与调度指南](docs/operations.md) 及 [2026-11 演进说明](docs/recent-updates-2026-11.md)。
- 贡献指南见 [CONTRIBUTING.md](CONTRIBUTING.md)，安全问题见 [SECURITY.md](SECURITY.md)。MIT License。
