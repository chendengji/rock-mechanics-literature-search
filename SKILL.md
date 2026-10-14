---
name: rock-mechanics-literature-search
description: 岩石力学与岩土工程领域深度定制的文献检索技能，基于 OpenAlex/CrossRef/Semantic Scholar API 全库检索，26 种核心期刊白名单作评分加权（不排除），漏斗式去噪后输出全量评分排序表供人工确认，支持期刊指标(IF/JCR)合并、BibTeX 导出、人工确认后导入 Zotero 分类。Use when 用户要求检索岩石力学/岩土工程方向的文献、查文献、找论文、做文献综述、跟踪期刊最新论文、查找某主题相关研究、导出候选文献表或把确认的论文导入 Zotero（literature search, find papers, recent publications）。
---

# 岩石力学领域文献检索

## 概述

针对岩石力学与岩土工程研究方向定制的文献检索技能。核心价值：(1) **默认全 OpenAlex 库检索，26 刊白名单只作评分加权（A类+3/BCDEFG+2/H+1），不作排除**——白名单外的高相关文献同样入选；(2) 内置期刊-主题映射与中英术语表，中文问题也能用标准英文术语检索国际文献；(3) 漏斗式交付：数百篇原始命中 → 去重与相关性标签 → 单侧补足 → 综合评分排序，**最终交付 20-50 篇高相关文献**（--top-n 可调）；(4) 脚本化 API 检索为主（数据准确、含被引数和摘要），网络检索为**受严格限制的最后手段**（详见工作流兜底路径）。检索脚本改造自开源项目 lingzhi227/agent-research-skills（stdlib-only 设计），并针对岩石力学领域做了定制。

## 资源文件

