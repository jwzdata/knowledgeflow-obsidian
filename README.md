# KnowledgeFlow Obsidian

一个可以直接用 Obsidian 打开的、来源优先且可审计的知识流入系统。

它把“订阅很多信息”变成一条真正闭环的流水线：

```text
固定来源 → 抓取与去重 → 质量评分 → 自动过滤 → 主题路由
        → 编号 + 日期标题 → Obsidian 知识目录 → 仪表盘与健康检查
```

## 为什么做这个项目

普通 RSS 阅读器停在“读过”，剪藏工具停在“收集过”，而知识库真正需要的是：来源可信、内容可追溯、文章进到正确目录、重复运行不会制造垃圾，并且低质量内容删除后不再回流。

KnowledgeFlow 的默认策略是：

- 只连接你明确配置的固定来源；
- 用确定性规则做抓取、去重、评分、过滤和路由；
- 自动生成带日期与连续编号的来源知识页；
- 明确标记“自动入库、尚未复核、仅代表来源陈述”；
- 将候选与决策记入账本，人工删除后不会自动重建；
- 不要求数据库、云服务或 API 密钥。

## 3 分钟开始

要求：macOS / Linux、Python 3.11+、Obsidian 桌面版。

```bash
git clone https://github.com/jwzdata/knowledgeflow-obsidian.git
cd knowledgeflow-obsidian
./kb.sh run
```

然后在 Obsidian 中选择“打开文件夹作为仓库”，打开克隆后的目录。进入“设置 → 第三方插件”，关闭安全模式并启用 **KnowledgeFlow Review**。左侧丝带会出现流水线按钮。

Windows 可运行：

```powershell
$env:PYTHONPATH="$PWD/src"
python -m knowledgeflow --vault . run
```

首次试用网络来源前，也可执行完全离线的结构验证：

```bash
./kb.sh run --offline
./kb.sh health
```

## 自动生成的文章长什么样

文件示例：

```text
10-知识库/02-经济与政策/
└── 001-2026-07-22-Federal-Reserve-issues-FOMC-statement.md
```

每一页都包含：原始来源、发布主体、候选 ID、质量分、主题路由、证据边界、自动入库标记和人工复核状态。它是可追溯的来源卡，不伪装成已经独立验证的事实。

## 常用命令

| 命令 | 作用 |
|---|---|
| `./kb.sh run` | 执行完整流水线 |
| `./kb.sh sync` | 只抓取并写入候选账本 |
| `./kb.sh promote --dry-run` | 预览自动过滤与入库结果 |
| `./kb.sh promote` | 路由、编号并生成文章 |
| `./kb.sh render` | 重建 Obsidian 收件箱 |
| `./kb.sh health` | 检查生成文章的元数据契约 |

## 配置来源与主题

编辑 [`.knowledgeflow/config.json`](.knowledgeflow/config.json)：

- `sources` 定义 RSS/Atom 地址、发布主体、可信等级和允许进入的主题；
- `topics` 定义关键词、知识目录和显示名称；
- `policy` 控制最低分、摘要长度、单来源容量和单次入库上限。

默认附带美联储、BIS 与 arXiv AI 三个演示来源。它们是配置示例，不代表项目方为第三方内容背书。生产使用前请按你的领域维护来源白名单，详见 [来源治理](docs/source-governance.md)。

## 项目结构

```text
.knowledgeflow/       配置与运行账本（运行数据不提交）
.obsidian/plugins/    无需构建的桌面端操作台
00-导航/              首页与使用入口
10-知识库/            自动路由后的知识文章
20-知识流入/          可视化收件箱
docs/                 架构、治理与二次发行文档
src/knowledgeflow/    零第三方依赖的 Python 引擎
tests/                离线回归测试
```

## 隐私与安全

项目不会读取仓库外文件，也不会上传笔记。抓取时只访问配置中的订阅地址。请勿把 API 密钥、私有订阅地址或个人笔记提交到公开仓库；本地私密配置可放在被忽略的 `.knowledgeflow/private.json`。

## 适合二次开发与商业发行

核心引擎、Obsidian 操作台、内容模板和配置均相互解耦。可以替换品牌、预置垂直领域来源与主题，并在不修改流水线代码的情况下形成行业版。见 [发行与白标指南](docs/distribution.md)。

## 贡献

欢迎提交 Issue 和 Pull Request。开发与测试流程见 [CONTRIBUTING.md](CONTRIBUTING.md)，安全问题请按 [SECURITY.md](SECURITY.md) 私下报告。

MIT License。
