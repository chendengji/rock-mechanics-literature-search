#!/usr/bin/env python3
"""共享工具库：期刊指标合并 / 去重 / 候选文献表 CSV 导出（仅标准库）。

设计借鉴 Lucaswangzcx/literature-downloader-skill（MIT License），三条纪律：

1. 期刊指标反编造
   - 影响因子/JCR 分区一律取自 references/journal_metrics.csv，
     每行带 metric_year / metric_source / metric_status（已核验/待复核/待核验/无JCR收录）；
   - 表中没有的值输出"待核验"，严禁现场编造数字；
   - 不混称 JIF / SJR / CiteScore，非 JCR 口径的数值只能进备注。

2. 候选文献表
   - 中文列名、指标并入每一行（用户无需另开指标表对照）；
   - utf-8-sig 编码，Excel 双击直开不乱码。

3. 去重规则（优先级从高到低）
   DOI 精确匹配 → 数据源 ID(openalex_id/arxiv_id/paperId) → 标准化题名精确匹配
   → 标题 Jaccard 相似度兜底（默认 0.8，兼容英式/美式拼写差异）；
   重复记录合并为一条信息最全的记录（失败/缺失不删行）。
"""
from __future__ import annotations

import csv
import hashlib
import re
from datetime import date
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_METRICS_CSV = SCRIPT_DIR.parent / "references" / "journal_metrics.csv"

PENDING = "待核验"
METRIC_FIELDS = ["impact_factor", "jcr_quartile", "metric_year", "metric_source", "indexing", "metric_status"]

# 面向用户的候选文献表中文名（借鉴 literature-downloader 的"中文交付物"原则）
# "人工确认"列：人机闭环工作流——用户在 Excel 里勾选后，Agent 按 DOI 批量导入 Zotero
CANDIDATE_COLUMNS_ZH = [
    "序号", "题名", "作者", "年份", "期刊或来源", "期刊缩写",
    "影响因子", "JCR分区", "指标年份", "指标来源", "索引情况", "指标状态",
    "被引数", "年均被引", "综合评分", "DOI", "文章地址", "OA入口",
    "全文状态", "下一步建议", "检索词", "相关性信号", "人工确认",
]


# ---------- 规范化 ----------

def normalize_doi(value: object) -> str:
    value = str(value or "").strip()
    value = re.sub(r"^https?://(dx\.)?doi\.org/", "", value, flags=re.I)
    value = re.sub(r"^doi:\s*", "", value, flags=re.I)
    return value.strip().lower()


def normalize_journal(value: object) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", str(value or "").casefold())


def normalize_title(value: object) -> str:
    text = str(value or "").casefold()
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", text)
    return " ".join(text.split())


def tokenize(title: object) -> set[str]:
    """英文按词、中文按字切分，用于标题相似度兜底。"""
    text = normalize_title(title)
    latin = set(re.findall(r"[a-z0-9]+", text))
    cjk = set(re.findall(r"[\u4e00-\u9fff]", text))
    return latin | cjk


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def source_id(record: dict) -> str:
    for key in ("arxiv_id", "paperId", "openalex_id"):
        value = str(record.get(key) or "").strip()
        if value:
            return value.rsplit("/", 1)[-1]
    return ""


# ---------- 期刊指标 ----------

def load_metrics(path=None) -> dict:
    """读 journal_metrics.csv → {规范化刊名或缩写: 指标行}。文件不存在返回空表。"""
    path = Path(path or DEFAULT_METRICS_CSV)
    db: dict[str, dict[str, str]] = {}
    if not path.exists():
        print(f"Warning: metrics table not found: {path}", file=__import__("sys").stderr)
        return db
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            clean = {k: (v or "").strip() for k, v in row.items()}
            for key in (clean.get("abbr"), clean.get("journal")):
                norm = normalize_journal(key)
                if norm:
                    db[norm] = clean
    return db


def metrics_for(journal_name: object, abbr: object = "", db: dict | None = None) -> dict:
    """查一本刊的指标；查不到的值一律填"待核验"，不编造。"""
    db = db if db is not None else load_metrics()
    row = db.get(normalize_journal(abbr)) or db.get(normalize_journal(journal_name)) or {}
    return {field: row.get(field) or PENDING for field in METRIC_FIELDS}


# ---------- 期刊层级与综合评分（白名单=评分项，不是排除项） ----------

# 26 删白名单按类别加分：A核心>B-F类/G三岩>H附刊；白名单外=0 分（不扣分不排除）
CAT_POINTS = {"A": 3, "B": 2, "C": 2, "D": 2, "E": 2, "F": 2, "G": 2, "H": 1}

# 相关信号标签
LBL_STRONG = "T"        # 标题双侧命中（强）
LBL_ABSTRACT = "a"      # 摘要双侧命中
LBL_SINGLE = "s"        # 仅单侧命中（兜底填充用，弱信号）
LBL_NONE = "-"          # 无命中
LBL_EXCLUDED = "x"      # 命中假阳性排除表


