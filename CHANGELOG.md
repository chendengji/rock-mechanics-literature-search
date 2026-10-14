# 变更记录（Changelog）

本文件集中管理本技能的版本历史、过往变更与应用调整记录。日常检索/下载使用无需读取；
如要了解"某个设计是何时引入、为什么这样"，查阅这里即可。当前活跃设计以
`SKILL.md` 与各 `references/` 文档为准，与本文档冲突时以 `SKILL.md` 为准。

格式：`## [YYYY-MM-DD] 标题`，变更按时间倒序排列，最新在上。

## [2026-09-30] 产出目录标准化：新增 lit_paths.py 并改造既有任务目录

- **问题**：过去每次检索都把脚本、原始命中、中间层、交付表、报告**平铺在任务目录根目录**。
  本次孔隙-微裂纹任务根目录堆了 21 个文件 + 2 个原始数据目录，助手和用户都得靠记忆判断
  "哪份是最终成果、哪份是中间产物"，最终两份 Markdown 报告和两张交付表完全看不出主次。
- **新增 `scripts/lit_paths.py`**：把九类目录（`00_config`/`01_sources`/`02_intermediate`/
  `03_final`/`04_reports`/`05_pdf`/`06_scripts`/`07_logs`/`99_archive`）固化成代码，
  提供 `init / new / path / manifest / migrate` 五个子命令。`init` 一次性生成骨架、
  带"先看哪里"导航的 `README.md`、`.lit_task.json` 标记文件与 `MANIFEST.csv` 文件清单。
  `migrate` 按文件名规则把旧的平铺目录迁进标准布局并留 `07_logs/migrate.log`。
- **`iterative_search.py` / `search_rock_journals.py` 新增 `--task`**：给了任务根目录后
  `-o` 只需写文件名，脚本按类型自动落位（.csv→`03_final`、.md→`04_reports`、.jsonl→`01_sources`；
  迭代检索的逐轮命中与各轮分析分别进 `01_sources`/`04_reports`），结束时自动刷新清单。
  不给 `--task` 时行为与旧版完全一致，不破坏既有调用。
- **SKILL.md** 的"产出目录规范"改写为九类目录表 + 五条硬性规则（最终成果只在 `03_final`、
  报告只在 `04_reports`、根目录只留 README/MANIFEST/标记文件、每阶段刷新清单、收尾跑 migrate）。
- **已迁移** `lit_pore_microcrack_progressive_20260928`：20 个平铺文件按规则归位，
  最终表在 `03_final/`（2 个），报告在 `04_reports/`（3 个），原始命中 121 个文件在 `01_sources/raw*`。
- **小坑**：`migrate` 第一版会把已建好的类别目录和 `.lit_task.json` 自己也当成待迁移文件
  搬进 `99_archive`（`classify` 对未知名默认归档）。已加 `CATEGORIES`/`_KEEP_AT_ROOT` 白名单跳过，
  并把 `init_task` 从扫描前挪到移动之后，避免"先建骨架再被自己搬走"。

## [2026-09-06] 节流器修复：系统重启后锁文件旧时间戳导致无限 sleep

- **问题**：`lit_throttle.py` 锁文件存的是 `time.monotonic()` 时间戳。系统重启后
  monotonic 归零，锁文件里的旧值反而**远大于**当前值，`wait = last + gap - now`
  变成一个巨大的正数，`time.sleep(wait)` 直接把整个检索脚本卡死（实测卡 5.7 天级别）。
  原注释"重启后旧值远小于当前时间"的判断与实际相反。
- **修复**：新增 `_MAX_SANE_WAIT = 60.0`，当算出的等待间隔明显异常（>60 秒）时视为
  该时间戳失效、直接跳过等待继续排队。正常节流下相邻请求间隔仅 1.4s 级，60s 远不会误伤。
- 触发场景：系统上次在 9/4 运行过检索后关机，9/6 开机再跑 `search_rock_journals.py`
  即卡死；删除 `.cache/rate_openalex.lock` 可临时恢复，本修复已从根上解决。

## [2026-08-29] OpenAlex 跨进程节流 + 预算耗尽告警

