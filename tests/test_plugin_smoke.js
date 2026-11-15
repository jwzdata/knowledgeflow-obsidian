const assert = require("assert");
const Module = require("module");
const path = require("path");

class PluginStub {
  constructor(app) {
    this.app = app;
    this.commands = [];
    this.views = [];
  }
  registerView(type, factory) { this.views.push({ type, factory }); }
  addRibbonIcon() {}
  addCommand(cmd) { this.commands.push(cmd); }
}

class ModalStub {
  constructor(app) { this.app = app; }
  open() {}
  close() {}
}

class ItemViewStub {
  constructor(leaf) { this.leaf = leaf; }
}

const originalLoad = Module._load;
Module._load = function (request, parent, isMain) {
  if (request === "obsidian") {
    return {
      ItemView: ItemViewStub,
      Modal: ModalStub,
      Notice: function () {},
      Plugin: PluginStub,
      setIcon: function () {},
    };
  }
  return originalLoad.call(this, request, parent, isMain);
};

async function main() {
  const pluginPath = path.resolve(__dirname, "../.obsidian/plugins/knowledgeflow-review/main.js");
  const KnowledgeFlowPlugin = require(pluginPath);
  const opened = [];
  const app = {
    vault: { adapter: { getBasePath: () => path.resolve(__dirname, "..") } },
    workspace: {
      getLeavesOfType: () => [],
      getRightLeaf: () => ({ setViewState: async () => {} }),
      revealLeaf: () => {},
      openLinkText: async (target) => { opened.push(target); },
    },
  };
  const plugin = new KnowledgeFlowPlugin(app);
  await plugin.onload();

  const ids = plugin.commands.map((c) => c.id);
  for (const required of ["open-dashboard", "open-hot-cache", "open-knowledge-base", "quick-search", "challenge-proposal", "run-pipeline"]) {
    assert(ids.includes(required), `Missing required command: ${required}`);
  }
  plugin.commands.find((c) => c.id === "open-hot-cache").callback();
  plugin.commands.find((c) => c.id === "open-knowledge-base").callback();
  assert(opened.includes("00-导航/01-智能体热启动上下文"), "Hot cache command should open hot cache note");
  assert(opened.includes("00-导航/知识台账.base"), "Base ledger command should open .base file");
  console.log("knowledgeflow plugin smoke test: OK");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