def label_paper(paper: dict, side_a: str, side_b: str, exclude: str = "") -> str:
    """给单条记录打相关信号标签 T/a/s/-/x。

    排除表两级语义（防止误杀）：
    - 标题命中排除词 → x（硬淘汰：标题即暴露主题错位）；
    - 仅摘要命中排除词 → 不剔除，只降一级（T→a / a→s）：
      相关文献摘要里顺带提到 seepage/hydraulic 很常见，直接删会误杀。
    """
    t = paper.get("title") or ""
    a = paper.get("abstract") or ""
    if exclude and re.search(exclude, t, re.I):
        return LBL_EXCLUDED
    t_a = re.search(side_a, t, re.I)
    t_b = re.search(side_b, t, re.I)
    a_a = re.search(side_a, a, re.I)
    a_b = re.search(side_b, a, re.I)
    if t_a and t_b:
        lab = LBL_STRONG
    elif a_a and a_b:
        lab = LBL_ABSTRACT
    elif t_a or t_b or a_a or a_b:
        lab = LBL_SINGLE
    else:
        return LBL_NONE
    if exclude and re.search(exclude, a, re.I) and lab in (LBL_STRONG, LBL_ABSTRACT):
        lab = LBL_ABSTRACT if lab == LBL_STRONG else LBL_SINGLE
    return lab


def score_paper(paper: dict, tier_map: dict | None = None,
                label: str | None = None, this_year: int | None = None) -> dict:
    """透明四分量评分（写入 paper["score"] 与 paper["score_parts"]）：

    score = 关键词信号(0-5) + 期刊层级(0-3) + 学术影响(0-3) + 时效(0-1)

    - 关键词（主导项加权，防止高被引弱相关压过低被引强相关）：
      T=5 / a=3 / s=1
    - 期刊层级：白名单 A=3，B~G=2，H=1，白名单外=0（仅不加权，非惩罚）
    - 学术影响：年均被引 >=10→3，>=3→2，>=1→1，其余 0
    - 时效：近 5 年 →1
    """
    this_year = this_year or date.today().year
    label = label or paper.get("relevance_label") or LBL_NONE
    kw = {LBL_STRONG: 5, LBL_ABSTRACT: 3, LBL_SINGLE: 1}.get(label, 0)
    jr = (tier_map or {}).get(paper.get("journal_abbr") or "", 0)
    try:
        cpy = float(paper.get("cpy") or 0)
    except (TypeError, ValueError):
        cpy = 0.0
    im = 3 if cpy >= 10 else 2 if cpy >= 3 else 1 if cpy >= 1 else 0
    try:
        yr = int(paper.get("year") or 0)
    except (TypeError, ValueError):
        yr = 0
    rc = 1 if yr and (this_year - yr) <= 5 else 0
    parts = {"kw": kw, "journal": jr, "impact": im, "recency": rc}
    paper["score"] = sum(parts.values())
    paper["score_parts"] = parts
    return paper


def rank_papers(papers: list[dict], top_n: int = 0) -> list[dict]:
    """按综合评分降序排列；top_n>0 时截取前 top_n 篇，否则返回全部（人审模式）。"""
    papers.sort(key=lambda p: (-p.get("score", 0),
                               -(p.get("cpy") or 0),
                               -(p.get("relevance_score") or 0)))
    n = int(top_n or 0)
    return papers[:n] if n > 0 else papers


# ---------- 去重与合并 ----------

_JOIN_FIELDS = {"query"}


def merge_records(dst: dict, src: dict) -> None:
    """把重复记录 src 并入 dst：填空缺、取更全值、并集列表，绝不丢行。"""
    for key, value in src.items():
        if value in (None, "", [], {}):
            continue
        cur = dst.get(key)
        if cur in (None, "", [], {}):
            dst[key] = value
        elif key == "abstract":
            if len(str(value)) > len(str(cur)):
                dst[key] = value
        elif isinstance(cur, list) and isinstance(value, list):
            dst[key] = list(dict.fromkeys([*cur, *value]))
        elif key in _JOIN_FIELDS and value != cur:
            dst[key] = f"{cur} | {value}"
        elif key in ("citationCount", "citations"):
            try:
                dst[key] = max(int(cur or 0), int(value or 0))
            except (TypeError, ValueError):
                pass
    # 统一 citationCount / citations 双键为同一个最大值
    counts = []
    for k in ("citationCount", "citations"):
        v = dst.get(k)
        if v not in (None, ""):
            try:
                counts.append(int(v))
            except (TypeError, ValueError):
                pass
    if counts:
        best = max(counts)
        dst["citationCount"] = dst["citations"] = best
    dst["duplicate_count"] = int(dst.get("duplicate_count") or 1) + 1


