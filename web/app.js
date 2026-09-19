const THEME_STORAGE_KEY = "se-mechanism-theme";
const DRAFT_STORAGE_KEY = "se-mechanism-config-draft-v2";
const backend = window.SeBackend || { enabled: () => false, requireAuth: false };

const PROVIDERS = {
  zhipu: { name: "智谱 GLM", base_url: "https://open.bigmodel.cn/api/paas/v4", model: "glm-4-flash-250414", secret: "ZHIPU_API_KEY" },
  gemini: { name: "Gemini", base_url: "https://generativelanguage.googleapis.com/v1beta/openai", model: "gemini-2.5-flash", secret: "GEMINI_API_KEY" },
  openai: { name: "OpenAI", base_url: "https://api.openai.com/v1", model: "gpt-4o-mini", secret: "OPENAI_API_KEY" },
  deepseek: { name: "DeepSeek", base_url: "https://api.deepseek.com", model: "deepseek-chat", secret: "DEEPSEEK_API_KEY" },
  custom: { name: "自定义 API", base_url: "", model: "", secret: "CUSTOM_LLM_API_KEY" },
};

const AVAILABLE_SOURCES = [
  { type: "pubmed", name: "PubMed" },
  { type: "google_scholar_serpapi", name: "Google Scholar" },
  { type: "openalex", name: "OpenAlex" },
  { type: "crossref", name: "Crossref" },
  { type: "arxiv", name: "arXiv" },
];

const state = {
  data: { papers: [], topics: [], sources: [], stats: {}, runtime: {} },
  filters: { query: "", topic: "all", level: "all", journal: "all", view: "date", date: "" },
  theme: "dark",
  account: { user: null, credentials: [] },
};

const nodes = {
  sidebar: document.querySelector("#sidebar"),
  sidebarScrim: document.querySelector("#sidebarScrim"),
  sidebarToggle: document.querySelector("#sidebarToggle"),
  dateNavigation: document.querySelector("#dateNavigation"),
  dateCount: document.querySelector("#dateCount"),
  allCount: document.querySelector("#allCount"),
  highlightCount: document.querySelector("#highlightCount"),
  configSource: document.querySelector("#configSource"),
  updatedAt: document.querySelector("#updatedAt"),
  viewTitle: document.querySelector("#viewTitle"),
  listTitle: document.querySelector("#listTitle"),
  scopeLabel: document.querySelector("#scopeLabel"),
  resultCount: document.querySelector("#resultCount"),
  paperCount: document.querySelector("#paperCount"),
  selectedCount: document.querySelector("#selectedCount"),
  aiCount: document.querySelector("#aiCount"),
  topScore: document.querySelector("#topScore"),
  paperList: document.querySelector("#paperList"),
  topicFilter: document.querySelector("#topicFilter"),
  levelFilter: document.querySelector("#levelFilter"),
  journalFilter: document.querySelector("#journalFilter"),
  searchInput: document.querySelector("#searchInput"),
  paperTemplate: document.querySelector("#paperTemplate"),
  topicEditorTemplate: document.querySelector("#topicEditorTemplate"),
  themeButton: document.querySelector("#themeButton"),
  accountButton: document.querySelector("#accountButton"),
  accountLabel: document.querySelector("#accountLabel"),
  openSettingsButton: document.querySelector("#openSettingsButton"),
  headerSettingsButton: document.querySelector("#headerSettingsButton"),
  settingsDialog: document.querySelector("#settingsDialog"),
  settingsClose: document.querySelector("#settingsClose"),
  providerSelect: document.querySelector("#providerSelect"),
  modelInput: document.querySelector("#modelInput"),
  baseUrlInput: document.querySelector("#baseUrlInput"),
  secretName: document.querySelector("#secretName"),
  secretStatus: document.querySelector("#secretStatus"),
  secretsLink: document.querySelector("#secretsLink"),
  apiKeyInput: document.querySelector("#apiKeyInput"),
  saveApiKeyButton: document.querySelector("#saveApiKeyButton"),
  sourceEditor: document.querySelector("#sourceEditor"),
  lookbackInput: document.querySelector("#lookbackInput"),
  dateFromInput: document.querySelector("#dateFromInput"),
  dateToInput: document.querySelector("#dateToInput"),
  maxPerTopicInput: document.querySelector("#maxPerTopicInput"),
  maxSummariesInput: document.querySelector("#maxSummariesInput"),
  maxPapersInput: document.querySelector("#maxPapersInput"),
  serpApiKeyInput: document.querySelector("#serpApiKeyInput"),
  saveSerpApiKeyButton: document.querySelector("#saveSerpApiKeyButton"),
  serpApiStatus: document.querySelector("#serpApiStatus"),
  serpApiCard: document.querySelector("#serpApiCard"),
  topicEditor: document.querySelector("#topicEditor"),
  addTopicButton: document.querySelector("#addTopicButton"),
  copyConfigButton: document.querySelector("#copyConfigButton"),
  saveDraftButton: document.querySelector("#saveDraftButton"),
  applyConfigButton: document.querySelector("#applyConfigButton"),
  settingsMessage: document.querySelector("#settingsMessage"),
  dataActionsButton: document.querySelector("#dataActionsButton"),
  dataActionsDialog: document.querySelector("#dataActionsDialog"),
  dataActionsClose: document.querySelector("#dataActionsClose"),
  refreshPapersLink: document.querySelector("#refreshPapersLink"),
  clearPapersLink: document.querySelector("#clearPapersLink"),
  runModeLabel: document.querySelector("#runModeLabel"),
  runModeDescription: document.querySelector("#runModeDescription"),
  authGate: document.querySelector("#authGate"),
  authForm: document.querySelector("#authForm"),
  authEmail: document.querySelector("#authEmail"),
  authPassword: document.querySelector("#authPassword"),
  authSubmit: document.querySelector("#authSubmit"),
  authSwitch: document.querySelector("#authSwitch"),
  authTitle: document.querySelector("#authTitle"),
  authMessage: document.querySelector("#authMessage"),
  toast: document.querySelector("#toast"),
};

