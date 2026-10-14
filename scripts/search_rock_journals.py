#!/usr/bin/env python3
"""岩石力学文献检索（基于 OpenAlex API；默认全库检索 + 26 刊白名单评分加权）。

Self-contained: 仅用标准库。OpenAlex 免费无 Key。

来源致谢：检索逻辑参考 lingzhi227/agent-research-skills 的 search_openalex.py 改造。

用法:
    # 全库检索 rockburst（白名单期刊加分排序，不排除任何期刊）
    python search_rock_journals.py --query "rockburst" --max-results 100 --top-n 40

    # 严格模式：只搜 26 刊（传 --journals/--category 自动切换）
    python search_rock_journals.py --query "rockburst prediction" --category A,G

    # 指定期刊 + 年份范围 + 引用数 + Markdown 输出
    python search_rock_journals.py --query "锚杆支护" --journals RMRE,IJRMMS,岩石力学与工程学报 \
        --year-range 2020-2026 --min-citations 10 --markdown -o result.md

    # 最新文献（按日期排序）/ 经典高被引 / 本地综合评分
    python search_rock_journals.py --query "deep tunnel" --sort publication_date:desc
    python search_rock_journals.py --query "rockburst" --min-citations 100 --sort cited_by_count:desc
    python search_rock_journals.py --query "rockburst water" --max-results 200 --sort score:desc -o top.csv

综合评分（透明四分量，见 lit_common.score_paper）：
    关键词信号(0-5：T=5,a=3,s=1) + 期刊层级(0-3：A=3,B~G=2,H=1,白名单外=0) + 年均被引(0-3) + 近5年(0-1)

输出字段说明见 scripts/lit_common.py 模块注释；期刊指标一律来自
references/journal_metrics.csv（带年份/来源/核验状态），缺失时输出"待核验"，不编造。
"""

import argparse
import json
import sys
import time
import random
import urllib.parse
import urllib.request
from pathlib import Path

import lit_common as lc
import lit_paths
import lit_throttle

OPENALEX_API = "https://api.openalex.org"

# ---- OpenAlex 全局节流器（跨所有 openalex_request 调用，且跨所有脚本进程）----
# OpenAlex 按"出口 IP"限流：同机并跑两个检索脚本时，若各自只在进程内排队，出口速率会叠加
# （0.7 + 0.7 = 1.4 req/s）直接触发 429。节流状态落在 lit_throttle —— 技能目录 .cache/ 下的
# 锁文件 + 操作系统级文件锁 —— 所有脚本进程共享同一条请求队列。
# 默认速率 0.7 请求/秒 ≈ 每请求间隔 ~1.43s；可用 --rate 覆盖。
DEFAULT_RATE_QPS = 0.7
_RATE_QPS = DEFAULT_RATE_QPS


def set_rate(qps: float) -> None:
    """设置全局 OpenAlex 请求速率（每秒请求数，>0），同步更新跨进程节流器。"""
    global _RATE_QPS
    if qps and qps > 0:
        _RATE_QPS = qps
        lit_throttle.set_rate("openalex", qps)


def _throttle() -> None:
    """保证相邻两次 OpenAlex 请求至少间隔 1/_RATE_QPS 秒（跨进程共享队列）。"""
    lit_throttle.throttle("openalex")