- `scripts/search_rock_journals.py` — **单主题检索脚本**：默认全 OpenAlex 库检索（`--scope all`），白名单期刊评分加权；`--top-n` 截断交付；传入 `--journals/--category` 或 `--scope whitelist` 时退化为 26 刊硬过滤（适合"某刊最近有什么新文章"）。免 API Key。
- `scripts/iterative_search.py` — **交叉主题轮询检索（首选）**：多组检索词轮询 → 去重 → 相关性标签漏斗（无信号与命中排除表者永不进表——切题度硬底线）→ 综合评分排序 → **默认输出全部相关候选的评分排序表**（弱信号沉底，供人工复核；`--top-n N` 可选截断，`--min-signal a/T` 可收紧切题度）。**自动归档**：传 `--task <任务目录>` 时逐轮原始命中/检索词进 `01_sources/`、每轮分析 JSON 进 `04_reports/`、`-o` 省略时默认 `02_intermediate/result`，跑完自动刷新 MANIFEST。
- `scripts/lit_common.py` — **共享工具库**：期刊指标合并（反编造）、去重（DOI→ID→标准化题名→Jaccard 兜底）、相关信号标签（T/a/s/-/x；排除表分两级——标题命中硬淘汰、仅摘要命中降级不剔除）、透明综合评分（关键词0-5+期刊层级0-3+学术影响0-3+时效0-1）、候选文献表 CSV 导出（utf-8-sig，Excel 直开）。
- `scripts/lit_secrets.py` — **共享凭据与限速模块**：自动从 `.env` 读取 Semantic Scholar API Key，并提供 S2 全局节流器。任何密钥不入日志、不进结果文件。
- `scripts/lit_paths.py` — **任务目录标准布局（唯一的产出路径真相源）**：定义 `00_config / 01_sources / 02_intermediate / 03_final / 04_reports / 05_pdf / 06_scripts / 07_logs / 99_archive` 九类目录，提供 `init / new / path / manifest / migrate` 五个子命令（建骨架+README、生成文件清单、迁移旧的平铺目录）。检索与导入脚本用它的 `p(root, "03_final", "x.csv")` 取路径，**不要手拼目录名**。
- `scripts/lit_throttle.py` — **跨进程共享节流器**：OpenAlex/CrossRef/S2 各自一条队列，状态落在技能目录 `.cache/rate_<endpoint>.lock`（锁文件 + `msvcrt` 文件锁串行化）。同机并跑多个检索脚本时共享同一队列，出口速率不会叠加（旧版只有进程内 `threading.Lock`，并跑两个脚本 = 2×速率）。非 Windows 或锁文件不可写时自动退回进程内节流。`search_rock_journals.py` 与 `search_openalex.py` 已接入。
- `references/journal_metrics.csv` — **26 刊指标权威数据表**：IF/JCR 分区均带 metric_year / metric_source / metric_status（已核验/待复核/待核验/无JCR收录）。白名单外期刊的指标显示"待核验"。
- `scripts/zotero_import.py` — **检索结果入库 Zotero**：读检索 JSONL → DOI 查重 → 创建/复用分类 → 写入条目。本地 API 优先（Zotero 客户端运行中即可，授权 Key 已缓存在技能目录的 `.cache/zotero_local.json`）；Web API 备选（`--web --user-id --api-key`）。
- `scripts/search_openalex.py` — 通用 OpenAlex 检索（不限期刊，用于扩大范围）。
- `scripts/search_crossref.py` — CrossRef 检索（可输出 BibTeX，适合按 DOI 补条目）。
- `scripts/search_semantic_scholar.py` — Semantic Scholar 检索（API Key 自动从 .env 加载；S2 限流严格，勿高频请求）。
- `scripts/paper_db.py` — 多来源结果合并去重（三级键匹配 + Jaccard 兜底，重复合并为一条最全记录）。
- `scripts/bibtex_manager.py` — 从 JSONL 生成 BibTeX（带期刊名+DOI 的条目输出 @article）。
- `references/scihub-download.md` — **Sci-Hub 全文 PDF 下载操作规范**：仅用 chrome-devtools MCP 人机模拟操作实体 Chrome（导航→证书跳过→人机验证→点下载→另存为），并含限速规则（严禁解析网页/fetch/playwright）。
- `references/windows-control/` — **Windows 桌面控制技能（MIT，spliff7777）**：pywinauto/pyautogui 脚本集，用于处理"另存为"等系统对话框（该技能默认的 UIA backend 对中文"另存为"对话框不可见，需用 win32 backend 定位 `#32770`，集成细节见其中 README-scihub-integration.md）。
- `scripts/save_dialog_confirm.py` — **"另存为"对话框自动确认**：win32 backend 定位 `#32770`+标题"另存为"，填目标路径、点"保存"，把下载闭环最后一步全自动化。
- `references/journals.md` — 期刊知识库：主题范围、主题→期刊映射表。定位目标期刊时读取。IF 数值以 journal_metrics.csv 为准。
- `references/search-strategies.md` — 网络检索兜底方案（最后手段，须用户许可后使用）：出版商 URL 模板、WebSearch 域名过滤、中英术语对照表、输出模板。
- `CHANGELOG.md` — 版本历史与变更记录（各设计何时代入、为何调整）；日常使用无需读取，与本文件冲突时以本文件为准。
- `pyproject.toml` + `uv.lock` — **依赖声明与锁文件**：`requires-python = ">=3.12,<3.13"`，依赖 `pywinauto/pyautogui/pillow`；由 uv 解析锁定版本，装入本技能目录 `.venv`。新增/升级依赖在此声明后跑 `uv sync --directory "<本技能目录>"`，**不要 pip install**。
- `.cache/` — 本地缓存（Zotero 本地 API Key），已 `.gitignore`，不入库、不带走。