def dedupe_papers(records: list[dict], jaccard_threshold: float = 0.8) -> list[dict]:
    """DOI → 数据源 ID → 标准化题名 → 标题 Jaccard 兜底；重复合并保留首见位置。"""
    kept: list[dict] = []
    by_doi: dict[str, dict] = {}
    by_id: dict[str, dict] = {}
    by_ntitle: dict[str, dict] = {}
    token_sets: list[set] = []

    for rec in records:
        doi = normalize_doi(rec.get("doi"))
        rid = source_id(rec)
        ntitle = normalize_title(rec.get("title"))

        target = None
        if doi and doi in by_doi:
            target = by_doi[doi]
        elif rid and rid in by_id:
            target = by_id[rid]
        elif ntitle and ntitle in by_ntitle:
            target = by_ntitle[ntitle]
        elif ntitle:
            toks = tokenize(ntitle)
            for kept_rec, prev in zip(kept, token_sets):
                if jaccard(toks, prev) >= jaccard_threshold:
                    target = kept_rec
                    break

        if target is None:
            kept.append(rec)
            if doi:
                by_doi[doi] = rec
            if rid:
                by_id[rid] = rec
            if ntitle:
                by_ntitle[ntitle] = rec
            token_sets.append(tokenize(ntitle))  # 无题也占位，保持索引对齐
        else:
            merge_records(target, rec)
    return kept


# ---------- 记录扩充 ----------

def enrich_paper(paper: dict, metrics_db: dict | None = None) -> dict:
    """给单条检索结果补齐候选表字段：record_id、文章地址、年均被引、期刊指标、全文状态。"""
    doi = normalize_doi(paper.get("doi"))
    if doi:
        paper["doi"] = doi
        paper.setdefault("landing_page_url", f"https://doi.org/{doi}")
    else:
        paper.setdefault("landing_page_url", paper.get("openalex_id", ""))

    key_src = doi or normalize_title(paper.get("title")) or str(paper.get("openalex_id"))
    if key_src:
        paper.setdefault("record_id", hashlib.sha1(key_src.encode("utf-8")).hexdigest()[:12])

    try:
        year = int(paper.get("year") or 0)
    except (TypeError, ValueError):
        year = 0
    cites = paper.get("citationCount") or paper.get("citations") or 0
    try:
        cites = int(cites)
    except (TypeError, ValueError):
        cites = 0
    age = max(1, date.today().year - year + 1) if year else 1
    paper["cpy"] = round(cites / age, 1)

    paper.update(metrics_for(paper.get("journal"), paper.get("journal_abbr"), metrics_db))

    paper["fulltext_status"] = "有OA/PDF入口" if paper.get("pdf_url") else "未获取全文"
    paper["next_step"] = ("可从文章地址获取PDF" if paper.get("pdf_url")
                          else "经学校图书馆/馆际互借获取，或邮件联系作者")
    return paper


# ---------- 候选文献表 CSV ----------

def fmt_authors(paper: dict, limit: int = 3) -> str:
    authors = paper.get("authors") or []
    if isinstance(authors, str):
        return authors
    if len(authors) > limit:
        return "; ".join(authors[:limit]) + " et al."
    return "; ".join(authors)


def relevance_signal(paper: dict) -> str:
    lab = paper.get("relevance_label")
    zh = {LBL_STRONG: "T(标题双命中)", LBL_ABSTRACT: "a(摘要双命中)",
          LBL_SINGLE: "s(单侧命中)", LBL_EXCLUDED: "x(已排除)"}
    if lab:
        return zh.get(lab, str(lab))
    hit = paper.get("title_hit")
    if hit is True:
        return zh[LBL_STRONG]
    if hit is False:
        return zh[LBL_ABSTRACT]
    return ""


def candidate_row(index: int, paper: dict) -> dict:
    query = paper.get("query") or ""
    if isinstance(query, (list, tuple)):
        query = " | ".join(str(q) for q in query)
    return {
        "序号": index,
        "题名": paper.get("title", ""),
        "作者": fmt_authors(paper),
        "年份": paper.get("year", ""),
        "期刊或来源": paper.get("journal", ""),
        "期刊缩写": paper.get("journal_abbr", ""),
        "影响因子": paper.get("impact_factor", PENDING),
        "JCR分区": paper.get("jcr_quartile", PENDING),
        "指标年份": paper.get("metric_year", PENDING),
        "指标来源": paper.get("metric_source", PENDING),
        "索引情况": paper.get("indexing", PENDING),
        "指标状态": paper.get("metric_status", PENDING),
        "被引数": paper.get("citationCount", paper.get("citations", "")),
        "年均被引": paper.get("cpy", ""),
        "综合评分": paper.get("score", ""),
        "DOI": paper.get("doi", ""),
        "文章地址": paper.get("landing_page_url", ""),
        "OA入口": paper.get("pdf_url", ""),
        "全文状态": paper.get("fulltext_status", ""),
        "下一步建议": paper.get("next_step", ""),
        "检索词": query,
        "相关性信号": relevance_signal(paper),
        "人工确认": "",
    }


def write_candidates_csv(papers: list[dict], path) -> None:
    """写出候选文献表 CSV（utf-8-sig，Excel 直开）。"""
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CANDIDATE_COLUMNS_ZH, extrasaction="ignore")
        writer.writeheader()
        for i, paper in enumerate(papers, 1):
            writer.writerow(candidate_row(i, paper))
