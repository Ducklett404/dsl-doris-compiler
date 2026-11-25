"use strict";

const examples = {
  basic: "indicator('', '', '收盘价', '2026-04-14', '', '', '') > 1 limit 0,100",
  history: "record_high('沪', '', '最高价', '历史', '2026-04-14', '', '', '') = True limit 0,100",
  ranking: [
    "indicator('沪', '', '收盘价', '2026-04-14', '', '', '') > 10",
    "and indicator('沪', '', '主力净流入', '2026-04-14', '', '', '') > 0",
    "then rank('沪', '', '涨跌幅', 'desc:row_number', '2026-04-14', '', '', '') <= 20",
    "limit 0,20"
  ].join("\n")
};
const $ = (id) => document.getElementById(id);
const tabs = [...document.querySelectorAll("[data-tab]")];
const panel = $("output-panel");
const elapsed = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 });
let service = null;
let pending = null;
let compiled = null;
let result = null;
let active = "result";

function create(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function button(text, onClick) {
  const node = create("button", text, "button secondary");
  node.type = "button";
  node.addEventListener("click", onClick);
  return node;
}

function feedback(message, error = false) {
  $("feedback").textContent = message;
  $("feedback").classList.toggle("error", error);
}

function refreshControls() {
  $("compile").disabled = !service || pending !== null;
  $("run").disabled = !service?.executionEnabled || pending !== null;
}

function changeTab(name) {
  active = name;
  for (const tab of tabs) {
    const selected = tab.dataset.tab === name;
    tab.tabIndex = selected ? 0 : -1;
    tab.setAttribute("aria-selected", String(selected));
  }
  panel.setAttribute("aria-labelledby", "tab-" + name);
  render();
}

function clearArtifacts() {
  pending?.abort();
  pending = null;
  compiled = null;
  result = null;
  refreshControls();
  feedback("");
  render();
}

function selectExample() {
  $("dsl").value = examples[$("example").value];
  clearArtifacts();
  changeTab("result");
}

function markdownCell(value) {
  return String(value ?? "NULL")
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
    .replaceAll("\\", "\\\\").replaceAll("|", "\\|").replace(/\r\n?|\n/g, "<br>");
}

function exportMarkdown(execution) {
  const tableRow = (values) => "| " + values.map(markdownCell).join(" | ") + " |";
  const lines = [
    "# Doris 查询结果",
    "",
    "快照 " + execution.dataVersion.snapshotId,
    "返回 " + execution.rows.length + " 行" + (execution.truncated ? "（达到结果上限）" : ""),
    "",
    tableRow(execution.columns),
    tableRow(execution.columns.map(() => "---")),
    ...execution.rows.map(tableRow)
  ];
  const url = URL.createObjectURL(new Blob([lines.join("\n") + "\n"], { type: "text/markdown;charset=utf-8" }));
  const download = create("a");
  download.href = url;
  download.download = "Doris-查询结果.md";
  document.body.append(download);
  download.click();
  download.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function showResults(execution) {
  const counts = create("div", undefined, "result-info");
  counts.append(create("strong", elapsed.format(execution.rows.length) + " 行"),
    create("span", "总耗时 " + elapsed.format(execution.timings.totalMillis) + " ms", "output-note"));
  if (execution.truncated) counts.append(create("span", "已达到结果上限", "output-note"));
  const quality = execution.dataQuality;
  if (quality) {
    const coverage = {
      NO_OBSERVATIONS: "无行情",
      PARTIAL_INPUTS: "部分输入缺失",
      COMPLETE_QUERY_INPUTS: "查询输入完整"
    };
    counts.append(create("span", coverage[quality.coverageStatus] ?? quality.coverageStatus, "output-note"));
  }
  panel.append(counts);

  const tools = create("div", undefined, "output-tools");
  const search = create("input", undefined, "search");
  search.type = "search";
  search.placeholder = "搜索返回结果";
  search.setAttribute("aria-label", "搜索返回结果");
  tools.append(search, button("导出 Markdown", () => exportMarkdown(execution)));
  panel.append(tools);

  const scroll = create("div", undefined, "table-wrap");
  scroll.tabIndex = 0;
  scroll.setAttribute("role", "region");
  scroll.setAttribute("aria-label", "Doris 返回结果");
  const table = create("table");
  const heading = table.createTHead().insertRow();
  for (const name of execution.columns) {
    const th = create("th", name);
    th.scope = "col";
    heading.append(th);
  }
  const body = table.createTBody();
  function fillRows() {
    const term = search.value.toLowerCase().trim();
    const rows = execution.rows.filter((row) => row.some((value) => String(value ?? "").toLowerCase().includes(term)));
    const fragment = document.createDocumentFragment();
    for (const values of rows) {
      const tr = create("tr");
      for (const value of values) tr.append(create("td", value ?? "NULL"));
      fragment.append(tr);
    }
    if (rows.length === 0) {
      const tr = create("tr");
      const cell = create("td", term ? "没有匹配结果。" : "Doris 返回了空结果。");
      cell.colSpan = Math.max(execution.columns.length, 1);
      tr.append(cell);
      fragment.append(tr);
    }
    body.replaceChildren(fragment);
  }
  search.addEventListener("input", fillRows);
  fillRows();
  scroll.append(table);
  panel.append(scroll);
}

function showCode(text, label) {
  const toolbar = create("div", undefined, "output-tools");
  const copy = button("复制", async () => {
    try {
      await navigator.clipboard.writeText(text);
      copy.textContent = "已复制";
    } catch {
      copy.textContent = "请手动复制";
    }
  });
  toolbar.append(create("span", label, "output-note"), copy);
  const code = create("pre", text, "code");
  code.tabIndex = 0;
  panel.append(toolbar, code);
}

function render() {
  panel.replaceChildren();
  const badge = $("output-tag");
  badge.hidden = !result && !compiled;
  badge.textContent = result ? "Doris 实时执行" : "已编译";
  $("output-summary").textContent = result ? "快照 " + result.dataVersion.snapshotId
    : compiled ? "已由当前项目编译器生成。" : "执行查询后在这里查看 Doris 返回。";

  if (active === "result") {
    if (result) showResults(result);
    else panel.append(create("p", service?.executionEnabled ? "执行查询后，Doris 返回的证券列表将显示在这里。"
      : "当前以编译模式运行。使用 serve-doris 并连接 Doris 后可执行查询。", "empty"));
    return;
  }
  if (!compiled) {
    panel.append(create("p", "编译 DSL 后可查看这一产物。", "empty"));
    return;
  }
  switch (active) {
    case "sql":
      showCode(compiled.sql + "\n\n-- 绑定参数\n" + JSON.stringify(compiled.bindings, null, 2),
        result ? "本次查询执行的 SQL" : "项目编译器生成的 SQL");
      break;
    case "ast":
      showCode(JSON.stringify(compiled.semanticModel.document, null, 2), "类型化 AST");
      break;
    case "plan":
      showCode(result?.explain.length ? result.explain.join("\n") : JSON.stringify(compiled.logicalPlan, null, 2),
        result?.explain.length ? "Doris EXPLAIN" : "编译器逻辑计划");
      break;
  }
}

async function submit(execute) {
  const token = $("token").value.trim();
  const dsl = $("dsl").value.trim();
  const snapshot = $("snapshot").value.trim();
  if (!token || !dsl || (execute && !snapshot)) {
    const missing = !token ? $("token") : !dsl ? $("dsl") : $("snapshot");
    feedback("请填写" + missing.labels[0].textContent + "。", true);
    missing.focus();
    return;
  }
  clearArtifacts();
  const request = new AbortController();
  pending = request;
  refreshControls();
  feedback(execute ? "正在通过 Doris 执行查询…" : "正在编译 DSL…");
  try {
    const response = await fetch(execute ? "/execute" : "/compile-sql", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: "Bearer " + token },
      body: JSON.stringify(execute ? { dsl, snapshotId: snapshot, maxRows: Number($("max-rows").value) } : { dsl }),
      signal: request.signal,
      cache: "no-store"
    });
    const value = await response.json();
    if (!response.ok) {
      const location = value.line ? "（第 " + value.line + " 行，第 " + value.column + " 列）" : "";
      throw new Error(response.status === 401 ? "HTTP 令牌无效，请确认与服务配置一致。"
        : (value.message ?? value.error ?? "请求失败。") + location);
    }
    if (pending !== request) return;
    if (execute) result = value;
    compiled = execute ? value.compilation : value;
    changeTab(execute ? "result" : "sql");
    feedback(execute ? "Doris 查询完成。" : "编译完成。");
  } catch (error) {
    if (pending === request) feedback(error.message, true);
  } finally {
    if (pending === request) {
      pending = null;
      refreshControls();
    }
  }
}

