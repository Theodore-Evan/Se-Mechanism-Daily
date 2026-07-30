const THEME_STORAGE_KEY = "se-mechanism-theme";
const THEMES = new Set(["dark", "light", "eye"]);

const state = {
  data: { papers: [], topics: [], stats: {} },
  theme: "dark",
  filters: { query: "", topic: "all", level: "all", journal: "all", view: "daily", date: "" },
};

const nodes = {
  updatedAt: document.querySelector("#updatedAt"),
  paperCount: document.querySelector("#paperCount"),
  weekCount: document.querySelector("#weekCount"),
  monthCount: document.querySelector("#monthCount"),
  topScore: document.querySelector("#topScore"),
  resultCount: document.querySelector("#resultCount"),
  viewTitle: document.querySelector("#viewTitle"),
  listTitle: document.querySelector("#listTitle"),
  scopeLabel: document.querySelector("#scopeLabel"),
  paperList: document.querySelector("#paperList"),
  topicFilter: document.querySelector("#topicFilter"),
  levelFilter: document.querySelector("#levelFilter"),
  journalFilter: document.querySelector("#journalFilter"),
  dateFilter: document.querySelector("#dateFilter"),
  searchInput: document.querySelector("#searchInput"),
  themeOptions: document.querySelectorAll("[data-theme-option]"),
  tabs: document.querySelectorAll(".tab"),
  template: document.querySelector("#paperTemplate"),
  configureLink: document.querySelector("#configureLink"),
  actionsLink: document.querySelector("#actionsLink"),
  dataActionsButton: document.querySelector("#dataActionsButton"),
  dataActionsDialog: document.querySelector("#dataActionsDialog"),
  dataActionsClose: document.querySelector("#dataActionsClose"),
  refreshPapersLink: document.querySelector("#refreshPapersLink"),
  clearPapersLink: document.querySelector("#clearPapersLink"),
};

function repositoryUrl() {
  if (!window.location.hostname.endsWith(".github.io")) return "";
  const owner = window.location.hostname.slice(0, -".github.io".length);
  const repository = window.location.pathname.split("/").filter(Boolean)[0];
  return owner && repository ? `https://github.com/${owner}/${repository}` : "";
}

function configureRepositoryLinks() {
  const repository = repositoryUrl();
  if (!repository) {
    nodes.configureLink.hidden = true;
    nodes.actionsLink.hidden = true;
    nodes.dataActionsButton.hidden = true;
    return;
  }
  const workflowUrl = `${repository}/actions/workflows/update-literature.yml`;
  nodes.configureLink.href = `${repository}/issues/new?template=research-interests.md`;
  nodes.actionsLink.href = workflowUrl;
  nodes.refreshPapersLink.href = workflowUrl;
  nodes.clearPapersLink.href = workflowUrl;
}

function storedTheme() {
  try {
    const theme = localStorage.getItem(THEME_STORAGE_KEY);
    return THEMES.has(theme) ? theme : "dark";
  } catch {
    return "dark";
  }
}

function applyTheme(theme) {
  state.theme = THEMES.has(theme) ? theme : "dark";
  document.body.dataset.theme = state.theme;
  for (const option of nodes.themeOptions) {
    const active = option.dataset.themeOption === state.theme;
    option.classList.toggle("active", active);
    option.setAttribute("aria-checked", String(active));
  }
  try {
    localStorage.setItem(THEME_STORAGE_KEY, state.theme);
  } catch {
    // Some privacy modes disable local storage.
  }
}