**运行环境**：Python 一律走本机 uv 管理的环境（**不要直接调用 `python`、不要手装 Python**）。所有脚本统一用 `uv run --directory "<技能目录>" scripts/xxx.py` 调用（`<技能目录>` 指本技能安装目录，默认 `~/.config/opencode/skills/rock-mechanics-literature-search`，下文命令中的 `<技能目录>` 均指此处）——uv 会按本技能目录的 `pyproject.toml`（`requires-python = ">=3.12,<3.13"`）自动选用 uv 托管的 CPython 3.12.x 并构建/复用该目录下的 `.venv`。检索/导入类脚本仅依赖标准库；PDF 下载类脚本另需 pywinauto/pyautogui/pillow，依赖声明在 `pyproject.toml`，由 uv 装入本技能目录 `.venv`（首次 `uv run` 会自动安装）。

**凭据与限速注意**：Semantic Scholar API Key 自动从 `~/.config/opencode/.env`（或技能目录下的 `.env`，亦可用环境变量 `LIT_ENV_FILE` 指定）加载（`lit_secrets.py`，键名 `SEMANTIC_SCHOLAR_API_KEY` 或 `S2_API_KEY`），脚本无需手动传参。Semantic Scholar 与 OpenAlex 均按 IP/速率限流——OpenAlex 节流已改为**跨进程共享队列**（`lit_throttle.py`，锁文件在技能目录 `.cache/`；同机并跑多个检索脚本不会叠加出口速率），S2 默认 0.55 req/s、OpenAlex 默认 0.7 req/s，配 429 指数退避，**严禁人为连续刷大量请求**，以免封 IP/Key。可传 `--rate` / `--s2-rate` 调速率。

**OpenAlex 每日预算（重要）**：匿名请求按"美元预算"计费（约 $0.001/请求）。**当日预算用尽后，无论把速率降到多低都会返回 429**，响应体为 `Insufficient budget ... Resets at midnight UTC`——节流器解决不了这个问题。预算耗尽时：① 等 UTC 零点重置；② 改用 `search_crossref.py` / `search_semantic_scholar.py`（不受此预算限制）；③ 用 `search_federated.py` 自动跳过失效数据源。大检索任务请分批在一天内完成，或优先走 federated。

## 产出目录规范（技能文件与结果分离 + 固定九类布局）

技能文件固定在本目录（`~/.config/opencode/skills/rock-mechanics-literature-search`）；**所有检索产出必须写入 `~/Documents/paper`（可用环境变量 `LIT_PAPER_ROOT` 覆盖）下的独立任务文件夹，绝不要写到技能目录里**。

### 建任务目录（一行命令）

```bash
uv run --directory "<技能目录>" \
    scripts/lit_paths.py new "<主题英文短横线>" --note "本次检索目标"
```

- 目录名 = `lit_<主题>_<YYYYMMDD>`（主题小写、下划线连接、去掉空格与特殊字符；已有示例 `lit_water_rockburst`、`lit_pore_microcrack_progressive_20260928`）。
- 该命令会一次性生成九类目录、任务根 `README.md`（含"先看哪里"导航与数据链路）、`00_config/commands.md`、`.lit_task.json` 标记文件和 `MANIFEST.csv` 全量文件清单。
- `.lit_task.json` 是"这是标准任务目录"的标记；`lit_paths.task_root_for(路径)` 靠它向上定位任务根，后续脚本不必再手填目录。

### 九类目录（写文件时对照这张表，不要平铺在根目录）

| 目录 | 放什么 | 谁生成 |
|------|--------|--------|
| `00_config/` | 检索词表、期刊范围、**实际执行过的完整命令**（可复现的唯一凭据） | 人工/Agent 记录 |
| `01_sources/` | 各数据源原始返回、跨库合并去重后的完整库（`merged_all.jsonl`）、逐轮命中 | 检索脚本 |
| `02_intermediate/` | 去重/标签/评分后的中间层 JSONL、候选文献表 CSV、摘要补充数据 | 漏斗与摘要脚本 |
| `03_final/` | **最终交付**：分级交付表、含摘要交付表、`references.bib` | 人工确认后 |
| `04_reports/` | 结论报告、解读/精读 Markdown、审计统计表 | 分析阶段 |
| `05_pdf/` | 下载的全文 PDF | Sci-Hub 流程 |
| `06_scripts/` | 本任务新写的脚本（漏斗、摘要补全、分级等） | Agent |
| `07_logs/` | 运行日志、错误记录、迁移记录 | 随时 |
| `99_archive/` | 过期或被取代的产物，**只读留档不删** | 收尾整理 |

