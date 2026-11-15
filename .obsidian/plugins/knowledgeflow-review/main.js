const { ItemView, Modal, Notice, Plugin, setIcon } = require("obsidian");
const { execFile } = require("child_process");
const path = require("path");

const VIEW_TYPE = "knowledgeflow-dashboard";

function runKbCli(vaultPath, command, args = []) {
  return new Promise((resolve, reject) => {
    const script = path.join(vaultPath, "kb.sh");
    const executable = process.platform === "win32" ? script : "/bin/bash";
    const executableArgs = process.platform === "win32" ? [command, ...args] : [script, command, ...args];
    execFile(executable, executableArgs, {
      cwd: vaultPath,
      timeout: 180000,
      maxBuffer: 4 * 1024 * 1024,
      env: {
        ...process.env,
        LANG: process.env.LANG || "zh_CN.UTF-8",
        PYTHONUTF8: "1",
      },
    }, (error, stdout, stderr) => {
      if (error) {
        reject(new Error((stderr || stdout || error.message).trim().slice(0, 320)));
        return;
      }
      resolve((stdout || "").trim());
    });
  });
}

function parseJsonPayload(raw) {
  const start = raw.indexOf("{");
  const end = raw.lastIndexOf("}");
  return start >= 0 && end > start ? JSON.parse(raw.slice(start, end + 1)) : {};
}

class KnowledgeSearchModal extends Modal {
  constructor(plugin) {
    super(plugin.app);
    this.plugin = plugin;
  }

  onOpen() {
    const { contentEl } = this;
    contentEl.addClass("kf-modal");
    contentEl.createEl("h3", { text: "KnowledgeFlow 双语混合检索 (BM25 + 同义桥)" });
    const row = contentEl.createDiv({ cls: "kf-modal-row" });
    const input = row.createEl("input", {
      attr: { type: "text", placeholder: "输入中英文关键词或缩写，例如：碳关税 / CBAM / RAG / ADR" },
    });
    const btn = row.createEl("button", { text: "检索", cls: "mod-cta" });
    const resultEl = contentEl.createDiv({ cls: "kf-modal-results" });

    const execute = async () => {
      const q = (input.value || "").trim();
      if (!q) return;
      resultEl.empty();
      resultEl.createEl("p", { text: "正在跨库检索并校准可信等级…" });
      try {
        const raw = await runKbCli(this.plugin.vaultPath(), "search", [q, "--limit", "10", "--json"]);
        const payload = parseJsonPayload(raw);
        const results = Array.isArray(payload.results) ? payload.results : [];
        resultEl.empty();
        if (!results.length) {
          resultEl.createEl("p", { text: "未检索到匹配笔记。" });
          return;
        }
        const ul = resultEl.createEl("ul");
        for (const item of results) {
          const li = ul.createEl("li");
          const link = li.createEl("a", { text: item.title || item.source, href: "#" });
          link.addEventListener("click", (evt) => {
            evt.preventDefault();
            this.close();
            this.app.workspace.openLinkText(item.source, "", false);
          });
          const badges = (item.quality_labels || []).join(" / ") || item.status;
          li.createSpan({ text: ` [${badges} · ${item.score}]` });
          if (item.summary) li.createEl("div", { text: item.summary.slice(0, 140), cls: "kf-modal-snippet" });
        }
      } catch (err) {
        resultEl.empty();
        resultEl.createEl("p", { text: `检索失败：${err.message}` });
      }
    };

    btn.addEventListener("click", execute);
    input.addEventListener("keydown", (evt) => { if (evt.key === "Enter") execute(); });
    setTimeout(() => input.focus(), 20);
  }

  onClose() { this.contentEl.empty(); }
}

class ProposalChallengeModal extends Modal {
  constructor(plugin) {
    super(plugin.app);
    this.plugin = plugin;
  }

