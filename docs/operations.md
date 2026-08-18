# 运行与调度指南

这份指南把生产环境中验证过的运行约束抽成通用部署方式。核心流水线仍然可以只用命令行运行；调度器只是外层触发器，不拥有知识状态。

## 推荐执行顺序

```bash
./kb.sh run --retry-rejected
./kb.sh health
```

`--retry-rejected` 只会重试最新决策为 `rejected` 且详情页补抓成功的候选。重试先写入一条 `requeued` 审计记录，再写入最终的 `published` 或 `rejected` 决策；因此可以安全地重复运行，也不会让人工删除的页面重新出现。

如果要验证安装而不访问网络：

```bash
./kb.sh run --offline
./kb.sh health
```

## macOS LaunchAgent

将下面模板保存为 `~/Library/LaunchAgents/com.knowledgeflow.sync.plist`，把 `/ABS/PATH/TO/knowledgeflow-obsidian` 替换成仓库绝对路径：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.knowledgeflow.sync</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>/ABS/PATH/TO/knowledgeflow-obsidian/kb.sh</string>
    <string>run</string>
    <string>--retry-rejected</string>
  </array>
  <key>WorkingDirectory</key>
  <string>/ABS/PATH/TO/knowledgeflow-obsidian</string>
  <key>RunAtLoad</key>
  <false/>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>3</integer><key>Minute</key><integer>0</integer></dict>
  <key>ThrottleInterval</key>
  <integer>3600</integer>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>PYTHONDONTWRITEBYTECODE</key>
    <string>1</string>
    <key>PYTHONUTF8</key>
    <string>1</string>
  </dict>
  <!-- 日志放在云盘/文件提供商目录之外，避免 macOS 启动前沙箱拒绝打开重定向文件。 -->
  <key>StandardOutPath</key>
  <string>/Users/REPLACE_ME/Library/Logs/knowledgeflow.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/REPLACE_ME/Library/Logs/knowledgeflow_error.log</string>
</dict>
</plist>
```

加载、启用和手动验证：

```bash
mkdir -p "$HOME/Library/Logs"
launchctl bootout "gui/$(id -u)/com.knowledgeflow.sync" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.knowledgeflow.sync.plist"
launchctl enable "gui/$(id -u)/com.knowledgeflow.sync"
launchctl kickstart -k "gui/$(id -u)/com.knowledgeflow.sync"
launchctl print "gui/$(id -u)/com.knowledgeflow.sync" | rg 'state =|runs =|last exit code'
```

预期结果是最近一次退出码为 `0`。如果看到 `EX_CONFIG` 或 `Operation not permitted`，优先检查 `StandardOutPath`、`StandardErrorPath` 是否仍指向 iCloud/CloudDrive/其他文件提供商目录。

## 运行数据与公开仓库

`.knowledgeflow/data/` 是运行时账本，包含候选、决策和来源异常记录，默认被 `.gitignore` 排除。公开仓库只提交配置模板、示例笔记、代码和文档；不要提交个人来源地址、私有订阅、真实候选内容或 API 密钥。

模型综合不是抓取和决策的前置条件。没有模型密钥时，应生成明确标记的自动证据草稿或隔离提案，不能把它们伪装成已核验的正式知识页。

## 健康检查建议

至少关注以下指标：

- `source_errors == 0`，且启用来源最近一次运行均为 `ok` 或 `unchanged`；
- `health.healthy == true`，自动文章的 `candidate_id`、`sources`、`review_status` 和 `verification` 字段完整；
- `requeued` 只作为审计事件，不应被质量检查器当成未知决策；
- 自动来源卡的路由率和吸收率持续提升，长期未路由卡片应进入主题治理，而不是无限堆积在收件箱。