let authMode = "signin";

function repositoryUrl() {
  if (!window.location.hostname.endsWith(".github.io")) return "";
  const owner = window.location.hostname.slice(0, -".github.io".length);
  const repository = window.location.pathname.split("/").filter(Boolean)[0];
  return owner && repository ? `https://github.com/${owner}/${repository}` : "";
}

function configureRepositoryLinks() {
  const repository = repositoryUrl();
  if (!repository) return;
  const workflow = `${repository}/actions/workflows/update-literature.yml`;
  nodes.refreshPapersLink.href = workflow;
  nodes.clearPapersLink.href = workflow;
  nodes.secretsLink.href = `${repository}/settings/secrets/actions`;
}

function parseDate(value) {
  if (!value) return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function dateKey(value) {
  const date = parseDate(value);
  if (!date) return "";
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function formatDate(value, withYear = true) {
  const date = parseDate(value);
  if (!date) return value || "-";
  const options = withYear ? { year: "numeric", month: "2-digit", day: "2-digit" } : { month: "2-digit", day: "2-digit" };
  return date.toLocaleDateString("zh-CN", options);
}

function firstSeen(paper) {
  return paper.first_seen_at || paper.last_seen_at || paper.updated || paper.published || "";
}

function collectionDates(paper) {
  return paper.collection_dates?.length ? paper.collection_dates : [dateKey(firstSeen(paper))];
}

function scoreOf(paper) { return Number(paper.best_match?.score || 0); }
function levelOf(paper) { return String(paper.best_match?.level || "low").toLowerCase(); }
function journalOf(paper) { return paper.journal_profile || {}; }

function startOfWeek(date) {
  const start = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  start.setDate(start.getDate() - ((start.getDay() + 6) % 7));
  return start;
}

function endOfWeek(date) {
  const end = startOfWeek(date);
  end.setDate(end.getDate() + 7);
  return end;
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
  if (filter === "unconfigured") return typeof journal.impact_factor !== "number" || !journal.quartile;
  return true;
}

function matchesText(paper, query) {
  if (!query) return true;
  const values = [paper.title, paper.summary, (paper.authors || []).join(" "), (paper.categories || []).join(" "), paper.journal, paper.journal_profile?.name, paper.best_match?.reason, ...Object.values(paper.chinese_summary || {})];
  return values.join(" ").toLowerCase().includes(query.toLowerCase());
}

function matchesView(paper) {
  if (state.filters.view === "all") return true;
  if (state.filters.view === "date") return collectionDates(paper).includes(state.filters.date);
  if (state.filters.view === "highlights") {
    const newest = parseDate(`${newestDateKey()}T12:00:00`) || new Date();
    const seen = parseDate(firstSeen(paper));
    return Boolean(seen && seen >= startOfWeek(newest) && seen < endOfWeek(newest) && scoreOf(paper) >= 0.55);
  }
  return true;
}

function filteredPapers() {
  return (state.data.papers || [])
    .filter(matchesView)
    .filter((paper) => matchesText(paper, state.filters.query))
    .filter((paper) => state.filters.topic === "all" || paper.best_match?.topic_id === state.filters.topic)
    .filter((paper) => state.filters.level === "all" || levelOf(paper) === state.filters.level)
    .filter(matchesJournalFilter)
    .sort((a, b) => scoreOf(b) - scoreOf(a) || String(b.published || "").localeCompare(String(a.published || "")));
}

function dateGroups() {
  const counts = new Map();
  for (const paper of state.data.papers || []) {
    for (const key of collectionDates(paper)) {
      if (key) counts.set(key, (counts.get(key) || 0) + 1);
    }
  }
  return [...counts.entries()].sort(([a], [b]) => b.localeCompare(a));
}

function newestDateKey() { return dateGroups()[0]?.[0] || dateKey(state.data.generated_at_iso || new Date()); }

function setText(parent, selector, text) { parent.querySelector(selector).textContent = text || "暂无"; }

function safeFilename(paper) {
  const title = String(paper.title || paper.id || "paper").replace(/[\\/:*?"<>|]+/g, " ").replace(/\s+/g, " ").trim().slice(0, 120);
  return `${title || "paper"}.pdf`;
}

function renderJournal(node, paper) {
  const profile = journalOf(paper);
  const name = profile.name || paper.journal || "期刊待补充";
  const impact = Number(profile.impact_factor);
  const hasImpact = typeof profile.impact_factor === "number" && Number.isFinite(impact);
  setText(node, ".journal-name", `期刊 · ${name}`);
  setText(node, ".journal-impact", hasImpact ? `JIF ${impact.toFixed(1)}${profile.metric_year ? ` · ${profile.metric_year}` : ""}` : "JIF 待配置");
  setText(node, ".journal-quartile", profile.quartile ? `${profile.quartile_system || "JCR"} ${profile.quartile}` : `${profile.quartile_system || "JCR"} 待配置`);
  const source = profile.metric_source || state.data.stats?.journal_metric_source;
  const note = state.data.stats?.journal_metric_note || "期刊指标按年度变化，请以当年数据源为准。";
  node.querySelector(".journal-impact").title = source ? `${note}\n来源：${source}` : note;
  const tier = node.querySelector(".journal-tier");
  tier.textContent = (profile.labels || []).join(" · ");
  tier.hidden = !(profile.labels || []).length;
}

function renderPaper(paper) {
  const node = nodes.paperTemplate.content.firstElementChild.cloneNode(true);
  const best = paper.best_match || {};
  const summary = paper.chinese_summary || {};
  const level = levelOf(paper);
  const badge = node.querySelector(".match-badge");
  badge.textContent = `${level} ${scoreOf(paper).toFixed(2)}`;
  badge.classList.add(level);
  const summaryStatus = node.querySelector(".summary-status");
  const hasAi = paper.summary_engine === "ai";
  summaryStatus.textContent = hasAi ? `${paper.summary_provider || state.data.stats?.ai_provider || "AI"} 摘要` : "基础摘要";
  summaryStatus.classList.toggle("ai", hasAi);
  setText(node, ".paper-date", `发布 ${formatDate(paper.published)} · 首次抓取 ${formatDate(firstSeen(paper))}`);
  setText(node, ".paper-source", paper.source || "文献源");
  setText(node, ".paper-title", paper.title);
  setText(node, ".paper-authors", (paper.authors || []).slice(0, 10).join(", "));
  renderJournal(node, paper);
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

function renderDateNavigation() {
  const groups = dateGroups();
  nodes.dateNavigation.textContent = "";
  nodes.dateCount.textContent = `${groups.length} 天`;
  nodes.allCount.textContent = String(state.data.papers?.length || 0);
  const newest = parseDate(`${newestDateKey()}T12:00:00`) || new Date();
  const highlights = (state.data.papers || []).filter((paper) => {
    const seen = parseDate(firstSeen(paper));
    return seen && seen >= startOfWeek(newest) && seen < endOfWeek(newest) && scoreOf(paper) >= 0.55;
  });
  nodes.highlightCount.textContent = String(highlights.length);
  let currentMonth = "";
  for (const [key, count] of groups) {
    const month = key.slice(0, 7);
    if (month !== currentMonth) {
      currentMonth = month;
      const heading = document.createElement("div");
      heading.className = "date-group";
      heading.textContent = `${key.slice(0, 4)} 年 ${key.slice(5, 7)} 月`;
      nodes.dateNavigation.appendChild(heading);
    }
    const button = document.createElement("button");
    button.className = "date-item";
    button.type = "button";
    button.dataset.date = key;
    button.innerHTML = `<span class="date-label">${formatDate(`${key}T12:00:00`, false)}</span><span class="date-count">${count}</span>`;
    button.addEventListener("click", () => selectDate(key));
    nodes.dateNavigation.appendChild(button);
  }
}

function viewCopy() {
  if (state.filters.view === "all") return ["全部文献", "所有已收录的硒机制论文"];
  if (state.filters.view === "highlights") return ["本周精选", "按匹配度筛选的本周重点论文"];
  return ["每日抓取", formatDate(`${state.filters.date}T12:00:00`)];
}

function updateActiveNavigation() {
  document.querySelectorAll("[data-view]").forEach((button) => button.classList.toggle("active", button.dataset.view === state.filters.view));
  document.querySelectorAll("[data-date]").forEach((button) => button.classList.toggle("active", state.filters.view === "date" && button.dataset.date === state.filters.date));
}

function updateStatus(papers) {
  const copy = viewCopy();
  nodes.viewTitle.textContent = copy[0];
  nodes.listTitle.textContent = copy[0];
  nodes.scopeLabel.textContent = copy[1];
  nodes.resultCount.textContent = `${papers.length} 篇`;
  nodes.paperCount.textContent = String(state.data.papers?.length || 0);
  nodes.selectedCount.textContent = String(papers.length);
  nodes.aiCount.textContent = String((state.data.papers || []).filter((paper) => paper.summary_engine === "ai").length);
  nodes.topScore.textContent = (state.data.papers || []).reduce((maximum, paper) => Math.max(maximum, scoreOf(paper)), 0).toFixed(2);
}

function render() {
  const papers = filteredPapers();
  updateActiveNavigation();
  updateStatus(papers);
  nodes.paperList.textContent = "";
  if (!papers.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "当前日期或筛选条件下没有文献。";
    nodes.paperList.appendChild(empty);
    return;
  }
  const fragment = document.createDocumentFragment();
  for (const paper of papers) fragment.appendChild(renderPaper(paper));
  nodes.paperList.appendChild(fragment);
}

function selectDate(key) {
  state.filters.view = "date";
  state.filters.date = key;
  document.body.classList.remove("sidebar-open");
  render();
}

function selectView(view) {
  state.filters.view = view;
  document.body.classList.remove("sidebar-open");
  render();
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

function updateGeneratedStatus(message = "") {
  if (message) { nodes.updatedAt.textContent = message; return; }
  const stats = state.data.stats || {};
  const runtime = state.data.runtime || {};
  if (backend.enabled() && !state.data.generated_at_iso) {
    nodes.updatedAt.textContent = "个人空间已建立 · 尚未完成首次抓取";
    nodes.configSource.textContent = "账号独立配置";
    return;
  }
  const mode = stats.collection_mode === "incremental" ? "增量更新" : "重新生成";
  const provider = runtime.provider_name || stats.ai_provider || "AI";
  nodes.updatedAt.textContent = `更新于 ${formatDate(state.data.generated_at_iso)} · ${mode} · ${provider} 摘要 ${Number(stats.ai_summary_count || 0)}/${Number(stats.paper_count || state.data.papers?.length || 0)}`;
  if (backend.enabled()) nodes.configSource.textContent = "账号独立配置 · 数据隔离";
  else nodes.configSource.textContent = String(state.data.config_source || "repository").startsWith("issue") ? `Issue 配置 · ${state.data.config_source}` : "仓库默认配置";
}

function storedTheme() {
  try { return localStorage.getItem(THEME_STORAGE_KEY) === "light" ? "light" : "dark"; } catch { return "dark"; }
}

function applyTheme(theme) {
  state.theme = theme === "light" ? "light" : "dark";
  document.body.dataset.theme = state.theme;
  try { localStorage.setItem(THEME_STORAGE_KEY, state.theme); } catch { /* unavailable */ }
}

function showToast(message) {
  nodes.toast.textContent = message;
  nodes.toast.classList.add("visible");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => nodes.toast.classList.remove("visible"), 2600);
}

function liveConfig() {
  const runtime = state.data.runtime || {};
  return {
    sources: (state.data.sources?.length ? state.data.sources : AVAILABLE_SOURCES).map((source) => ({ type: source.type, name: source.name })),
    topics: (state.data.topics || []).map((topic) => ({
      id: topic.id,
      name: topic.name,
      description: topic.description || "",
      keywords: [...(topic.keywords || [])],
      arxiv_categories: [...(topic.arxiv_categories || ["q-bio.BM", "q-bio.CB"])],
    })),
    runtime: {
      provider: runtime.provider || "zhipu",
      provider_name: runtime.provider_name || PROVIDERS[runtime.provider || "zhipu"]?.name || "AI",
      base_url: runtime.base_url || PROVIDERS[runtime.provider || "zhipu"]?.base_url || "",
      model: runtime.model || PROVIDERS[runtime.provider || "zhipu"]?.model || "",
      lookback_days: Number(runtime.lookback_days || 7),
      date_from: runtime.date_from || "",
      date_to: runtime.date_to || "",
      max_per_topic: Number(runtime.max_per_topic || 10),
      max_summaries: Number(runtime.max_summaries || 12),
      max_new_papers: Number(runtime.max_new_papers || 50),
      max_stored_papers: Number(runtime.max_stored_papers || 500),
      min_match_score: Number(runtime.min_match_score || 0.12),
    },
  };
}

function savedDraft() {
  if (backend.enabled()) return null;
  try { return JSON.parse(localStorage.getItem(DRAFT_STORAGE_KEY) || "null"); } catch { return null; }
}

function renderSources(selectedSources) {
  const selected = new Set((selectedSources || []).map((source) => source.type));
  nodes.sourceEditor.textContent = "";
  for (const source of AVAILABLE_SOURCES) {
    const label = document.createElement("label");
    label.className = "source-option";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.value = source.type;
    input.dataset.name = source.name;
    input.checked = selected.has(source.type);
    label.append(input, document.createTextNode(source.name));
    nodes.sourceEditor.appendChild(label);
  }
}

function addTopicEditor(topic = {}) {
  const card = nodes.topicEditorTemplate.content.firstElementChild.cloneNode(true);
  card.querySelector(".topic-name").value = topic.name || "新研究方向";
  card.querySelector(".topic-id").value = topic.id || `topic_${Date.now()}`;
  card.querySelector(".topic-description").value = topic.description || "";
  card.querySelector(".topic-keywords").value = (topic.keywords || []).join("\n");
  card.dataset.categories = JSON.stringify(topic.arxiv_categories || ["q-bio.BM", "q-bio.CB"]);
  card.querySelector(".remove-topic").addEventListener("click", () => {
    card.remove();
    renumberTopics();
  });
  nodes.topicEditor.appendChild(card);
  renumberTopics();
}

function renumberTopics() {
  [...nodes.topicEditor.children].forEach((card, index) => { card.querySelector(".topic-number").textContent = `方向 ${index + 1}`; });
}

function updateProviderUi({ usePreset = false } = {}) {
  const provider = nodes.providerSelect.value;
  const preset = PROVIDERS[provider] || PROVIDERS.custom;
  if (usePreset) {
    nodes.baseUrlInput.value = preset.base_url;
    nodes.modelInput.value = preset.model;
  }
  nodes.secretName.textContent = preset.secret;
  if (backend.enabled()) {
    const credential = state.account.credentials.find((item) => item.provider === provider);
    nodes.secretStatus.textContent = credential ? `已加密保存 · 尾号 ${credential.key_last4}` : "尚未为此账号配置";
    nodes.secretsLink.hidden = true;
    nodes.apiKeyInput.hidden = false;
    nodes.saveApiKeyButton.hidden = false;
    const serpApi = state.account.credentials.find((item) => item.provider === "serpapi");
    nodes.serpApiStatus.textContent = serpApi ? `已加密保存 · 尾号 ${serpApi.key_last4}` : "Google Scholar 需要此密钥";
    nodes.serpApiCard.hidden = false;
    return;
  }
  nodes.secretsLink.hidden = false;
  nodes.apiKeyInput.hidden = true;
  nodes.saveApiKeyButton.hidden = true;
  nodes.serpApiKeyInput.hidden = true;
  nodes.saveSerpApiKeyButton.hidden = true;
  nodes.serpApiCard.hidden = true;
  const runtime = state.data.runtime || {};
  const matchesLiveProvider = runtime.provider === provider;
  if (matchesLiveProvider && runtime.secret_configured === true) nodes.secretStatus.textContent = "GitHub Secret 已配置";
  else if (matchesLiveProvider && runtime.secret_configured === false) nodes.secretStatus.textContent = "尚未检测到密钥";
  else nodes.secretStatus.textContent = `切换后请在 GitHub 中配置 ${preset.secret}`;
}

function fillSettings(config) {
  const runtime = config.runtime || {};
  nodes.providerSelect.value = PROVIDERS[runtime.provider] ? runtime.provider : "custom";
  nodes.baseUrlInput.value = runtime.base_url || "";
  nodes.modelInput.value = runtime.model || "";
  nodes.lookbackInput.value = runtime.lookback_days || 7;
  nodes.dateFromInput.value = runtime.date_from || "";
  nodes.dateToInput.value = runtime.date_to || "";
  nodes.maxPerTopicInput.value = runtime.max_per_topic || 10;
  nodes.maxSummariesInput.value = runtime.max_summaries ?? 12;
  nodes.maxPapersInput.value = runtime.max_stored_papers || 500;
  renderSources(config.sources);
  nodes.topicEditor.textContent = "";
  for (const topic of config.topics || []) addTopicEditor(topic);
  updateProviderUi();
}

function openSettings() {
  fillSettings(savedDraft() || liveConfig());
  nodes.settingsMessage.textContent = backend.enabled()
    ? "当前显示你的个人配置；保存不会影响其他账号。"
    : savedDraft() ? "已载入这个浏览器中的未提交草稿。" : "当前显示线上正在使用的配置。";
  nodes.settingsDialog.showModal();
}

function numberValue(input, fallback) {
  const value = Number(input.value);
  return Number.isFinite(value) ? value : fallback;
}

function readSettings() {
  const sources = [...nodes.sourceEditor.querySelectorAll("input:checked")].map((input) => ({ type: input.value, name: input.dataset.name }));
  const topics = [...nodes.topicEditor.querySelectorAll(".topic-config-card")].map((card) => ({
    id: card.querySelector(".topic-id").value.trim(),
    name: card.querySelector(".topic-name").value.trim(),
    description: card.querySelector(".topic-description").value.trim(),
    keywords: card.querySelector(".topic-keywords").value.split(/\r?\n/).map((value) => value.trim()).filter(Boolean),
    arxiv_categories: JSON.parse(card.dataset.categories || "[]"),
  }));
  const provider = nodes.providerSelect.value;
  const preset = PROVIDERS[provider] || PROVIDERS.custom;
  return {
    sources,
    topics,
    runtime: {
      provider,
      provider_name: preset.name,
      base_url: nodes.baseUrlInput.value.trim().replace(/\/$/, ""),
      model: nodes.modelInput.value.trim(),
      lookback_days: numberValue(nodes.lookbackInput, 7),
      date_from: nodes.dateFromInput.value,
      date_to: nodes.dateToInput.value,
      max_per_topic: numberValue(nodes.maxPerTopicInput, 10),
      max_summaries: numberValue(nodes.maxSummariesInput, 12),
      max_new_papers: Number(state.data.runtime?.max_new_papers || 50),
      max_stored_papers: numberValue(nodes.maxPapersInput, 500),
      min_match_score: Number(state.data.runtime?.min_match_score || 0.12),
    },
  };
}

function validateSettings(config) {
  if (!config.sources.length) throw new Error("至少选择一个文献来源。");
  if (!config.topics.length) throw new Error("至少保留一个研究方向。");
  for (const topic of config.topics) {
    if (!topic.id || !topic.name) throw new Error("每个研究方向都需要名称和稳定 ID。");
    if (!topic.keywords.length) throw new Error(`“${topic.name}”至少需要一个关键词。`);
  }
  if (!config.runtime.base_url.startsWith("https://")) throw new Error("API Base URL 必须以 https:// 开头。");
  if (!config.runtime.model) throw new Error("请填写模型名称。");
  if (config.runtime.date_from && config.runtime.date_to && config.runtime.date_from > config.runtime.date_to) throw new Error("起始日期不能晚于结束日期。");
  return config;
}

async function copyText(text) {
  if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(text);
  const textarea = document.createElement("textarea");
  textarea.value = text;
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand("copy");
  textarea.remove();
}

function configJson() { return JSON.stringify(validateSettings(readSettings()), null, 2); }

async function copyConfiguration() {
  try { await copyText(configJson()); showToast("配置 JSON 已复制"); }
  catch (error) { showToast(error.message || "复制失败"); }
}

function applyConfigToState(config) {
  state.data.sources = config.sources || [];
  state.data.topics = config.topics || [];
  state.data.runtime = { ...(state.data.runtime || {}), ...(config.runtime || {}) };
  hydrateTopicFilter();
  updateGeneratedStatus();
  render();
}

async function saveDraft() {
  try {
    const config = validateSettings(readSettings());
    if (backend.enabled()) {
      await backend.saveSettings(config);
      applyConfigToState(config);
      nodes.settingsMessage.textContent = "已保存到你的个人空间；其他账号不会看到这些设置。";
      showToast("个人设置已保存");
      return;
    }
    localStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(config));
    nodes.settingsMessage.textContent = "草稿已保存在此浏览器；尚未影响线上抓取。";
    showToast("本地草稿已保存");
  } catch (error) { showToast(error.message); }
}

async function applyConfiguration() {
  try {
    const json = configJson();
    if (backend.enabled()) {
      const config = JSON.parse(json);
      await backend.saveSettings(config);
      if (nodes.apiKeyInput.value.trim()) await saveCredential(config.runtime.provider, nodes.apiKeyInput, { quiet: true });
      if (nodes.serpApiKeyInput.value.trim()) await saveCredential("serpapi", nodes.serpApiKeyInput, { quiet: true });
      await backend.queueCollection(false);
      applyConfigToState(config);
      nodes.settingsDialog.close();
      showToast("设置已保存，抓取请求已进入队列");
      return;
    }
    localStorage.setItem(DRAFT_STORAGE_KEY, json);
    const repository = repositoryUrl();
    if (!repository) throw new Error("无法识别 GitHub 仓库地址。");
    const body = [
      "此配置由 Se Mechanism Daily 前端生成。保存或编辑此 Issue 后，GitHub Actions 会自动读取最新配置并重新抓取。",
      "",
      "API Key 不在此处保存；请放在仓库 Settings → Secrets and variables → Actions。",
      "",
      "```json",
      json,
      "```",
    ].join("\n");
    const url = `${repository}/issues/new?title=${encodeURIComponent("Research Interests")}&body=${encodeURIComponent(body)}`;
    if (url.length > 7500) {
      await copyText(body);
      window.open(`${repository}/issues/new?title=Research%20Interests`, "_blank", "noopener,noreferrer");
      nodes.settingsMessage.textContent = "完整配置已复制。请在 GitHub 正文中粘贴并创建 Issue；若弹窗被阻止，请允许弹窗后重试。";
    } else {
      window.open(url, "_blank", "noopener,noreferrer");
      nodes.settingsMessage.textContent = "已打开 GitHub：确认 Create new issue 后会自动应用并抓取。";
    }
  } catch (error) { showToast(error.message); }
}

async function saveCredential(provider, input, { quiet = false } = {}) {
  try {
    const value = input.value.trim();
    if (!value) throw new Error("请先输入 API Key。");
    const saved = await backend.saveCredential(provider, value);
    input.value = "";
    state.account.credentials = state.account.credentials.filter((item) => item.provider !== provider);
    state.account.credentials.push(saved);
    updateProviderUi();
    if (!quiet) showToast("API Key 已加密保存");
  } catch (error) {
    if (!quiet) showToast(error.message || "API Key 保存失败");
    throw error;
  }
}

async function queueCollection(clearCache) {
  try {
    await backend.queueCollection(clearCache);
    nodes.dataActionsDialog.close();
    showToast(clearCache ? "已提交清空后重抓" : "已提交增量抓取");
  } catch (error) { showToast(error.message || "提交失败"); }
}

function showAuthGate(message = "") {
  nodes.authGate.hidden = false;
  document.body.classList.add("auth-required");
  if (message) nodes.authMessage.textContent = message;
}

function hideAuthGate() {
  nodes.authGate.hidden = true;
  document.body.classList.remove("auth-required");
}

function updateAuthMode(mode) {
  authMode = mode === "signup" ? "signup" : "signin";
  nodes.authTitle.textContent = authMode === "signup" ? "创建你的文献空间" : "登录你的文献空间";
  nodes.authSubmit.textContent = authMode === "signup" ? "创建账号" : "登录";
  nodes.authSwitch.textContent = authMode === "signup" ? "已有账号？返回登录" : "没有账号？创建账号";
  nodes.authPassword.autocomplete = authMode === "signup" ? "new-password" : "current-password";
}

async function submitAuth(event) {
  event.preventDefault();
  nodes.authSubmit.disabled = true;
  nodes.authMessage.textContent = authMode === "signup" ? "正在创建独立空间…" : "正在验证账号…";
  try {
    const email = nodes.authEmail.value.trim();
    const password = nodes.authPassword.value;
    const result = authMode === "signup" ? await backend.signUp(email, password) : await backend.signIn(email, password);
    if (authMode === "signup" && !result.session) {
      nodes.authMessage.textContent = "账号已创建。请打开验证邮件，验证后再登录。";
      updateAuthMode("signin");
      return;
    }
    await loadAuthenticatedWorkspace();
  } catch (error) {
    nodes.authMessage.textContent = error.message || "登录失败，请检查邮箱和密码。";
  } finally {
    nodes.authSubmit.disabled = false;
  }
}

function bindEvents() {
  nodes.sidebarToggle.addEventListener("click", () => document.body.classList.add("sidebar-open"));
  nodes.sidebarScrim.addEventListener("click", () => document.body.classList.remove("sidebar-open"));
  document.querySelectorAll("[data-view]").forEach((button) => button.addEventListener("click", () => selectView(button.dataset.view)));
  nodes.topicFilter.addEventListener("change", (event) => { state.filters.topic = event.target.value; render(); });
  nodes.levelFilter.addEventListener("change", (event) => { state.filters.level = event.target.value; render(); });
  nodes.journalFilter.addEventListener("change", (event) => { state.filters.journal = event.target.value; render(); });
  nodes.searchInput.addEventListener("input", (event) => { state.filters.query = event.target.value.trim(); render(); });
  nodes.themeButton.addEventListener("click", () => applyTheme(state.theme === "dark" ? "light" : "dark"));
  nodes.accountButton.addEventListener("click", async () => {
    try { await backend.signOut(); window.location.reload(); }
    catch (error) { showToast(error.message || "退出失败"); }
  });
  nodes.openSettingsButton.addEventListener("click", openSettings);
  nodes.headerSettingsButton.addEventListener("click", openSettings);
  nodes.settingsClose.addEventListener("click", () => nodes.settingsDialog.close());
  nodes.settingsDialog.addEventListener("click", (event) => { if (event.target === nodes.settingsDialog) nodes.settingsDialog.close(); });
  nodes.providerSelect.addEventListener("change", () => updateProviderUi({ usePreset: true }));
  nodes.saveApiKeyButton.addEventListener("click", () => saveCredential(nodes.providerSelect.value, nodes.apiKeyInput));
  nodes.saveSerpApiKeyButton.addEventListener("click", () => saveCredential("serpapi", nodes.serpApiKeyInput));
  nodes.addTopicButton.addEventListener("click", () => addTopicEditor());
  nodes.copyConfigButton.addEventListener("click", copyConfiguration);
  nodes.saveDraftButton.addEventListener("click", saveDraft);
  nodes.applyConfigButton.addEventListener("click", applyConfiguration);
  nodes.dataActionsButton.addEventListener("click", () => {
    if (backend.enabled()) {
      nodes.runModeLabel.textContent = "PERSONAL COLLECTION";
      nodes.runModeDescription.textContent = "提交到你的个人抓取队列；配置、日期历史和结果均与其他账号隔离。";
    } else {
      nodes.runModeLabel.textContent = "GITHUB ACTIONS";
      nodes.runModeDescription.textContent = "进入已登录的 GitHub 后确认运行，网页不会接触你的令牌。";
    }
    nodes.dataActionsDialog.showModal();
  });
  nodes.dataActionsClose.addEventListener("click", () => nodes.dataActionsDialog.close());
  nodes.dataActionsDialog.addEventListener("click", (event) => { if (event.target === nodes.dataActionsDialog) nodes.dataActionsDialog.close(); });
  nodes.refreshPapersLink.addEventListener("click", (event) => {
    if (!backend.enabled()) return;
    event.preventDefault();
    queueCollection(false);
  });
  nodes.clearPapersLink.addEventListener("click", (event) => {
    if (!backend.enabled()) return;
    event.preventDefault();
    queueCollection(true);
  });
  nodes.authForm.addEventListener("submit", submitAuth);
  nodes.authSwitch.addEventListener("click", () => updateAuthMode(authMode === "signin" ? "signup" : "signin"));
}

async function loadStaticData() {
  const response = await fetch("./data/papers.json", { cache: "no-store" });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

function renderWorkspace() {
  state.filters.date = newestDateKey();
  renderDateNavigation();
  hydrateTopicFilter();
  updateGeneratedStatus();
  render();
  if (new URLSearchParams(window.location.search).get("settings") === "1") openSettings();
}

async function loadAuthenticatedWorkspace() {
  nodes.authMessage.textContent = "正在载入你的独立文献空间…";
  const [template, workspace] = await Promise.all([loadStaticData(), backend.loadWorkspace()]);
  const defaultConfig = {
    sources: template.sources || AVAILABLE_SOURCES,
    topics: template.topics || [],
    runtime: template.runtime || {},
  };
  const config = workspace.config || defaultConfig;
  if (!workspace.config) await backend.saveSettings(config);
  try { state.account.credentials = await backend.credentialStatus(); }
  catch (error) { state.account.credentials = []; console.warn("Credential status unavailable", error); }
  state.account.user = workspace.user;
  const latestRun = workspace.latestRun;
  state.data = {
    data_kind: "selenium_mechanism",
    config_source: "account",
    papers: workspace.papers || [],
    sources: config.sources || [],
    topics: config.topics || [],
    runtime: { ...(config.runtime || {}) },
    stats: latestRun?.stats || {},
    generated_at_iso: latestRun?.completed_at || "",
  };
  const selectedCredential = state.account.credentials.find((item) => item.provider === state.data.runtime.provider);
  state.data.runtime.secret_configured = Boolean(selectedCredential);
  nodes.accountLabel.textContent = workspace.user.email || "我的账号";
  nodes.accountButton.hidden = false;
  hideAuthGate();
  renderWorkspace();
  if (latestRun?.status === "failed") updateGeneratedStatus(`最近一次抓取失败：${latestRun.error_message || "请检查配置"}`);
}

async function main() {
  configureRepositoryLinks();
  applyTheme(storedTheme());
  bindEvents();
  updateAuthMode("signin");

  if (backend.requireAuth && !backend.enabled()) {
    showAuthGate("云后端尚未完成配置，请联系网站管理员。");
    nodes.authSubmit.disabled = true;
    return;
  }

  if (backend.enabled()) {
    try {
      const activeSession = await backend.session();
      if (!activeSession) {
        showAuthGate();
        return;
      }
      await loadAuthenticatedWorkspace();
      return;
    } catch (error) {
      showAuthGate(`个人空间加载失败：${error.message}`);
      return;
    }
  }

  try { state.data = await loadStaticData(); }
  catch (error) {
    updateGeneratedStatus(`数据读取失败：${error.message}`);
    nodes.paperList.textContent = "文献数据加载失败，请稍后刷新。";
    return;
  }
  renderWorkspace();
}

main();