for (const [index, tab] of tabs.entries()) {
  tab.addEventListener("click", () => changeTab(tab.dataset.tab));
  tab.addEventListener("keydown", (event) => {
    const positions = { ArrowLeft: (index + tabs.length - 1) % tabs.length, ArrowRight: (index + 1) % tabs.length,
      Home: 0, End: tabs.length - 1 };
    if (!Object.hasOwn(positions, event.key)) return;
    event.preventDefault();
    const next = tabs[positions[event.key]];
    changeTab(next.dataset.tab);
    next.focus();
  });
}
$("compile").addEventListener("click", () => submit(false));
$("run").addEventListener("click", () => submit(true));
$("example").addEventListener("change", selectExample);
for (const id of ["dsl", "snapshot", "max-rows"]) $(id).addEventListener("input", clearArtifacts);

selectExample();
fetch("/workbench/status", { cache: "no-store" }).then((response) => {
  if (!response.ok) throw new Error("服务状态不可用");
  return response.json();
}).then((mode) => {
  service = mode;
  const status = $("service-state");
  status.textContent = mode.executionEnabled ? "Doris 执行已启用" : "仅编译";
  status.classList.toggle("connected", mode.executionEnabled);
  refreshControls();
  render();
}).catch(() => {
  $("service-state").textContent = "服务不可用";
  feedback("无法读取服务状态，请确认 Java 服务已启动。", true);
});