### 硬性规则

1. **最终成果只能在 `03_final/`**，报告只能在 `04_reports/`；用户打开目录先看这两个。
2. 任何脚本/临时产物不得留在任务根目录；根目录只允许 `README.md`、`MANIFEST.csv`、`.lit_task.json`。
3. 每完成一个阶段跑一次 `lit_paths.py manifest <任务目录>` 刷新清单（`--hash` 附校验值，大文件慎用）。
4. 收尾前用 `lit_paths.py migrate <任务目录>` 把平铺文件归位（支持 `--dry-run` 预演），它会把移动记录写进 `07_logs/migrate.log`。
5. 脚本里的相对路径 `scripts/`、`references/` 始终指本技能目录；输出路径一律用 `lit_paths.p(任务根, "类别", "文件名")` 取，不要手拼目录名。

## 检索工作流

### 第 1 步：解析主题并扩展关键词

1. 从用户问题中提取研究主题、研究对象（岩盐/花岗岩/煤岩等）、研究方法（试验/数值/监测）。
2. 读取 `references/search-strategies.md` 的术语对照表，把中文主题翻译为标准英文术语（OpenAlex 对英文检索词命中率显著更高，中文刊也用英文检索词能召回更多）。
3. 生成 2-4 组关键词组合（主题词 + 方法词/对象词）。主题模糊时先问清方向再检索。

### 第 2 步：期刊加权（不再是排除）

读取 `references/journals.md` 的"按主题快速定位期刊"表，判断主题与哪些类别强相关——这些信息用于**解读评分**（"期刊层级+2/+3 分"）和向用户解释排序，而不是用来缩小检索范围：

- 默认全库检索，不加任何期刊过滤
- 需要严格限定白名单时才传 `--journals` / `--category` 或 `--scope whitelist`（如"XX 期刊最近有什么新文章"场景）

### 第 3 步：执行检索（脚本优先）

**路径选择**：单一主题（如"隧道岩爆"）→ 单次 `search_rock_journals.py`；**交叉主题（如"含水率影响岩爆"、"温度对蠕变影响"）→ 必须走轮询迭代**，单次检索漏检率极高。

**主路径 A：单次检索 search_rock_journals.py**（单一主题）

```bash
# 相关性排序（默认，适合找代表性文献）；默认不截断，输出全表供人工复核
# --task 给标准任务目录后，-o 只需写文件名，脚本自动落位到 03_final/（.csv）
uv run --directory "<技能目录>" scripts/search_rock_journals.py --query "{英文关键词}" \
    --year-range {如 2020-2026} --max-results 100 \
    --task "~/Documents/paper/lit_<主题>_<日期>" -o "{主题}.csv"

# 本地综合评分排序（关键词信号+白名单加分+被引+时效）；--top-n 可选截断
uv run --directory "<技能目录>" scripts/search_rock_journals.py --query "..." --max-results 200 --sort score:desc

# 最新文献跟踪（按发表日期）
uv run --directory "<技能目录>" scripts/search_rock_journals.py --query "{英文关键词}" --sort publication_date:desc

# 经典高被引文献
uv run --directory "<技能目录>" scripts/search_rock_journals.py --query "{英文关键词}" --min-citations 100 --sort cited_by_count:desc
```

