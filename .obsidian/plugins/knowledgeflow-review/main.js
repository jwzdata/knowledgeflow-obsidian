const { ItemView, Notice, Plugin, setIcon } = require("obsidian");
const { execFile } = require("child_process");
const path = require("path");

const VIEW_TYPE = "knowledgeflow-dashboard";

class KnowledgeFlowView extends ItemView {
  constructor(leaf, plugin) {
    super(leaf);
    this.plugin = plugin;
    this.busy = false;
  }

  getViewType() { return VIEW_TYPE; }
  getDisplayText() { return "KnowledgeFlow"; }
  getIcon() { return "rss"; }

  async onOpen() { await this.render(); }

  async readStatus() {
    try {
      const raw = await this.app.vault.adapter.read(".knowledgeflow/data/status.json");
      return JSON.parse(raw);
    } catch (_) {
      return { candidates: 0, pending: 0, published: 0, rejected: 0, source_errors: 0 };
    }
  }

  button(parent, label, icon, action, primary = false) {
    const button = parent.createEl("button", { cls: primary ? "kf-button kf-primary" : "kf-button" });
    setIcon(button.createSpan({ cls: "kf-button-icon" }), icon);
    button.createSpan({ text: label });
    button.disabled = this.busy;
    button.addEventListener("click", action);
    return button;
  }

  async render() {
    const status = await this.readStatus();
    const root = this.contentEl;
    root.empty();
    root.addClass("knowledgeflow-view");
    const hero = root.createDiv({ cls: "kf-hero" });
    hero.createEl("div", { text: "KNOWLEDGEFLOW", cls: "kf-eyebrow" });
    hero.createEl("h1", { text: "知识流入操作台" });
    hero.createEl("p", { text: "固定来源自动筛选、主题路由、编号入库与质量审计。" });

    const actions = hero.createDiv({ cls: "kf-actions" });
    this.button(actions, this.busy ? "正在运行…" : "运行完整流水线", "play", () => this.runPipeline("run"), true);
    this.button(actions, "刷新", "refresh-cw", () => this.render());
    this.button(actions, "打开收件箱", "inbox", () => this.openInbox());

    const grid = root.createDiv({ cls: "kf-stats" });
    const cards = [
      ["候选总数", status.candidates || 0, "inbox"],
      ["待处理", status.pending || 0, "clock-3"],
      ["已入库", status.published || 0, "file-check-2"],
      ["已过滤", status.rejected || 0, "shield-x"],
      ["来源异常", status.source_errors || 0, "triangle-alert"]
    ];
    for (const [label, value, icon] of cards) {
      const card = grid.createDiv({ cls: "kf-stat" });
      setIcon(card.createSpan({ cls: "kf-stat-icon" }), icon);
      card.createEl("strong", { text: String(value) });
      card.createEl("span", { text: label });
    }

    const guide = root.createDiv({ cls: "kf-panel" });
    guide.createEl("h2", { text: "闭环规则" });
    const list = guide.createEl("ol");
    list.createEl("li", { text: "只抓取配置中启用的固定来源。" });
    list.createEl("li", { text: "低分、短摘要和重复 URL 自动过滤。" });
    list.createEl("li", { text: "通过门槛的文章直接进入主题目录，自动编号且标题带日期。" });
    list.createEl("li", { text: "每篇文章保留来源、候选 ID 和待复核标记；人工删除后不会回流。" });
    if (status.updated_at) guide.createEl("small", { text: `状态更新：${status.updated_at}` });
  }

  vaultPath() {
    const adapter = this.app.vault.adapter;
    if (!adapter.getBasePath) throw new Error("当前存储适配器不支持本地命令");
    return adapter.getBasePath();
  }

  async runPipeline(command) {
    if (this.busy) return;
    this.busy = true;
    await this.render();
    const vault = this.vaultPath();
    const script = path.join(vault, "kb.sh");
    new Notice("KnowledgeFlow 流水线已启动");
    execFile(script, [command], { cwd: vault, timeout: 180000, maxBuffer: 4 * 1024 * 1024 }, async (error, stdout, stderr) => {
      this.busy = false;
      if (error) {
        console.error("KnowledgeFlow failed", error, stdout, stderr);
        new Notice(`运行失败：${(stderr || error.message).slice(0, 220)}`, 10000);
      } else {
        new Notice("流水线完成，文章已路由到知识目录");
      }
      await this.render();
    });
  }

  async openInbox() {
    const status = await this.readStatus();
    const note = (status.inbox_note || "20-知识流入/00-流水线收件箱.md").replace(/\.md$/, "");
    await this.app.workspace.openLinkText(note, "", false);
  }
}

module.exports = class KnowledgeFlowPlugin extends Plugin {
  async onload() {
    this.registerView(VIEW_TYPE, leaf => new KnowledgeFlowView(leaf, this));
    this.addRibbonIcon("rss", "KnowledgeFlow 操作台", () => this.activateView());
    this.addCommand({ id: "open-dashboard", name: "打开知识流入操作台", callback: () => this.activateView() });
    this.addCommand({ id: "run-pipeline", name: "运行完整流水线", callback: async () => {
      await this.activateView();
      const leaves = this.app.workspace.getLeavesOfType(VIEW_TYPE);
      if (leaves[0] && leaves[0].view.runPipeline) leaves[0].view.runPipeline("run");
    }});
  }

  async activateView() {
    let leaf = this.app.workspace.getLeavesOfType(VIEW_TYPE)[0];
    if (!leaf) {
      leaf = this.app.workspace.getRightLeaf(false);
      await leaf.setViewState({ type: VIEW_TYPE, active: true });
    }
    this.app.workspace.revealLeaf(leaf);
  }

  onunload() { this.app.workspace.detachLeavesOfType(VIEW_TYPE); }
};