# ---- 26 种核心期刊数据库（OpenAlex source ID 已实测解析）----
# 用途：--scope whitelist 时作为硬过滤；默认 --scope all 下仅作评分加权与指标匹配。
# category: A 岩石力学核心 / B 岩土工程 / C 工程地质灾害 / D 隧道
#           E 断裂动力学 / F 能源岩土 / G 中文三岩 / H 其他中文
JOURNALS = {
    "RMRE":   {"name": "Rock Mechanics and Rock Engineering", "sid": "S39260535", "cat": "A"},
    "IJRMMS": {"name": "International Journal of Rock Mechanics and Mining Sciences", "sid": "S129124101", "cat": "A"},
    "AG":     {"name": "Acta Geotechnica", "sid": "S106535470", "cat": "A"},
    "JRMGE":  {"name": "Journal of Rock Mechanics and Geotechnical Engineering", "sid": "S2764891560", "cat": "A"},
    "CG":     {"name": "Computers and Geotechnics", "sid": "S106576117", "cat": "B"},
    "GGM":    {"name": "Geotextiles and Geomembranes", "sid": "S146462558", "cat": "B"},
    "GEO":    {"name": "Géotechnique", "sid": "S170199316", "cat": "B"},
    "JGGE":   {"name": "Journal of Geotechnical and Geoenvironmental Engineering", "sid": "S178493899", "cat": "B"},
    "IJOG":   {"name": "International Journal of Geomechanics", "sid": "S143391730", "cat": "B"},
    "NAG":    {"name": "International Journal for Numerical and Analytical Methods in Geomechanics", "sid": "S10012645", "cat": "B"},
    "CGJ":    {"name": "Canadian Geotechnical Journal", "sid": "S105963835", "cat": "B"},
    "SAF":    {"name": "Soils and Foundations", "sid": "S164417264", "cat": "B"},
    "EG":     {"name": "Engineering Geology", "sid": "S65957803", "cat": "C"},
    "LANDSLIDES": {"name": "Landslides", "sid": "S2645077", "cat": "C"},
    "BEGE":   {"name": "Bulletin of Engineering Geology and the Environment", "sid": "S184406644", "cat": "C"},
    "TUST":   {"name": "Tunnelling and Underground Space Technology", "sid": "S139192911", "cat": "D"},
    "EFM":    {"name": "Engineering Fracture Mechanics", "sid": "S17983605", "cat": "E"},
    "SDEE":   {"name": "Soil Dynamics and Earthquake Engineering", "sid": "S99356198", "cat": "E"},
    "G4":     {"name": "Geomechanics and Geophysics for Geo-Energy and Geo-Resources", "sid": "S4210236237", "cat": "F"},
    "岩石力学与工程学报": {"name": "Chinese Journal of Rock Mechanics and Engineering", "sid": "S2764487033", "cat": "G"},
    "岩土力学":  {"name": "Rock and Soil Mechanics", "sid": "S2764640149", "cat": "G"},
    "岩土工程学报": {"name": "Chinese Journal of Geotechnical Engineering", "sid": "S2764944905", "cat": "G"},
    "土木工程学报": {"name": "China Civil Engineering Journal", "sid": "S4306533413", "cat": "H"},
    "工程地质学报": {"name": "Journal of Engineering Geology", "sid": "S2764975289", "cat": "H"},
    "煤炭学报":  {"name": "Journal of China Coal Society", "sid": "S2764922013", "cat": "H"},
    "水利学报":  {"name": "Journal of Hydraulic Engineering", "sid": "S4306529905", "cat": "H"},
}