> **OpenAlex 限流保护**：所有 OpenAlex 请求（`search_rock_journals.py` / `iterative_search.py` / `search_openalex.py` / `search_federated.py`）共用 `lit_throttle.py` 的**跨进程共享队列**（默认 0.7 req/s ≈ 1.4s/请求；锁文件在技能目录 `.cache/rate_openalex.lock`，同机并跑多个脚本不会叠加出口速率），429 指数退避最长等 60s、最多重试 6 次。可传 `--rate N` 调快（如 `--rate 2`）或调慢（防封时可 `--rate 0.3`）。**注意区分两种 429**：响应体含 `Retry-After` 且无 `dailyRemainingUsd` 才是速率问题（降速有效）；若出现 `Insufficient budget ... dailyRemainingUsd: 0`，说明当日匿名预算已耗尽，降速无效，需等 UTC 零点或改用 CrossRef/S2。

**主路径 B：轮询迭代检索 iterative_search.py**（交叉主题，推荐）

轮询分多轮执行，每轮结束后分析命中结果、学习新术语、设计下一轮检索词。**每组词全库模式下取回量要大（--per-query ≥50），原始命中几百篇是正常的，交给漏斗收敛**：

- **轮次 1**：主题两侧关键词直接组合。两侧各取 3-5 个变体（含水率: water content / moisture / water saturation / 含水率 / 饱水；岩爆: rockburst / bursting liability / impact propensity / 岩爆 / 冲击倾向性），交叉成 5-8 组检索词
- **轮次 2**：读轮次 1 命中文献的**标题和摘要**，提取实际使用的术语（往往与初始设计不同，如 water-rich、water injection pressure relief、proneness），补 5-8 组变体再轮询；固定术语用引号词组查询降噪（OpenAlex 多词是词袋 OR 语义）
- **轮次 3**（收敛判断）：若轮次新增相关文献 < 3 篇则收敛。用边缘分析查漏——检查"只差一个条件"的文献（标题双命中但被单侧/排除的），确认是漏检还是假阳性

```bash
uv run --directory "<技能目录>" scripts/iterative_search.py \
    --query "rockburst water content" --query "含水率 冲击倾向性" --query '"bursting liability" water' \
    --year-range 2000-2026 --per-query 50 \
    --task "~/Documents/paper/lit_water_rockburst_20260828"
# --task 会自动建骨架并分流：逐轮原始命中/检索词→01_sources/，每轮分析→04_reports/，
# -o 省略时默认 02_intermediate/result；也可用 -o 显式指定文件名。
# 注意：--side-a/--side-b 是相关性词表（默认=水×岩爆），其他交叉主题必须自定义两个词表
# --exclude 是假阳性排除表；标题双命中(T)优先于摘要双命中(a)，防止 OpenAlex 摘要缺失漏检
# 默认 --top-n 0：全部 T/a/s 候选按综合评分排序输出完整表（人工复核模式）；
# 可选收紧：--min-signal a（只看双命中）/ --top-n N（只交付前N篇）
# 若总数不足 --min-final(默认20)，统计输出 shortfall=true，须在覆盖说明中如实交代存量不足
```

**已识别的假阳性类型**（新主题沿用此思路）：①工程背景词（引水隧洞 water conveyance/diversion 中的"water"与含水率无关）；②相邻领域（hydraulic fracturing、seepage、水力耦合）；③摘要偶然提及（用标题双命中 T/a 双信号区分）；④防治措施类（注水卸压、微波致裂等摘要含双词但主题是工程措施）。

**兜底路径（严控，最后手段）**：网络检索（WebSearch / WebFetch）**只能作为最后一个手段**，且**使用前必须取得用户明确许可**。触发顺序严格如下：
1. **先用多数据源 API**：`search_federated.py`（OpenAlex+CrossRef+S2，单库失败自动跳过其余继续）或 `iterative_search.py` / `search_rock_journals.py`。某一库限流/空结果 **不等于** 放弃，须先换库 / 换检索词 / 稍后重试。
2. **仅当全部可用数据源都失败且结果仍不足时**，才向用户说明现状并**征得明确许可**后，才读 `references/search-strategies.md` 用 WebSearch + 出版商域名过滤 / WebFetch 检索兜底。
3. 未经用户明确应允，**不得擅自发起任何 WebSearch / WebFetch 检索**；网络兜底使用量应尽量减少。
4. 用网络结果时，须在交付表里对每条标注来源为"网络兜底"，且不编造字段（标"待核验"）。