  onOpen() {
    const { contentEl } = this;
    contentEl.addClass("kf-modal");
    contentEl.createEl("h3", { text: "方案红队对抗质询 (Knowledge Challenge)" });
    contentEl.createEl("p", { text: "输入方案设想、技术选型或合规假设，自动匹配历史 ADR、合规红线与待核验警示：" });
    const textarea = contentEl.createEl("textarea", {
      attr: { rows: "4", placeholder: "例如：准备将未复核草稿直接接入 RAG 检索并用于 CBAM 财务核算" },
    });
    textarea.style.width = "100%";
    textarea.style.marginBottom = "10px";
    const btn = contentEl.createEl("button", { text: "执行对抗质询", cls: "mod-cta" });
    const resultEl = contentEl.createDiv({ cls: "kf-modal-results" });

    btn.addEventListener("click", async () => {
      const proposal = (textarea.value || "").trim();
      if (!proposal) {
        new Notice("请先输入方案描述");
        return;
      }
      resultEl.empty();
      resultEl.createEl("p", { text: "正在扫描 ADR、合规边界与风险条目…" });
      try {
        const raw = await runKbCli(this.plugin.vaultPath(), "challenge", [proposal, "--json"]);
        const payload = parseJsonPayload(raw);
        const items = Array.isArray(payload.items) ? payload.items : [];
        resultEl.empty();
        if (!items.length) {
          resultEl.createEl("p", { text: "未检测到直接冲突的 ADR 或高风险警示。" });
          return;
        }
        const grouped = new Map();
        for (const item of items) {
          const bucket = item.bucket || "风险与约束提示";
          if (!grouped.has(bucket)) grouped.set(bucket, []);
          grouped.get(bucket).push(item);
        }
        for (const [bucket, groupItems] of grouped.entries()) {
          resultEl.createEl("h4", { text: `${bucket} (${groupItems.length})` });
          const ul = resultEl.createEl("ul");
          for (const item of groupItems) {
            const li = ul.createEl("li");
            const link = li.createEl("a", { text: item.title || item.source, href: "#" });
            link.addEventListener("click", (evt) => {
              evt.preventDefault();
              this.close();
              this.app.workspace.openLinkText(item.source, "", false);
            });
            const hits = Array.isArray(item.matched_terms) && item.matched_terms.length
              ? ` [命中: ${item.matched_terms.slice(0, 4).join(", ")}]`
              : "";
            li.createSpan({ text: `${hits}${item.summary ? ` — ${item.summary.slice(0, 110)}` : ""}` });
          }
        }
      } catch (err) {
        resultEl.empty();
        resultEl.createEl("p", { text: `对抗质询失败：${err.message}` });
      }
    });
  }

