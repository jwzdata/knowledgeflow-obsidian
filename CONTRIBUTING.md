# Contributing

感谢帮助改进 KnowledgeFlow。

1. Fork 仓库并从 `main` 创建功能分支。
2. 保持核心引擎仅依赖 Python 标准库；新增依赖需在 PR 中解释必要性。
3. 不要提交个人知识内容、登录凭据、私有订阅地址或运行账本。
4. 为解析、评分或路由行为的变化增加离线测试。
5. 运行 `python -m unittest discover -s tests -v` 和 `./kb.sh health`。
6. 提交 Pull Request，写明行为变化、兼容性和验证方式。

来源配置应指向合法公开、可稳定访问的 RSS/Atom 页面。项目不会接受绕过付费墙、身份验证或 robots 限制的抓取逻辑。