def openalex_request(url: str) -> dict:
    headers = {
        "User-Agent": "rock-mech-literature-search/1.0 (mailto:research@example.com)",
        "Accept": "application/json",
    }
    # 全局节流：每次请求前按全局速率排队，避免突发触发按 IP 的 429 封禁
    _throttle()
    req = urllib.request.Request(url, headers=headers)
    # 429 指数退避重试：最长等 ~64s，最多重试 6 次，尽量让同一轮内自恢复
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = min(2 ** (attempt + 1), 60)
                print(f"Rate limited, waiting {wait}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            if e.code in (500, 502, 503, 504):
                wait = min(2 ** (attempt + 1), 30)
                print(f"Server error {e.code}, waiting {wait}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            raise
        except Exception:
            if attempt < 5:
                time.sleep(2)
                continue
            raise
    return {}


def parse_work(work: dict, sid_to_abbr: dict) -> dict | None:
    if not work or not work.get("title"):
        return None
    authors = []
    for authorship in work.get("authorships", []):
        name = (authorship.get("author") or {}).get("display_name", "")
        if name:
            authors.append(name)
    primary = work.get("primary_location", {}) or {}
    source = primary.get("source", {}) or {}
    venue = source.get("display_name", "")
    sid = (source.get("id") or "").rsplit("/", 1)[-1]
    abbr = sid_to_abbr.get(sid, "")
    doi = work.get("doi", "") or ""
    if doi.startswith("https://doi.org/"):
        doi = doi[16:]
    abstract = ""
    inv = work.get("abstract_inverted_index", {})
    if inv:
        word_positions = []
        for word, positions in inv.items():
            for pos in positions:
                word_positions.append((pos, word))
        word_positions.sort()
        abstract = " ".join(w for _, w in word_positions)
    return {
        "title": work["title"],
        "authors": authors,
        "year": work.get("publication_year"),
        "venue": venue,  # 兼容上游 paper_db.py / bibtex_manager.py 的字段格式
        "journal": venue,
        "journal_abbr": abbr,
        "citationCount": work.get("cited_by_count", 0),
        "citations": work.get("cited_by_count", 0),
        "doi": doi,
        "abstract": abstract[:1500],
        "publication_date": work.get("publication_date", ""),
        "openalex_id": work.get("id", ""),
        "pdf_url": (work.get("open_access", {}) or {}).get("oa_url", "") or "",
        "oa_status": (work.get("open_access", {}) or {}).get("oa_status", "") or "",
        "relevance_score": round(work.get("score") or 0, 3),  # OpenAlex 检索相关分
        "type": work.get("type", ""),
    }


def build_tier_map(selected: list[str] | None = None) -> dict[str, int]:
    """构建 {期刊缩写: 层级分}（lit_common.CAT_POINTS），供综合评分使用。"""
    keys = selected if selected is not None else list(JOURNALS.keys())
    return {k: lc.CAT_POINTS.get(JOURNALS[k]["cat"], 0) for k in keys if k in JOURNALS}


def resolve_selection(journals_arg: str | None, category_arg: str | None) -> list[str]:
    """根据 --journals / --category 参数解析期刊缩写列表。"""
    if journals_arg:
        selected = []
        for token in journals_arg.split(","):
            token = token.strip()
            if not token:
                continue
            if token in JOURNALS:
                selected.append(token)
            else:
                # 容错：按名称模糊匹配
                matches = [k for k, v in JOURNALS.items()
                           if token.lower() in v["name"].lower() or token in k]
                if matches:
                    selected.extend(matches)
                else:
                    print(f"Warning: unknown journal '{token}', skipped", file=sys.stderr)
        return selected
    if category_arg:
        cats = {c.strip().upper() for c in category_arg.split(",")}
        return [k for k, v in JOURNALS.items() if v["cat"] in cats]
    return list(JOURNALS.keys())


def search(query: str, sids: list[str] | None, sid_to_abbr: dict,
           max_results: int, year_range: str | None,
           min_citations: int, sort: str, metrics_db: dict | None = None,
           scope: str = "all") -> list[dict]:
    """scope="all"：全 OpenAlex 检索（白名单只用于打 abbr 标签，供评分/指标）；
    scope="whitelist"：仅 26 刊硬过滤。sids 为 None 时同样走全库。"""
    if metrics_db is None:
        metrics_db = lc.load_metrics()
    filters = []
    if scope == "whitelist":
        if not sids:
            raise ValueError("scope=whitelist requires source ids")
        filters.append(f"primary_location.source.id:{'|'.join(sids)}")
    if year_range:
        parts = year_range.split("-")
        if len(parts) == 2:
            filters.append(f"publication_year:{parts[0]}-{parts[1]}")
    if min_citations > 0:
        filters.append(f"cited_by_count:>{min_citations}")
    filters.append("type:article")  # 只要期刊论文，剔除会议/章节/勘误

    papers, page = [], 1
    per_page = min(50, max_results)
    while len(papers) < max_results:
        params = {
            "search": query,
            "per_page": per_page,
            "page": page,
            "filter": ",".join(filters),
            "sort": sort,
        }
        url = f"{OPENALEX_API}/works?{urllib.parse.urlencode(params)}"
        try:
            resp = openalex_request(url)
        except Exception as e:
            print(f"Warning: search failed at page {page}: {e}", file=sys.stderr)
            break
        results = resp.get("results", [])
        if not results:
            break
        for work in results:
            if len(papers) >= max_results:
                break
            paper = parse_work(work, sid_to_abbr)
            if paper:
                papers.append(lc.enrich_paper(paper, metrics_db))
        total = resp.get("meta", {}).get("count", 0)
        if page * per_page >= total:
            break
        page += 1
        time.sleep(0.2)
    return papers


def _journal_cell(paper: dict) -> str:
    """期刊缩写后附已核验的 IF（待核验/无JCR收录时不显示，避免误导）。"""
    label = paper.get("journal_abbr") or paper.get("journal") or ""
    impact = paper.get("impact_factor", "")
    if impact and impact != lc.PENDING:
        return f"{label}({impact})"
    return label


def to_markdown(papers: list[dict], query: str) -> str:
    lines = [f"# 检索结果：{query}", "",
             f"共 {len(papers)} 篇（按检索相关性排序）", "",
             "| # | 标题 | 作者 | 年份 | 期刊(IF) | 被引 | DOI |",
             "|---|------|------|------|------|------|-----|"]
    for i, p in enumerate(papers, 1):
        authors = ", ".join(p["authors"][:3]) + (" et al." if len(p["authors"]) > 3 else "")
        doi_link = f"[{p['doi']}](https://doi.org/{p['doi']})" if p["doi"] else "—"
        lines.append(f"| {i} | {p['title']} | {authors} | {p['year']} | "
                     f"{_journal_cell(p)} | {p['citations']} | {doi_link} |")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="岩石力学文献检索（OpenAlex；默认全库+白名单评分）")
    parser.add_argument("--query", required=True, help="检索关键词（中英文均可）")
    parser.add_argument("--journals", help="期刊缩写列表，逗号分隔（传入则自动切换为 whitelist 严格模式）")
    parser.add_argument("--category", help="期刊类别，逗号分隔（A核心 B岩土 C地质 D隧道 E断裂 F能源 G三岩 H其他中文；传入则切换为 whitelist 严格模式）")
    parser.add_argument("--scope", choices=["all", "whitelist"], default="all",
                        help="all=全 OpenAlex 检索，白名单作评分加分（默认）；whitelist=仅 26 刊")
    parser.add_argument("--top-n", type=int, default=0,
                        help="按综合评分只交付前 N 篇（0=不截断）")
    parser.add_argument("--max-results", type=int, default=30)
    parser.add_argument("--year-range", help="年份范围，如 2020-2026")
    parser.add_argument("--min-citations", type=int, default=0)
    parser.add_argument("--sort", default="relevance_score:desc",
                        help="relevance_score:desc / cited_by_count:desc / publication_date:desc / score:desc(本地综合评分)")
    parser.add_argument("--rate", type=float, default=None,
                        help="OpenAlex 请求速率（每秒请求数），默认 0.7（约每1.4秒一次，保守防封IP）。可调大如 2.0 提速")
    parser.add_argument("--output", "-o", help="输出文件（.jsonl / .csv 候选文献表 / .md）")
    parser.add_argument("--task", help="任务根目录（标准布局，见 scripts/lit_paths.py）；"
                                       "配合 -o 时按文件类型自动落位：.csv→03_final/，.md→04_reports/，.jsonl→01_sources/")
    parser.add_argument("--markdown", action="store_true", help="输出 Markdown 表格")
    args = parser.parse_args()

    if args.task:
        lit_paths.init_task(args.task, args.query)
        if args.output and not Path(args.output).is_absolute():
            cat = ("03_final" if args.output.endswith(".csv")
                   else "04_reports" if args.output.endswith(".md") else "01_sources")
            args.output = str(lit_paths.p(args.task, cat, Path(args.output).name))
        args.task = Path(args.task)

    metrics_db = lc.load_metrics()
    tier_map = build_tier_map()

    if args.rate is not None:
        set_rate(args.rate)
    sys.stderr.write(f"OpenAlex 全局速率：{_RATE_QPS} req/s（约 {1/_RATE_QPS:.1f}s/请求）\n")

    if args.journals or args.category:
        if args.scope == "all":
            sys.stderr.write("Note: --journals/--category given -> switching to whitelist strict mode\n")
        args.scope = "whitelist"
        selected = resolve_selection(args.journals, args.category)
    else:
        selected = list(JOURNALS.keys())  # 全库模式下仍需 sid→缩写 映射打标签
    if not selected:
        print("Error: no valid journals selected", file=sys.stderr)
        sys.exit(1)
    scope_desc = "ALL OpenAlex (whitelist as bonus)" if args.scope == "all" else f"{len(selected)} whitelist journals"
    print(f"Scope: {scope_desc}", file=sys.stderr)

    sid_to_abbr = {JOURNALS[k]["sid"]: k for k in selected}
    fetch_sort = "relevance_score:desc" if args.sort == "score:desc" else args.sort
    papers = search(args.query, list(sid_to_abbr.keys()) if args.scope == "whitelist" else None,
                    sid_to_abbr, args.max_results, args.year_range, args.min_citations,
                    fetch_sort, metrics_db=metrics_db, scope=args.scope)

    # 本地综合评分（供 CSV 列与 score:desc 排序）
    for p in papers:
        lc.score_paper(p, tier_map)
    if args.sort == "score:desc":
        papers = lc.rank_papers(papers, top_n=args.top_n or len(papers))

    use_markdown = args.markdown or (args.output and args.output.endswith(".md"))
    use_csv = args.output and args.output.endswith(".csv")
    if args.output:
        if use_csv:
            if args.top_n > 0 and args.sort != "score:desc":
                papers = lc.rank_papers(papers, args.top_n)
            lc.write_candidates_csv(papers, args.output)
            print(f"Wrote {len(papers)} papers (candidate CSV) to {args.output}", file=sys.stderr)
        else:
            with open(args.output, "w", encoding="utf-8") as f:
                if use_markdown:
                    f.write(to_markdown(papers, args.query))
                else:
                    for p in papers:
                        f.write(json.dumps(p, ensure_ascii=False) + "\n")
            print(f"Wrote {len(papers)} papers to {args.output}", file=sys.stderr)
    else:
        if use_markdown:
            print(to_markdown(papers, args.query))
        else:
            for p in papers:
                print(json.dumps(p, ensure_ascii=False))
    print(f"Found {len(papers)} papers", file=sys.stderr)


if __name__ == "__main__":
    main()