- **问题**：旧节流器 `_LAST_REQUEST_TIME` 是模块内变量、锁只是 `threading.Lock`，
  **只在单进程内有效**。同机并跑两个检索脚本时出口速率叠加（0.7 + 0.7 = 1.4 req/s），
  容易触发 OpenAlex 429。
- **新增 `scripts/lit_throttle.py`**：把"最近一次请求时间"落到技能目录
  `.cache/rate_<endpoint>.lock`，用 `msvcrt` 操作系统级文件锁串行化，所有脚本进程
  共享同一条队列；按 endpoint 名隔离（openalex/s2/crossref），速率可 `set_rate` 覆盖；
  非 Windows 或锁文件不可写时退回进程内节流，不报错。
- **已接入**：`search_rock_journals.py`（替换原 `_throttle`）、`search_openalex.py`
  （替换原 `random.uniform(0.8, 2.5)` 礼貌延迟——随机延迟不保证最小间隔）。
- **实测验证**：两个并发进程各打 5 次节流（间隔 5s），A 用时 20.02s、B 等锁后 43.43s、
  总墙钟 45.15s —— 跨进程串行化生效（若未串行化应各约 20s、总约 20s）。
- **重要：OpenAlex 的 429 有两种，必须区分**。2026-08-29 实测，限速到 0.7 req/s 仍 429，
  响应体明确是**每日预算耗尽**而非速率：
  `{"error":"Rate limit exceeded","message":"Insufficient budget. This request costs $0.001
  but you only have $0 remaining. Resets at midnight UTC.","dailyRemainingUsd":0,"retryAfter":40350}`。
  匿名请求按美元计费（约 $0.001/请求），预算用尽后**降速无效**，只能等 UTC 零点重置
  或买额度。节流器只解决"突发速率"，解决不了"预算"。
- **不受影响的替代源**：`search_crossref.py` 当日实测正常（并捞到经典条目
  Nikolaev 1962 *Driving Steel Piles by Electroosmosis*，DOI `10.1007/978-1-4757-0453-2_5`）；
  `search_semantic_scholar.py` 走 S2 自有配额。OpenAlex 预算耗尽时改用这两者，
  或用 `search_federated.py` 自动跳过失效源。大检索任务建议分批在一天内完成。
- SKILL.md 的"凭据与限速注意"与"OpenAlex 限流保护"两处同步补充上述区分与处置办法。

## [2026-08-29] Python 运行环境迁移至 uv（清理手装 Python）

- **背景**：本机 Python 由 uv 统一管理，此前误装了独立 Python 3.12.10
  （`AppData\Local\Programs\Python\Python312`，3.12.10），与 uv 托管的
  3.12.14 重复且绕过 uv，已彻底删除其目录及用户 PATH 三项
  （`Python312\Scripts\`、`Python312\`、`Python\Launcher\`）。
- **调用方式**：全部脚本改为 `uv run --directory "<本技能目录>" scripts/xxx.py`。
  uv 按本技能目录 `pyproject.toml` 选用 uv 托管的 CPython 3.12.x，
  自动构建/复用本技能目录 `.venv`；**不再依赖全局 `python` 命令**。
- **依赖声明**：新增 `pyproject.toml`（`requires-python = ">=3.12,<3.13"`，
  `pywinauto==0.6.9`、`pyautogui==0.9.54`、`pillow`），依赖由 uv 装入
  本技能目录 `.venv`，取代原"基于手装 Python 手工 pip 安装"。
- **Key 缓存位置**：`zotero_import.py` 的本地 API Key 缓存从
  `~/.workbuddy/zotero_local.json` 改到本技能目录 `.cache/zotero_local.json`
  ——`.workbuddy` 是其他软件的目录，不应占用。
- SKILL.md、`references/scihub-download.md` 中所有 `python scripts/...`
  示例同步改为 `uv run --directory ...`。

## [2026-08-29] 下载闭环自动化收尾

- 全链路打通 `Sci-Hub 全文下载`：仅 chrome-devtools MCP 人机操作实体 Chrome，
  PDF 阅读器"下载"按钮触发系统"另存为"对话框。
- 新增 `scripts/save_dialog_confirm.py`：pywinauto **win32 backend** 定位
  `#32770`"另存为"对话框（UIA backend 对中文系统对话框不可见），填目标路径、
  点"保存"，实现全自动落盘。等价人类弹窗操作，不解析网页。