**补充路径**：需要某几篇的完整 BibTeX 时，`bibtex_manager.py --jsonl "~/Documents/paper/lit_<主题>_<日期>/{检索结果}.jsonl" --output "~/Documents/paper/lit_<主题>_<日期>/references.bib"`。

### 第 4 步：人工复核闭环（机器排序 → 人确认 → 机器入库）

1. 脚本默认**不截断**，输出全部相关候选（T/a/s）的**综合评分排序表** CSV——强相关置顶、弱信号沉底、噪声(-/x)已剔除。Agent 先自行浏览全表，结合摘要做分级标注（核心/支撑/方法借鉴），但**不替用户做最终取舍**。
2. 把排序表交给用户人工查看（Excel 直开）。用户可按"综合评分 + 相关性信号 + 摘要"判断，在 **"人工确认"列**勾选认可的文献，或直接口头指定 DOI/序号。
3. 用户确认后，Agent 用 `zotero_import.py --only-doi {勾选的DOI}` 批量导入指定分类（先 `--dry-run` 预检查重）。导入前核对勾选行 DOI 完整；无 DOI 的中文条目单独列出由用户复核。
4. 按 `references/search-strategies.md` 第四节模板输出：结果概览 + 重点文献摘要 + 覆盖情况说明。

硬性规则：
- 每条结果必须附 DOI 或可核实链接；脚本输出的数据可信，但不要凭空补充作者/年份等字段，不确定的标"待核验"，**严禁编造**。
- 中文文献标题、期刊名保持中文；英文文献保持原文。
- **切题度硬底线**：无信号(-)与命中排除表(x)的记录永不进入交付表；交付表按评分排序让用户一眼看到高相关文献。
- 未经用户确认不得擅自批量导入 Zotero；导入后报告成功/失败/跳过计数。
- 输出末尾建议后续动作：深挖某几篇（拉摘要全文）、生成 references.bib、确认后导入 Zotero。

## 候选文献表、期刊指标与去重规范

（借鉴 Lucaswangzcx/literature-downloader-skill 的三条纪律，实现于 `scripts/lit_common.py`）

### 候选文献表 CSV 必要列

面向用户的清单一律用中文列名（`lit_common.CANDIDATE_COLUMNS_ZH`），指标并入每一行，
不让用户在文献清单和指标表之间来回对照：

```
序号 | 题名 | 作者 | 年份 | 期刊或来源 | 期刊缩写
影响因子 | JCR分区 | 指标年份 | 指标来源 | 索引情况 | 指标状态   ← 每行都带，缺失=待核验
被引数 | 年均被引 | 综合评分 | DOI | 文章地址 | OA入口
全文状态 | 下一步建议 | 检索词 | 相关性信号(T/a/s) | **人工确认**   ← 用户勾选列，确认后按 DOI 导入 Zotero
```

JSONL 中对应新增字段：`record_id`（DOI/题名哈希，跨轮次稳定 ID）、`landing_page_url`、
`oa_status`、`cpy`（年均被引）、五个指标字段、`fulltext_status`、`next_step`、
`relevance_label`（T/a/s/-/x）、`score` 与 `score_parts`（透明评分四分量）、`relevance_score`（OpenAlex 相关分）。

### 期刊指标反编造纪律

1. 影响因子/JCR 分区**只**取自 `references/journal_metrics.csv`；该表每行带指标年份与来源。
2. 表中没有的值（含全部扩展期刊）输出**待核验**，严禁现场编造数字或引用记忆中的旧值。
3. 不混称口径：JCR 影响因子、SJR、CiteScore 是三种指标；非 JCR 口径的数值只能进备注。
4. `metric_status=待复核` 的值可用但须注明状态；每 年 6 月 JCR 更新后重新核实一次。

