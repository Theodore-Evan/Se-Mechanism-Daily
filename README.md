# Se Mechanism Daily

一个可 Fork、可自行部署的硒相关生物机制文献追踪器。项目每天检索公开学术索引，按照自定义研究方向筛选论文，并生成便于快速浏览的静态网页。

本仓库默认关注：

- 硒代谢、硒稳态与硒蛋白生物合成
- 硒、氧化还原、GPX4 与铁死亡
- 硒参与的免疫和炎症调控
- 硒缺乏、补充或暴露相关疾病机制

## 功能

- 文献源：PubMed、Google Scholar（通过 SerpApi）、OpenAlex、Crossref 和生命科学 arXiv
- 自动更新：GitHub Actions 每天运行，也支持手动触发
- 数据管理：网页右上角可选择“刷新重新抓取”或“清空后重抓”
- 期刊信息：展示期刊名、带年份的 JIF、JCR 分区，以及 CNS / Nature / Science / Cell 系列和 Top 标记
- 顶刊筛选：支持 CNS 主刊、三大期刊系列、其他 Top 期刊和 JCR Q1–Q4 筛选
- 机制摘要：可选用智谱 GLM 生成结构化中文摘要；未配置模型时使用保守的基础摘要
- 研究方向配置：编辑 JSON 文件，或通过仓库中的 `Research Interests` Issue 修改
- 静态部署：生成纯 HTML、CSS 和 JavaScript，可直接部署到 GitHub Pages
- 隐私友好：代码中不包含维护者姓名、邮箱、账号、API Key 或固定仓库地址

## 工作流程

```text
研究方向配置
      ↓
五个学术索引并行提供候选题录
      ↓
标题与摘要关键词评分、合并重复记录
      ↓
智谱 GLM 中文机制摘要（可选）
      ↓
web/data/papers.json
      ↓
GitHub Pages 静态网站
```

不同来源的覆盖范围和更新时间并不相同，因此同一论文可能由多个来源共同提供信息。采集器会优先用 DOI，其次用规范化标题合并重复记录。

## Fork 后快速部署

1. Fork 本仓库。
2. 打开仓库的 **Settings → Pages**，将 Source 设为 **GitHub Actions**。
3. 打开 **Settings → Secrets and variables → Actions**，根据需要添加密钥：

   | 类型 | 名称 | 用途 |
   |---|---|---|
   | Secret | `SERPAPI_API_KEY` | 启用 Google Scholar |
   | Secret | `ZHIPU_API_KEY` | 启用智谱 GLM 中文摘要 |
   | Secret | `NCBI_API_KEY` | 可选，提高 PubMed API 配额 |
   | Variable | `ZHIPU_BASE_URL` | 可选；默认 `https://open.bigmodel.cn/api/paas/v4` |
   | Variable | `ZHIPU_MODEL` | 可选；默认 `glm-4-flash-250414` |
   | Variable | `CONTACT_EMAIL` | 可选，提供给 Crossref、OpenAlex 或 NCBI 的 API 联系地址 |

4. 在 **Actions → 更新 Se 文献网站 → Run workflow** 手动运行一次。
5. 部署完成后，网站地址通常为：

   ```text
   https://YOUR_USERNAME.github.io/YOUR_REPOSITORY/
   ```

API Key 只能保存在 GitHub Actions Secrets 中，不要写入代码、Issue、提交记录或网页数据。

如果仓库以前使用 Gemini，旧的 `LLM_API_KEY`、`LLM_BASE_URL` 和 `LLM_MODEL`
设置不会再被自动任务读取，可以安全删除。切换到智谱只需添加
`ZHIPU_API_KEY`；只有使用代理地址或其他智谱模型时才需要设置两个可选变量。

## 修改研究方向

直接编辑 [`config/interests.json`](config/interests.json)。一个方向的结构如下：

```json
{
  "id": "selenium_redox_ferroptosis",
  "name": "硒、氧化还原与铁死亡",
  "description": "关注硒和硒蛋白对氧化应激、脂质过氧化及铁死亡敏感性的调控机制。",
  "keywords": [
    "selenium ferroptosis",
    "GPX4 ferroptosis",
    "selenium lipid peroxidation"
  ],
  "arxiv_categories": ["q-bio.BM", "q-bio.CB"]
}
```

建议：

- `id` 使用稳定的英文小写标识，后续尽量不要修改。
- `keywords` 使用数据库中常见的英文术语；把 “selenium” 或具体硒蛋白写进短语，可减少无关结果。
- `description` 会传给摘要模型，应该说明你真正关心的机制问题。
- `arxiv_categories` 仅用于 arXiv 辅助检索；默认仍以关键词为主。

网页右上角的配置按钮也可以创建 `Research Interests` Issue。保留 Issue 中的 JSON 代码块，GitHub Actions 会优先读取它；关闭该 Issue 后会自动回到仓库配置。

## 配置文献源

`config/interests.json` 中的 `sources` 决定启用哪些来源：

```json
[
  { "type": "pubmed", "name": "PubMed" },
  { "type": "google_scholar_serpapi", "name": "Google Scholar" },
  { "type": "openalex", "name": "OpenAlex" },
  { "type": "crossref", "name": "Crossref" },
  { "type": "arxiv", "name": "arXiv" }
]
```

Google Scholar 需要 `SERPAPI_API_KEY`。缺少某一来源的密钥或某一 API 暂时不可用时，采集器会记录该来源失败并继续处理其他来源。