- 并入第三方技能 `references/windows-control/`（MIT，spliff7777），来源
  `clawdbot/skills` commit `aca5437`；上游版本 v2.0（2026-02-02），含
  Dialog/UI Elements/点击元素等窗口自动化脚本。
- Sci-Hub 下载操作规范沉淀到 `references/scihub-download.md`。
- 清理无效方案：删除系统浏览器下载目录设置脚本（CDP `Browser.setDownloadBehavior`
  对阅读器"下载"按钮无效，另存为对话框仍弹出），改由 `save_dialog_confirm.py` 接管。
- 运行环境统一：全部脚本使用本机 Python 3.12（`C:\Users\QZ\AppData\Local\Programs\Python\Python312\python.exe`）；
  检索/导入类脚本仅依赖标准库；PDF 下载相关脚本基于该环境安装 pywinauto 0.6.9、pyautogui 0.9.54、pillow。

## [2026-08-26] 白名单定位变更 + 指标表联网核实 + 评分审计

- **白名单定位变更**：默认检索改为全 OpenAlex 库，26 刊仅作综合评分加分
  （A +3 / B~G +2 / H +1），不再排除白名单外文献；仅在用户指定
  `--journals/--category` 或 `--scope whitelist` 时启用硬过滤。
- **期刊指标表联网核实**：`references/journal_metrics.csv` 每行带
  metric_year / metric_source / metric_status（已核验/待复核/待核验/无JCR收录）；
  白名单外期刊输出"待核验"。
- **相关性标签审计**：排除表采用两级语义——标题命中排除词 → `x`（硬淘汰）；
  仅摘要命中 → 降一级不剔除（T→a / a→s），避免误杀相关文献。
- **评分审计**：关键词信号作为主导项加权（T=5 / a=3 / s=1），
  防止高被引弱相关文献压过低被引强相关文献。
- 轮询迭代篇期实验复测（含水率×岩爆实验，A/G/H 共 11 刊）：B 侧词表补齐
  国际术语变体（proneness、strainburst、bursts、burst tendency/potential）并回写
  `iterative_search.py` 默认词表；固定术语改用引号词组查询降噪。

## [2026-08-25] 轮询迭代检索上线（含水率×岩爆实测）

- 新增 `scripts/iterative_search.py`：显式多轮迭代检索（每轮 3 组并行 →
  相关性评价/缺口分析 → 补词/优化）。
- 26 刊 OpenAlex source ID 全部实测解析并内置于
  `scripts/search_rock_journals.py` 的 JOURNALS 字典。
- 轮询迭代首次实测（含水率×岩爆）：三轮 21 组词 → 454 命中 → 270 去重 →
  14 候选，验证交叉主题必须多轮、单次检索漏检率高。
- `scripts/bibtex_manager.py` 修补：带期刊名+DOI 的条目输出 `@article`。

## [2026-08-24] 检索体系初建

- 新增核心检索脚本：`search_rock_journals.py`（OpenAlex）、
  `search_openalex.py`、`search_crossref.py`、`search_semantic_scholar.py`、
  `search_federated.py`（多库聚合）。
- 新增 `scripts/lit_common.py`：期刊指标合并、多级去重、相关信号标签、透明评分、候选表 CSV。
- 新增 `scripts/lit_secrets.py`：S2 API Key 自动加载与全局节流器。
- 新增 `scripts/paper_db.py`（多来源合并去重）与 `scripts/zotero_import.py`（入库 Zotero）。
- 26 刊白名单数据库建立；`references/journals.md` 期刊知识库、`references/search-strategies.md`
  网络兜底手册同步建立。
- 候选文献表设计、期刊指标反编造纪律与去重规则借鉴
  `Lucaswangzcx/literature-downloader-skill`（MIT）；检索逻辑参考
  `lingzhi227/agent-research-skills` 改造（详见 SKILL.md 致谢）。