### 去重规则（优先级从高到低）

1. **DOI 精确匹配**（规范化大小写与前缀）
2. **数据源 ID**（openalex_id / arxiv_id / paperId）
3. **标准化题名精确匹配**（小写+去符号）
4. **标题 Jaccard 相似度兜底**（默认阈值 0.8，兼容英式/美式拼写差异）

重复记录**合并为一条信息最全的记录**（填空缺字段、取更长摘要、并集 tags/query、被引取最大），
绝不因去重丢行。多来源合并用 `paper_db.py merge`；轮询迭代内建同一套规则。

### 第 5 步（可选）：检索结果入库 Zotero

用户要求"存入 Zotero / 加到文献库"时执行。前提：Zotero 客户端正在运行（本地 API 已授权，Key 已缓存，无需再弹窗）。

```bash
# 预检：看哪些已在库（不写入）
uv run --directory "<技能目录>" scripts/zotero_import.py "~/Documents/paper/lit_<主题>_<日期>/{检索结果}.jsonl" --collection "{主题分类名}" --dry-run

# 正式入库：自动建分类、DOI 查重、打标签
uv run --directory "<技能目录>" scripts/zotero_import.py "~/Documents/paper/lit_<主题>_<日期>/{检索结果}.jsonl" --collection "{主题分类名}" --tag "{标签}"

# 只入库精选的几篇（先按 DOI 筛选）
uv run --directory "<技能目录>" scripts/zotero_import.py "~/Documents/paper/lit_<主题>_<日期>/{检索结果}.jsonl" --only-doi "10.1016/j.jrmge.2023.06.019,10.1007/s40948-024-00807-4"
```

注意：首次在**新电脑/重装后**运行会弹一次 Zotero 授权对话框，引导用户选"总是允许"；无 DOI 的中文文献也可入库（自动跳过 DOI 查重，靠标题精确匹配查重）。

## PDF 全文下载（Sci-Hub，仅人机 MCP 操作）

用户要求"下载某几篇全文/PDF"时执行。**铁律：只用 chrome-devtools MCP 工具模拟人类操作实体 Chrome；严禁任何代码解析网页、fetch、requests、playwright 等程序化抓取——那些手段对 sci-hub 的验证码/反爬全部失效，且会触发封禁。** 完整操作步骤、证书跳过、限速规则、常见失败处理见 `references/scihub-download.md`。

流程摘要（详细见参考文档）：
1. **前置**：确认 9222 端口已有实体 Chrome（用户手动启动：`chrome.exe --remote-debugging-port=9222 --remote-allow-origins=* --user-data-dir="%LOCALAPPDATA%\ChromeDebug9222"`）。MCP `chrome-devtools` 服务器必须在 opencode 配置中启用；pywinauto 已由 uv 装入本技能目录 `.venv`（win32 backend，声明见 `pyproject.toml`）。
2. **导航**：`chrome-devtools_new_page` 打开 `https://sci-hub.st/{DOI}`（镜像按序尝试 `.st`→`.ru`→`.se`）。
3. **过证书警告**（若出现"隐私设置错误"）：点"高级"→"继续前往 ...（不安全）"。
4. **等人机验证自动通过** → 页面跳转到可访问镜像（当前实测为 `sci-net.xyz`）→ PDF 在内置阅读器加载。
5. **下载**：多次 `Tab` 让阅读器工具栏暴露下载按钮 → `chrome-devtools_click` 点"下载" → 弹系统"另存为"对话框。
6. **自动确认保存**：运行 `uv run --directory "<技能目录>" scripts/save_dialog_confirm.py "<任务pdf目录>\<作者>_<年份>_<短题>.pdf"`（win32 backend 定位 `#32770`"另存为"→文件名框填目标路径→点"保存"），PDF 直接落盘到目标位置，**无需人工**。或 `--keep` 存默认目录。
7. **核对与收尾**：核对 PDF 大小/文件头 `%PDF-`；必要时移入 `~/Documents/paper/lit_.../pdf/`；更新 `fulltext_status=downloaded`。