## 刷新与清空后重抓

网页右上角的 `↻` 按钮提供两个入口：

- **刷新重新抓取**：进入 GitHub Actions 后直接运行，保留历史文献缓存，并抓取最新文献、补齐期刊信息。
- **清空后重抓**：进入 GitHub Actions 后勾选 `clear_cache` 再运行，忽略原有文献缓存，从各数据源重新建立列表。

网站是纯静态 GitHub Pages，不能安全保存 GitHub 访问令牌，因此不会在浏览器里直接触发有写权限的工作流。入口会打开已登录的 GitHub Actions 页面，由仓库维护者确认运行；这可避免把 Token 暴露给访客。

## 期刊指标与顶刊规则

期刊指标和别名位于 [`config/journal_metrics.json`](config/journal_metrics.json)。采集器会从 PubMed、OpenAlex、Crossref、Google Scholar 和 arXiv 读取期刊名，然后用规范名或别名匹配该配置。

每个期刊条目支持：

```json
{
  "name": "Nature Communications",
  "aliases": ["Nat Commun"],
  "family": "nature",
  "tier": "family",
  "impact_factor": 18.1,
  "quartile": "Q1",
  "source_url": "https://www.nature.com/nature-portfolio/about-journals/journal-metrics"
}
```

- `family` 可写 `nature`、`science`、`cell` 或留空。
- `tier` 可写 `flagship`、`family`、`top`、`standard`。
- `impact_factor`、`quartile` 应与文件顶部的 `metric_year` 和 `quartile_system` 对应；未知值请保留 `null`，网页会显示“待配置”，不会猜测。
- 一个期刊可能分属多个 JCR 学科并具有不同分区。默认配置展示代表性分区；正式评价或投稿决策前，应以所在机构可访问的当年 JCR 为准。

默认收录的 Nature Portfolio JIF 来自其公开的年度期刊指标页。完整 JCR 数据及 Web of Science Journals API 属于 Clarivate 授权服务，因此本项目不抓取或内置未经授权的完整 JCR 数据库。Fork 后可以用本单位许可数据维护这个公开配置，但请先确认再分发权限。

## 本地运行

需要 Python 3.11 或更高版本。采集器只使用 Python 标准库。

```bash
python scripts/collect_papers.py --lookback-days 7
python -m http.server 8000 --directory web
```

然后打开 `http://localhost:8000`。

如需在本地启用外部服务，请通过环境变量传入密钥，不要创建会被提交的明文配置：

```bash
export SERPAPI_API_KEY="..."
export LLM_API_KEY="..."
export LLM_BASE_URL="https://open.bigmodel.cn/api/paas/v4"
export LLM_MODEL="glm-4-flash-250414"
export LLM_PROVIDER_NAME="智谱 GLM"
python scripts/collect_papers.py
```

PowerShell 对应写法：

```powershell
$env:SERPAPI_API_KEY = "..."
$env:LLM_API_KEY = "..."
python scripts/collect_papers.py
```

## 常用运行参数

以下值可以在 GitHub Actions Variables 中配置：

| 变量 | 默认值 | 说明 |
|---|---:|---|
| `LOOKBACK_DAYS` | `1` | 自动任务检索最近多少天 |
| `MAX_PER_TOPIC` | `10` | 每个来源、每个方向最多读取多少条 |
| `MAX_NEW_PAPERS` | `50` | 单次保留的新或重新发现论文上限 |
| `MAX_STORED_PAPERS` | `50` | 网页数据最多保存多少篇 |
| `MAX_SUMMARIES` | `12` | 单次最多生成多少篇 AI 摘要 |
| `MIN_MATCH_SCORE` | `0.12` | 最低相关性分数 |
| `MIN_DAILY_PAPERS` | `8` | 结果不足时触发回填的目标数量 |
| `DAILY_BACKFILL_DAYS` | `14` | 回填最多向前检索多少天 |
| `RECENT_HISTORY_DAYS` | `45` | 低匹配历史论文的保留时间 |
| `SOURCE_DELAY_SECONDS` | `1` | 外部请求之间的间隔 |
| `PAPER_SOURCES` | 空 | 可选，用逗号临时限定来源类型 |
| `LLM_CONCURRENCY` | `1` | 智谱摘要并发数；免费额度建议保持串行 |
| `LLM_REQUEST_DELAY_SECONDS` | `6` | 两次模型请求之间的间隔，用于降低限流风险 |
| `LLM_RETRIES` | `2` | 模型遇到限流或临时错误时的尝试次数 |

## 项目结构

```text
.
├── .github/
│   ├── ISSUE_TEMPLATE/research-interests.md
│   └── workflows/update-literature.yml
├── config/
│   ├── interests.json
│   └── journal_metrics.json
├── scripts/collect_papers.py
├── tests/test_collect_papers.py
└── web/
    ├── data/papers.json
    ├── app.js
    ├── index.html
    └── styles.css
```

## 参与修改

欢迎 Fork、修改和提交 Pull Request。请先阅读 [`CONTRIBUTING.md`](CONTRIBUTING.md)。公开发布自己的版本前，请替换研究方向和示例数据，并确认提交历史中没有密钥或个人信息。

本项目以 [MIT License](LICENSE) 发布，可用于学习、科研辅助和二次开发。自动摘要与匹配分数仅用于文献初筛，不能替代全文阅读、系统综述或专业判断。