function parseDate(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatDate(value) {
  const date = parseDate(value);
  if (!date) return value ? String(value).slice(0, 10) : "-";
  return date.toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" });
}

function dateKey(value) {
  const date = parseDate(value);
  if (!date) return "";
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function collectionTime(paper) {
  return paper.last_seen_at || paper.first_seen_at || paper.updated || paper.published || "";
}

function startOfDay(date) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

function startOfWeek(date) {
  const day = startOfDay(date);
  day.setDate(day.getDate() - ((day.getDay() + 6) % 7));
  return day;
}

function endOfWeek(date) {
  const end = startOfWeek(date);
  end.setDate(end.getDate() + 7);
  return end;
}

function startOfMonth(date) {
  return new Date(date.getFullYear(), date.getMonth(), 1);
}

function endOfMonth(date) {
  return new Date(date.getFullYear(), date.getMonth() + 1, 1);
}

function inRange(value, start, end) {
  const date = parseDate(value);
  return Boolean(date && date >= start && date < end);
}

function selectedDate() {
  return parseDate(`${state.filters.date}T12:00:00`) || new Date();
}

function scoreOf(paper) {
  return Number(paper.best_match?.score || 0);
}

function levelOf(paper) {
  return String(paper.best_match?.level || "low").toLowerCase();
}

function journalOf(paper) {
  return paper.journal_profile || {};
}

function matchesJournalFilter(paper) {
  const filter = state.filters.journal;
  if (filter === "all") return true;
  const journal = journalOf(paper);
  const family = String(journal.family || "").toLowerCase();
  const tier = String(journal.tier || "standard").toLowerCase();
  const quartile = String(journal.quartile || "").toLowerCase();
  if (filter === "cns") return tier === "flagship";
  if (["nature", "science", "cell"].includes(filter)) return family === filter;
  if (filter === "top") return tier === "top";
  if (["q1", "q2", "q3", "q4"].includes(filter)) return quartile === filter;
  if (filter === "unconfigured") {
    return typeof journal.impact_factor !== "number" || !journal.quartile;
  }
  return true;
}

function textIncludes(paper, query) {
  if (!query) return true;
  const haystack = [
    paper.title,
    paper.summary,
    (paper.authors || []).join(" "),
    (paper.categories || []).join(" "),
    paper.journal,
    paper.journal_profile?.name,
    (paper.journal_profile?.labels || []).join(" "),
    paper.best_match?.reason,
    ...Object.values(paper.chinese_summary || {}),
  ]
    .join(" ")
    .toLowerCase();
  return haystack.includes(query.toLowerCase());
}

function matchesFilters(paper) {
  if (!textIncludes(paper, state.filters.query)) return false;
  if (state.filters.topic !== "all" && paper.best_match?.topic_id !== state.filters.topic) return false;
  if (state.filters.level !== "all" && levelOf(paper) !== state.filters.level) return false;
  if (!matchesJournalFilter(paper)) return false;
  const date = selectedDate();
  const collectedAt = collectionTime(paper);
  if (state.filters.view === "daily") return dateKey(collectedAt) === state.filters.date;
  if (state.filters.view === "week") return inRange(collectedAt, startOfWeek(date), endOfWeek(date));
  if (state.filters.view === "month") return inRange(collectedAt, startOfMonth(date), endOfMonth(date));
  if (state.filters.view === "highlights") {
    return inRange(collectedAt, startOfWeek(date), endOfWeek(date)) && scoreOf(paper) >= 0.55;
  }
  return true;
}

function filteredPapers() {
  return (state.data.papers || [])
    .filter(matchesFilters)
    .sort((a, b) => scoreOf(b) - scoreOf(a) || String(b.published || "").localeCompare(String(a.published || "")));
}

function setText(parent, selector, text) {
  parent.querySelector(selector).textContent = text || "暂无";
}

function safeFilename(paper) {
  const title = String(paper.title || paper.id || "paper")
    .replace(/[\\/:*?"<>|]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 120);
  return `${title || "paper"}.pdf`;
}

function renderJournalDetails(node, paper) {
  const profile = journalOf(paper);
  const journalName = profile.name || paper.journal || "期刊待补充";
  const impactFactor = Number(profile.impact_factor);
  const hasImpactFactor = typeof profile.impact_factor === "number" && Number.isFinite(impactFactor);
  const metricYear = profile.metric_year ? ` · ${profile.metric_year}` : "";
  const quartileSystem = profile.quartile_system || "JCR";

  setText(node, ".journal-name", `期刊 · ${journalName}`);
  setText(node, ".journal-impact", hasImpactFactor ? `JIF ${impactFactor.toFixed(1)}${metricYear}` : "JIF 待配置");
  setText(
    node,
    ".journal-quartile",
    profile.quartile ? `${quartileSystem} ${profile.quartile}` : `${quartileSystem} 待配置`,
  );

  const source = profile.metric_source || state.data.stats?.journal_metric_source;
  const note = state.data.stats?.journal_metric_note || "期刊指标按年度变化，请以当年数据源为准。";
  node.querySelector(".journal-impact").title = source ? `${note}\n来源：${source}` : note;
  node.querySelector(".journal-quartile").title = note;

  const tier = node.querySelector(".journal-tier");
  const labels = profile.labels || [];
  tier.textContent = labels.join(" · ");
  tier.hidden = labels.length === 0;
  tier.classList.toggle("flagship", profile.tier === "flagship");
  tier.classList.toggle("nature", profile.family === "nature" && profile.tier !== "flagship");
  tier.classList.toggle("science", profile.family === "science" && profile.tier !== "flagship");
  tier.classList.toggle("cell", profile.family === "cell" && profile.tier !== "flagship");
  tier.classList.toggle("top", profile.tier === "top");
}

function renderPaper(paper) {
  const node = nodes.template.content.firstElementChild.cloneNode(true);
  const best = paper.best_match || {};
  const summary = paper.chinese_summary || {};
  const level = levelOf(paper);
  const badge = node.querySelector(".match-badge");
  badge.textContent = `${level} ${scoreOf(paper).toFixed(2)}`;
  badge.classList.add(level);

  const summaryStatus = node.querySelector(".summary-status");
  const hasAiSummary = paper.summary_engine === "ai";
  const provider = paper.summary_provider || state.data.stats?.ai_provider || "AI";
  summaryStatus.textContent = hasAiSummary ? `${provider} 摘要` : "基础摘要";
  summaryStatus.classList.toggle("ai", hasAiSummary);
  setText(node, ".paper-date", `发布 ${formatDate(paper.published)} · 收录 ${formatDate(collectionTime(paper))}`);
  setText(node, ".paper-source", paper.source || "文献源");
  setText(node, ".paper-title", paper.title);
  setText(node, ".paper-authors", (paper.authors || []).slice(0, 8).join(", "));
  renderJournalDetails(node, paper);
  setText(node, ".summary-problem", summary.problem);
  setText(node, ".summary-method", summary.method);
  setText(node, ".summary-innovation", summary.innovation);
  setText(node, ".summary-evidence", summary.evidence);
  setText(node, ".summary-limitations", summary.limitations);
  setText(node, ".summary-relevant", summary.why_relevant);
  setText(node, ".match-reason", `${best.topic_name || "未分类"}：${best.reason || ""}`);

  const tags = node.querySelector(".paper-tags");
  for (const category of (paper.categories || []).slice(0, 8)) {
    const tag = document.createElement("span");
    tag.className = "tag";
    tag.textContent = category;
    tags.appendChild(tag);
  }

  const originalUrl = paper.paper_url || "#";
  const pdfUrl = paper.pdf_url || originalUrl;
  node.querySelector(".abs-link").href = originalUrl;
  node.querySelector(".pdf-link").href = pdfUrl;
  const download = node.querySelector(".download-link");
  download.href = pdfUrl;
  download.setAttribute("download", safeFilename(paper));
  return node;
}

function viewLabels() {
  const date = selectedDate();
  const dayLabel = formatDate(date.toISOString());
  const weekStart = formatDate(startOfWeek(date).toISOString());
  const weekEndDate = endOfWeek(date);
  weekEndDate.setDate(weekEndDate.getDate() - 1);
  const weekEnd = formatDate(weekEndDate.toISOString());
  const monthLabel = `${date.getFullYear()} 年 ${String(date.getMonth() + 1).padStart(2, "0")} 月`;
  return {
    all: ["全部机制论文", "全部已收录论文"],
    daily: ["当日机制论文", dayLabel],
    week: ["本周机制论文", `${weekStart} - ${weekEnd}`],
    month: ["月度机制论文", monthLabel],
    highlights: ["本周机制精选", `${weekStart} - ${weekEnd}`],
  };
}

function updateHeadings(papers) {
  const labels = viewLabels()[state.filters.view];
  nodes.viewTitle.textContent = labels[0];
  nodes.listTitle.textContent = labels[0];
  nodes.scopeLabel.textContent = labels[1];
  nodes.resultCount.textContent = `${papers.length} 篇`;
}

function render() {
  const papers = filteredPapers();
  updateHeadings(papers);
  nodes.paperList.textContent = "";
  if (!papers.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "暂无符合条件的论文。首次自动更新完成后，结果会显示在这里。";
    nodes.paperList.appendChild(empty);
    return;
  }
  const fragment = document.createDocumentFragment();
  for (const paper of papers) fragment.appendChild(renderPaper(paper));
  nodes.paperList.appendChild(fragment);
}

function hydrateTopicFilter() {
  nodes.topicFilter.innerHTML = '<option value="all">全部方向</option>';
  for (const topic of state.data.topics || []) {
    const option = document.createElement("option");
    option.value = topic.id;
    option.textContent = topic.name;
    nodes.topicFilter.appendChild(option);
  }
}

function hydrateDateFilter() {
  const dates = [...new Set((state.data.papers || []).map((paper) => dateKey(collectionTime(paper))).filter(Boolean))]
    .sort()
    .reverse();
  const fallback = dateKey(state.data.generated_at_iso || new Date().toISOString());
  const options = dates.length ? dates : [fallback];
  state.filters.date = options[0];
  nodes.dateFilter.textContent = "";
  for (const key of options) {
    const option = document.createElement("option");
    option.value = key;
    option.textContent = formatDate(`${key}T12:00:00`);
    nodes.dateFilter.appendChild(option);
  }
}

function updateStats() {
  const papers = state.data.papers || [];
  const date = selectedDate();
  const week = papers.filter((paper) => inRange(collectionTime(paper), startOfWeek(date), endOfWeek(date)));
  const month = papers.filter((paper) => inRange(collectionTime(paper), startOfMonth(date), endOfMonth(date)));
  const top = papers.reduce((maximum, paper) => Math.max(maximum, scoreOf(paper)), 0);
  nodes.paperCount.textContent = String(papers.length);
  nodes.weekCount.textContent = String(week.length);
  nodes.monthCount.textContent = String(month.length);
  nodes.topScore.textContent = top.toFixed(2);
}

function updateUpdatedAt(message = "") {
  if (message) {
    nodes.updatedAt.textContent = message;
    return;
  }
  const stats = state.data.stats || {};
  const mode = stats.collection_mode === "incremental" ? "增量更新" : "重新生成";
  const aiCount = Number(stats.ai_summary_count || 0);
  const paperCount = Number(stats.paper_count || state.data.papers?.length || 0);
  const provider = stats.ai_provider || "AI";
  const summaryMode = aiCount > 0
    ? `${provider} 摘要 ${aiCount}/${paperCount}`
    : stats.ai_summary_enabled
      ? `${provider} 摘要待生成`
      : "基础摘要";
  nodes.updatedAt.textContent = `更新于 ${formatDate(state.data.generated_at_iso)} · ${mode} · ${summaryMode}`;
}

function bindEvents() {
  for (const option of nodes.themeOptions) {
    option.addEventListener("click", () => applyTheme(option.dataset.themeOption));
  }
  nodes.searchInput.addEventListener("input", (event) => {
    state.filters.query = event.target.value.trim();
    render();
  });
  nodes.topicFilter.addEventListener("change", (event) => {
    state.filters.topic = event.target.value;
    render();
  });
  nodes.levelFilter.addEventListener("change", (event) => {
    state.filters.level = event.target.value;
    render();
  });
  nodes.journalFilter.addEventListener("change", (event) => {
    state.filters.journal = event.target.value;
    render();
  });
  nodes.dateFilter.addEventListener("change", (event) => {
    state.filters.date = event.target.value;
    updateStats();
    render();
  });
  for (const tab of nodes.tabs) {
    tab.addEventListener("click", () => {
      state.filters.view = tab.dataset.view;
      for (const item of nodes.tabs) item.classList.toggle("active", item === tab);
      render();
    });
  }
  nodes.dataActionsButton.addEventListener("click", () => nodes.dataActionsDialog.showModal());
  nodes.dataActionsClose.addEventListener("click", () => nodes.dataActionsDialog.close());
  nodes.dataActionsDialog.addEventListener("click", (event) => {
    if (event.target === nodes.dataActionsDialog) nodes.dataActionsDialog.close();
  });
  for (const link of [nodes.refreshPapersLink, nodes.clearPapersLink]) {
    link.addEventListener("click", () => nodes.dataActionsDialog.close());
  }
}

async function main() {
  configureRepositoryLinks();
  applyTheme(storedTheme());
  bindEvents();
  try {
    const response = await fetch("./data/papers.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.data = await response.json();
  } catch (error) {
    updateUpdatedAt(`数据读取失败：${error.message}`);
  }
  updateUpdatedAt();
  hydrateTopicFilter();
  hydrateDateFilter();
  updateStats();
  render();
}

main();