**限速与纪律（强制）**：
- 每篇 DOI 下载之间至少等待 8-15 秒；对同一镜像连续操作 ≤3 篇后停 1 分钟以上，避免触发频控。
- 每个 MCP 动作之间留 ≥1-2 秒（先 `Start-Sleep`）；禁止连续快速点击或批量连发。
- 一次会话最多处理约 10-15 篇；超量后提醒用户分批。
- 若遇到"未能加载 PDF / 重新加载"，点"重新加载"重试 1-2 次仍失败则记为失败并换 DOI/镜像，**不得反复重试同一篇**。
- 浏览器内所有操作必须用 chrome-devtools MCP 工具（snapshot 查看 / click / press_key）；**不得**用 `chrome-devtools_evaluate_script` 解析 DOM、不得注入下载脚本。
- 系统"另存为"对话框**不是**网页：它由脚本 `scripts/save_dialog_confirm.py`（pywinauto win32 backend）处理，等价于人类在弹窗里填路径点保存，不算程序化抓取。

## 常见场景

| 用户请求 | 执行要点 |
|---------|---------|
| "帮我查 XX 方向的文献" | 标准工作流：全库检索 → 输出全量评分排序表 CSV → 用户人工确认后导入 |
| "XX 交叉主题（A 影响 B）" | **轮询迭代检索** iterative_search.py，至少 2-3 轮，交付 Top-N |
| "XX 方向最新进展" | `--sort publication_date:desc` + 近 2-3 年年份范围 |
| "XX 方向经典/高被引文献" | `--min-citations 100 --sort cited_by_count:desc`，年份不限 |
| "XX 期刊最近有什么新文章" | `--journals {缩写}` + date 排序（自动切换白名单严格模式） |
| "XX 主题国内外研究现状" | 全库检索为主，可另跑一轮 `--scope whitelist` 对照白名单内存量；输出分"国际/国内"两节 |
| "只要我订阅的 26 刊" | 加 `--scope whitelist` 或 `--journals/--category` 硬过滤 |
| "这几篇讲的什么" | 优先读取已有 JSONL 里的摘要字段；缺失时用 `search_crossref.py`（`--query "标题"` 或 DOI 字符串）从 CrossRef 取结构化摘要。仅当仍无摘要时才经用户许可 WebFetch 摘要页 |
| "帮我生成参考文献" | 检索 → JSONL → bibtex_manager.py → references.bib |
| "把结果存入 Zotero" | **人机闭环**：用户在排序表 CSV"人工确认"列勾选（或口头指定 DOI）→ Agent 提取 DOI → zotero_import.py --only-doi ... --collection {分类}（先 --dry-run 预检） |
| "导出 Excel 可读的候选文献清单" | 检索时 `-o {主题}.csv`（或对已有 JSONL 跑 paper_db.py export --format csv），指标与评分已并入每行 |
| "下载某几篇全文/PDF" | 只走「PDF 全文下载」人机 MCP 流程（见上节与 `references/scihub-download.md`），严禁程序化抓取 |

## 致谢与许可

- 检索脚本改造自 https://github.com/lingzhi227/agent-research-skills（该仓库未附开源许可证，本技能仅为个人科研用途的内部改造，勿再分发）。
- 候选文献表设计、期刊指标反编造纪律与去重规则借鉴自 https://github.com/Lucaswangzcx/literature-downloader-skill（MIT License），仅用于个人科研用途。
- `references/windows-control/`（含 `save_dialog_confirm.py` 参考其 handle_dialog 思路）来自 spliff7777/windows-control（MIT License），一整套拷贝自 `clawdbot/skills` commit `aca5437`。