  onClose() { this.contentEl.empty(); }
}

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
    hero.createEl("div", { text: "KNOWLEDGEFLOW 2.0", cls: "kf-eyebrow" });
    hero.createEl("h1", { text: "AI 原生知识工作台" });
    hero.createEl("p", { text: "固定来源筛选、非枢纽热缓存、双语混合检索与方案红队对抗质询。" });

    const actions = hero.createDiv({ cls: "kf-actions" });
    this.button(actions, this.busy ? "正在运行…" : "运行完整流水线", "play", () => this.runPipeline("run"), true);
    this.button(actions, "混合检索", "search", () => new KnowledgeSearchModal(this.plugin).open());
    this.button(actions, "方案对抗质询", "shield-alert", () => new ProposalChallengeModal(this.plugin).open());
    this.button(actions, "热启动上下文", "cpu", () => this.openPath("00-导航/01-智能体热启动上下文.md"));
    this.button(actions, "多维台账 (.base)", "table", () => this.openPath("00-导航/知识台账.base"));
    this.button(actions, "打开收件箱", "inbox", () => this.openInbox());
    this.button(actions, "刷新", "refresh-cw", () => this.render());

    const grid = root.createDiv({ cls: "kf-stats" });
    const cards = [
      ["候选总数", status.candidates || 0, "inbox"],
      ["待处理", status.pending || 0, "clock-3"],
      ["已入库", status.published || 0, "file-check-2"],
      ["已过滤", status.rejected || 0, "shield-x"],
      ["来源异常", status.source_errors || 0, "triangle-alert"],
    ];
    for (const [label, value, icon] of cards) {
      const card = grid.createDiv({ cls: "kf-stat" });
      setIcon(card.createSpan({ cls: "kf-stat-icon" }), icon);
      card.createEl("strong", { text: String(value) });
      card.createEl("span", { text: label });
    }

    const guide = root.createDiv({ cls: "kf-panel" });
    guide.createEl("h2", { text: "架构边界与闭环规则" });
    const list = guide.createEl("ol");
    list.createEl("li", { text: "只抓取配置中启用的固定来源，人工删除后经由 decisions.jsonl 永久防回流。" });
    list.createEl("li", { text: "草稿 (draft) 严格隔离于主检索外；待核验与自动来源卡携带证据边界提示。" });
    list.createEl("li", { text: "热缓存自动排除目录/MOC/模板枢纽，支持 Agent 1 次读取全库核心。" });
    list.createEl("li", { text: "新方案落地前可通过“方案对抗质询”匹配 ADR 与风控红线。" });
    if (status.updated_at) guide.createEl("small", { text: `状态更新：${status.updated_at}` });
  }

  async runPipeline(command) {
    if (this.busy) return;
    this.busy = true;
    await this.render();
    new Notice("KnowledgeFlow 流水线已启动");
    try {
      await runKbCli(this.plugin.vaultPath(), command, []);
      new Notice("流水线与热缓存已更新");
    } catch (error) {
      console.error("KnowledgeFlow failed", error);
      new Notice(`运行失败：${error.message}`, 10000);
    } finally {
      this.busy = false;
      await this.render();
    }
  }

  async openPath(relPath) {
    await this.app.workspace.openLinkText(relPath.replace(/\.md$/, ""), "", false);
  }

  async openInbox() {
    const status = await this.readStatus();
    await this.openPath(status.inbox_note || "20-知识流入/00-流水线收件箱.md");
  }
}

module.exports = class KnowledgeFlowPlugin extends Plugin {
  vaultPath() {
    const adapter = this.app.vault.adapter;
    if (!adapter.getBasePath) throw new Error("当前存储适配器不支持本地命令");
    return adapter.getBasePath();
  }

  async onload() {
    this.registerView(VIEW_TYPE, (leaf) => new KnowledgeFlowView(leaf, this));
    this.addRibbonIcon("rss", "KnowledgeFlow 操作台", () => this.activateView());
    this.addCommand({ id: "open-dashboard", name: "打开知识流入操作台", callback: () => this.activateView() });
    this.addCommand({ id: "open-hot-cache", name: "打开智能体热启动上下文 (Hot Cache)", callback: () => this.app.workspace.openLinkText("00-导航/01-智能体热启动上下文", "", false) });
    this.addCommand({ id: "open-knowledge-base", name: "打开多维知识台账 (.base)", callback: () => this.app.workspace.openLinkText("00-导航/知识台账.base", "", false) });
    this.addCommand({ id: "quick-search", name: "智能双语混合检索 (BM25 + Synonym)", callback: () => new KnowledgeSearchModal(this).open() });
    this.addCommand({ id: "challenge-proposal", name: "方案红队对抗质询 (Knowledge Challenge)", callback: () => new ProposalChallengeModal(this).open() });
    this.addCommand({
      id: "run-pipeline",
      name: "运行完整流水线",
      callback: async () => {
        await this.activateView();
        const leaves = this.app.workspace.getLeavesOfType(VIEW_TYPE);
        if (leaves[0] && leaves[0].view.runPipeline) leaves[0].view.runPipeline("run");
      },
    });
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
