#!/usr/bin/env python3
"""多库聚合检索：OpenAlex + Crossref + Semantic Scholar（可选 arXiv）→ 合并去重 → 组合评分 → CSV/JSON 输出。

单库检索（search_rock_journals.py 只查 OpenAlex）存在覆盖盲区：Crossref 对 DOI/出版社数据更全，
Semantic Scholar 的相关性和摘要召回更好。本脚本一次轮询多个大开源数据库，合并去重后统一评分排序。

输出三件套（-o 前缀 PREFIX）：
  PREFIX_检索结果总表.csv   全部去重结果，含评分明细，Excel 可直接打开（utf-8-sig）
  PREFIX_高质量论文.json    筛选后的高质量论文（综合评分 >= --min-score 且主题相关），完整元数据
  PREFIX_合并去重.jsonl     全部记录（兼容 paper_db / bibtex_manager / zotero_import）

组合评分（0-100，归一化）：
  相关性 (0-33)：include 词命中标题 +8/词（cap 24）、命中摘要 +3/词（cap 9）；无命中记 0 分
  被引   (0-30)：min(30, 10*log10(1+年均被引))
  期刊   (0-15)：26 刊白名单按类别 A=15, B/C/D=12, E/F/H=10, G=8；白名单外 4
  新近   (0-10)：<=2 年 10 分，<=5 年 8 分，<=10 年 5 分，更早 2 分
  开放获取 (0-5)：有 OA/PDF 链接 +5

用法:
    # 默认三库（OpenAlex+Crossref+S2），限 26 核心刊
    python search_federated.py --query "rockburst water content" --year-range 2015-2026 -o result

    # 全库含 arXiv 预印本、不限期刊白名单、只要前 15 篇高质量
    python search_federated.py --query "tunnel lining deterioration" --sources openalex,crossref,s2,arxiv \
        --all-journals --top 15 -o result

    # Semantic Scholar 无 Key 时限流严重，可传 Key 或设环境变量 S2_API_KEY
    python search_federated.py --query "rock creep" --s2-api-key XXX -o result

设计参考 Lucaswangzcx/literature-downloader-skill 的分层筛选思想（include/exclude 词表、排除原因落盘），
打分公式为本技能定制（被引+期刊层次+新近度信号，替代其纯关键词计数）。
"""
import argparse
import csv
import io
import json
import math
import os
import re
import sys
import time
import random
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from search_rock_journals import JOURNALS, resolve_selection, openalex_request  # noqa: E402
from lit_secrets import s2_api_key, s2_throttle, s2_set_rate  # noqa: E402

CROSSREF_API = "https://api.crossref.org/works"
S2_API = "https://api.semanticscholar.org/graph/v1"
ARXIV_API = "http://export.arxiv.org/api/query"
HEADERS = {"User-Agent": "rock-mech-literature-search/1.0 (mailto:research@example.com)",
           "Accept": "application/json"}

# ---- 评分权重（模块级常量，便于调参）----
W_TITLE_HIT, TITLE_CAP = 8, 24      # 相关性：标题命中
W_ABSTRACT_HIT, ABSTRACT_CAP = 3, 9  # 相关性：摘要命中
W_CITATION = 30                       # 被引（年均，log10）
TIER_SCORE = {"A": 15, "B": 12, "C": 12, "D": 12, "E": 10, "F": 10, "H": 10, "G": 8}
TIER_OUTSIDE = 4                      # 白名单外期刊/预印本
W_RECENCY = 10                        # 新近度
W_OA = 5                              # 开放获取加分
RAW_MAX = TITLE_CAP + ABSTRACT_CAP + W_CITATION + 15 + W_RECENCY + W_OA  # 93

DEFAULT_EXCLUDE = (r"editorial|commentary|corrigendum|erratum|retraction|book review|"
                   r"obituary|news and views|front matter|back matter|预印本说明")
STOPWORDS = {"the", "a", "an", "of", "in", "on", "at", "to", "for", "and", "or",
             "is", "are", "with", "by", "from", "using", "via", "its", "基于", "研究"}


# ---------- 通用工具 ----------

def norm_text(s: str) -> str:
    """小写并去掉非字母数字（保留 CJK），用于期刊名模糊匹配。"""
    return re.sub(r"[\W_]+", "", (s or "").lower())


def journal_matches(venue: str) -> str | None:
    """venue 是否在 26 刊白名单内，返回缩写；不匹配返回 None。

    兼容全称/中文名/常见缩写（如 Rock Mech Rock Eng）三种形式。
    """
    v = norm_text(venue)
    if not v:
        return None
    for abbr, info in JOURNALS.items():
        for cand in (info["name"], abbr):
            n = norm_text(cand)
            if not n:
                continue
            if v == n or (len(v) >= 10 and (v in n or n in v)):
                return abbr
        # 缩写形式：期刊名各英文单词首字母
        initials = "".join(w[0] for w in re.findall(r"[a-z]+", info["name"].lower()))
        if v == initials and len(initials) >= 4:
            return abbr
    return None


def http_get_json(url: str, headers: dict | None = None,
                  waits: tuple[int, ...] = (2, 4, 8, 15, 30)) -> dict:
    """GET + JSON，429 指数退避重试。重试耗尽抛 RuntimeError（由调用方标记该库失败）。"""
    req = urllib.request.Request(url, headers=headers or HEADERS)
    rate_limited = False
    for wait in waits:
        time.sleep(random.uniform(0.8, 2.5))  # polite random delay before each request
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                rate_limited = True
                sys.stderr.write(f"  rate limited, waiting {wait}s...\n")
                time.sleep(wait)
                continue
            raise
        except Exception:
            time.sleep(1)
            continue
    if rate_limited:
        raise RuntimeError("rate limited (429)")
    raise RuntimeError("request failed after retries")


def parse_year_range(year_range: str | None) -> tuple[int, int] | None:
    if not year_range:
        return None
    parts = year_range.split("-")
    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
        return int(parts[0]), int(parts[1])
    return None


def strip_xml_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text or "").strip()


# ---------- 各数据源检索 ----------

def search_openalex(query: str, year_range: str | None, limit: int,
                    sids: list[str] | None, sort: str) -> list[dict]:
    """OpenAlex 检索。sids=None 表示不限期刊（--all-journals）。"""
    sort_map = {"relevance": "relevance_score:desc", "citations": "cited_by_count:desc",
                "date": "publication_date:desc"}
    filters = ["type:article"]
    if sids:
        filters.insert(0, f"primary_location.source.id:{'|'.join(sids)}")
    yr = parse_year_range(year_range)
    if yr:
        filters.append(f"publication_year:{yr[0]}-{yr[1]}")
    papers, page, per_page = [], 1, min(50, limit)
    while len(papers) < limit:
        params = {"search": query, "per_page": per_page, "page": page,
                  "filter": ",".join(filters), "sort": sort_map.get(sort, sort_map["relevance"])}
        url = f"https://api.openalex.org/works?{urllib.parse.urlencode(params)}"
        try:
            resp = openalex_request(url)
        except Exception as e:
            sys.stderr.write(f"  [openalex] page {page} failed: {e}\n")
            break
        results = resp.get("results", [])
        if not results:
            break
        sid_to_abbr = {info["sid"]: k for k, info in JOURNALS.items()}
        for work in results:
            if len(papers) >= limit:
                break
            p = parse_openalex(work, sid_to_abbr)
            if p:
                papers.append(p)
        if page * per_page >= resp.get("meta", {}).get("count", 0):
            break
        page += 1
        time.sleep(0.2)
    return papers


def parse_openalex(work: dict, sid_to_abbr: dict) -> dict | None:
    if not work or not work.get("title"):
        return None
    authors = [a.get("author", {}).get("display_name", "")
               for a in work.get("authorships", []) if a.get("author", {}).get("display_name")]
    primary = work.get("primary_location", {}) or {}
    source = primary.get("source", {}) or {}
    venue = source.get("display_name", "")
    sid = (source.get("id") or "").rsplit("/", 1)[-1]
    doi = work.get("doi", "") or ""
    if doi.startswith("https://doi.org/"):
        doi = doi[16:]
    abstract = ""
    inv = work.get("abstract_inverted_index", {})
    if inv:
        wp = sorted((pos, w) for w, ps in inv.items() for pos in ps)
        abstract = " ".join(w for _, w in wp)
    return {
        "title": work["title"],
        "authors": authors,
        "year": work.get("publication_year"),
        "journal": venue,
        "venue": venue,
        "journal_abbr": sid_to_abbr.get(sid, ""),
        "citations": work.get("cited_by_count", 0) or 0,
        "citationCount": work.get("cited_by_count", 0) or 0,
        "doi": doi,
        "abstract": abstract[:2000],
        "publication_date": work.get("publication_date", ""),
        "openalex_id": work.get("id", ""),
        "pdf_url": (work.get("open_access", {}) or {}).get("oa_url", "") or "",
        "type": work.get("type", ""),
        "source": "openalex",
    }


def search_crossref(query: str, year_range: str | None, limit: int, sort: str) -> list[dict]:
    sort_map = {"relevance": "score", "citations": "is-referenced-by-count", "date": "published"}
    params = {
        "query": query,
        "rows": min(limit, 100),
        "select": "DOI,title,author,container-title,issued,is-referenced-by-count,abstract,URL,type",
        "sort": sort_map.get(sort, "score"),
        "filter": "type:journal-article",
    }
    yr = parse_year_range(year_range)
    if yr:
        params["filter"] += f",from-pub-date:{yr[0]}-01-01,until-pub-date:{yr[1]}-12-31"
    url = f"{CROSSREF_API}?{urllib.parse.urlencode(params)}"
    resp = http_get_json(url)
    papers = []
    for item in resp.get("message", {}).get("items", []):
        title = (item.get("title") or [""])[0]
        if not title:
            continue
        authors = []
        for a in item.get("author", []) or []:
            name = " ".join(x for x in [a.get("given", ""), a.get("family", "")] if x)
            if name:
                authors.append(name)
        year = None
        for key in ("published-print", "published-online", "issued", "created"):
            parts = (item.get(key) or {}).get("date-parts", [[]])
            if parts and parts[0] and parts[0][0]:
                year = parts[0][0]
                break
        papers.append({
            "title": title,
            "authors": authors,
            "year": year,
            "journal": (item.get("container-title") or [""])[0],
            "venue": (item.get("container-title") or [""])[0],
            "journal_abbr": "",
            "citations": item.get("is-referenced-by-count", 0) or 0,
            "citationCount": item.get("is-referenced-by-count", 0) or 0,
            "doi": item.get("DOI", "") or "",
            "abstract": strip_xml_tags(item.get("abstract", ""))[:2000],
            "publication_date": "",
            "pdf_url": "",
            "type": "journal-article",
            "source": "crossref",
        })
    return papers


def search_s2(query: str, year_range: str | None, limit: int,
              sort: str, api_key: str | None) -> list[dict]:
    fields = "title,authors,abstract,year,venue,citationCount,externalIds,publicationDate,openAccessPdf"
    params = {"query": query, "fields": fields, "limit": min(limit, 100)}
    yr = parse_year_range(year_range)
    if yr:
        params["year"] = f"{yr[0]}-{yr[1]}"
    url = f"{S2_API}/paper/search?{urllib.parse.urlencode(params)}"
    headers = dict(HEADERS)
    if api_key:
        headers["x-api-key"] = api_key
    s2_throttle()  # 全局 S2 限速，防止短时大量请求被封
    resp = http_get_json(url, headers)
    papers = []
    for d in resp.get("data", []) or []:
        if not d.get("title"):
            continue
        papers.append({
            "title": d["title"],
            "authors": [a.get("name", "") for a in d.get("authors", []) or [] if a.get("name")],
            "year": d.get("year"),
            "journal": d.get("venue", "") or "",
            "venue": d.get("venue", "") or "",
            "journal_abbr": "",
            "citations": d.get("citationCount", 0) or 0,
            "citationCount": d.get("citationCount", 0) or 0,
            "doi": (d.get("externalIds") or {}).get("DOI", "") or "",
            "abstract": (d.get("abstract") or "")[:2000],
            "publication_date": d.get("publicationDate", "") or "",
            "pdf_url": ((d.get("openAccessPdf") or {}).get("url", "") or ""),
            "type": "article",
            "source": "s2",
        })
    return papers


def search_arxiv(query: str, year_range: str | None, limit: int) -> list[dict]:
    yr = parse_year_range(year_range)
    params = {"search_query": f"all:{query}", "start": 0, "max_results": min(limit, 50),
              "sortBy": "relevance"}
    url = f"{ARXIV_API}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": HEADERS["User-Agent"]})
    for attempt in range(3):
        time.sleep(random.uniform(0.8, 2.5))  # polite random delay before each request
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                xml_text = resp.read().decode("utf-8")
            break
        except Exception:
            if attempt < 2:
                time.sleep(2)
                continue
            sys.stderr.write("  [arxiv] request failed\n")
            return []
    ns = {"a": "http://www.w3.org/2005/Atom", "ar": "http://arxiv.org/schemas/atom"}
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return []
    papers = []
    for e in root.findall("a:entry", ns):
        title = re.sub(r"\s+", " ", (e.findtext("a:title", "", ns) or "")).strip()
        if not title:
            continue
        published = e.findtext("a:published", "", ns) or ""
        year = int(published[:4]) if published[:4].isdigit() else None
        if yr and year and not (yr[0] <= year <= yr[1]):
            continue
        arxiv_id = (e.findtext("a:id", "", ns) or "").rsplit("/", 1)[-1]
        doi = e.findtext("ar:doi", "", ns) or (f"10.48550/arXiv.{arxiv_id}" if arxiv_id else "")
        papers.append({
            "title": title,
            "authors": [a.findtext("a:name", "", ns) for a in e.findall("a:author", ns)],
            "year": year,
            "journal": "arXiv (预印本)",
            "venue": "arXiv",
            "journal_abbr": "",
            "citations": 0,
            "citationCount": 0,
            "doi": doi,
            "abstract": re.sub(r"\s+", " ", e.findtext("a:summary", "", ns) or "").strip()[:2000],
            "publication_date": published[:10],
            "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}" if arxiv_id else "",
            "type": "preprint",
            "source": "arxiv",
        })
    return papers


# ---------- 合并去重 ----------

def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def merge_records(a: dict, b: dict) -> dict:
    """两条重复记录合并：字段取先到非空，被引取最大，来源库取并集。"""
    for k in ("doi", "abstract", "pdf_url", "publication_date", "journal_abbr", "openalex_id"):
        if not a.get(k) and b.get(k):
            a[k] = b[k]
    a["citations"] = max(a.get("citations") or 0, b.get("citations") or 0)
    a["citationCount"] = a["citations"]
    for k in ("title", "journal"):
        if not a.get(k) and b.get(k):
            a[k] = b[k]
    if len(b.get("authors", [])) > len(a.get("authors", [])):
        a["authors"] = b["authors"]
    if b["source"] not in a.setdefault("sources", [a.get("source", "")]):
        a["sources"].append(b["source"])
    return a


def dedupe(records: list[dict]) -> list[dict]:
    """DOI 优先 → 标题精确（规范化）→ 标题 Jaccard>=0.8。"""
    by_doi, by_title = {}, {}
    unique = []
    for rec in records:
        doi = (rec.get("doi") or "").lower()
        title_key = norm_text(rec.get("title", ""))
        hit = None
        if doi and doi in by_doi:
            hit = by_doi[doi]
        elif title_key and title_key in by_title:
            hit = by_title[title_key]
        else:
            tokens = set(re.findall(r"[a-z0-9]+", (rec.get("title") or "").lower()))
            for prev in unique:
                if jaccard(tokens, set(re.findall(r"[a-z0-9]+", (prev.get("title") or "").lower()))) >= 0.8:
                    hit = prev
                    break
        if hit is not None:
            merge_records(hit, rec)
        else:
            rec["sources"] = [rec["source"]]
            unique.append(rec)
            if doi:
                by_doi[doi] = rec
            if title_key:
                by_title[title_key] = rec
    return unique


# ---------- 组合评分 ----------

def score_paper(p: dict, include_terms: list[str], exclude_re: str) -> dict:
    title = (p.get("title") or "").lower()
    abstract = (p.get("abstract") or "").lower()
    # 排除项（仅标题匹配，避免摘要提及误伤）
    excluded_reason = ""
    if exclude_re and re.search(exclude_re, title, re.I):
        excluded_reason = "非研究论文（社论/勘误/书评等）"
    # 相关性
    title_hits = sum(1 for t in include_terms if t and t.lower() in title)
    abstract_hits = sum(1 for t in include_terms if t and t.lower() in abstract)
    relevance = min(title_hits * W_TITLE_HIT, TITLE_CAP) + min(abstract_hits * W_ABSTRACT_HIT, ABSTRACT_CAP)
    # 被引（年均，log10 缓冲）
    this_year = date.today().year
    year = p.get("year") or this_year
    cpy = (p.get("citations") or 0) / max(1, this_year - year + 1)
    citation_score = min(W_CITATION, 10 * math.log10(1 + cpy)) if cpy > 0 else 0
    # 期刊层次
    abbr = p.get("journal_abbr") or journal_matches(p.get("journal", ""))
    if abbr:
        p["journal_abbr"] = abbr
        tier = TIER_SCORE[JOURNALS[abbr]["cat"]]
    else:
        tier = TIER_OUTSIDE
    # 新近度
    age = this_year - (year if isinstance(year, int) else this_year)
    recency = 10 if age <= 2 else (8 if age <= 5 else (5 if age <= 10 else 2))
    # OA
    oa = W_OA if p.get("pdf_url") else 0

    raw = relevance + citation_score + tier + recency + oa
    p["cpy"] = round(cpy, 1)
    p["score_breakdown"] = {
        "relevance": relevance, "citations": round(citation_score, 1),
        "journal_tier": tier, "recency": recency, "open_access": oa,
    }
    p["score"] = 0 if excluded_reason else round(raw / RAW_MAX * 100, 1)
    p["relevance_hits"] = {"title": title_hits, "abstract": abstract_hits}
    p["excluded_reason"] = excluded_reason
    return p


# ---------- 输出 ----------

CSV_FIELDS = ["序号", "综合评分", "标题", "作者", "年份", "期刊", "期刊类别", "被引", "年均被引",
              "相关性分", "被引分", "期刊分", "新近分", "OA分", "数据库来源", "DOI", "PDF链接",
              "发表日期", "排除原因", "摘要"]


def to_csv(papers: list[dict]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CSV_FIELDS)
    for i, p in enumerate(papers, 1):
        authors = ", ".join(p.get("authors", [])[:3]) + (" et al." if len(p.get("authors", [])) > 3 else "")
        bd = p["score_breakdown"]
        writer.writerow([
            i, p["score"], p.get("title", ""), authors, p.get("year") or "",
            p.get("journal", "") or "", p.get("journal_abbr", "") or "白名单外",
            p.get("citations", 0), p.get("cpy", 0),
            bd["relevance"], bd["citations"], bd["journal_tier"], bd["recency"], bd["open_access"],
            "+".join(p.get("sources", [])), p.get("doi", "") or "",
            p.get("pdf_url", "") or "", p.get("publication_date", "") or "",
            p.get("excluded_reason", "") or "", (p.get("abstract", "") or "")[:500],
        ])
    return buf.getvalue()


def to_high_quality_json(papers: list[dict], args, high: list[dict]) -> str:
    payload = {
        "query": args.query,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "sources": args.sources.split(","),
        "year_range": args.year_range or "不限",
        "journals": "全部 26 核心刊" if not (args.journals or args.category or args.all_journals)
                    else ("不限期刊" if args.all_journals else f"{args.journals or args.category}"),
        "scoring": "相关性(0-33)+被引(0-30)+期刊层次(0-15)+新近度(0-10)+开放获取(0-5)，归一化 0-100",
        "total_candidates": len(papers),
        "high_quality_count": len(high),
        "papers": [{
            "rank": i,
            "title": p.get("title", ""),
            "authors": p.get("authors", []),
            "year": p.get("year"),
            "journal": p.get("journal", ""),
            "journal_abbr": p.get("journal_abbr", ""),
            "doi": p.get("doi", ""),
            "citations": p.get("citations", 0),
            "citations_per_year": p.get("cpy", 0),
            "score": p["score"],
            "score_breakdown": p["score_breakdown"],
            "relevance_hits": p["relevance_hits"],
            "pdf_url": p.get("pdf_url", ""),
            "publication_date": p.get("publication_date", ""),
            "abstract": p.get("abstract", ""),
            "databases": p.get("sources", []),
        } for i, p in enumerate(high, 1)],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def main():
    ap = argparse.ArgumentParser(description="多库聚合检索：OpenAlex+Crossref+S2(可选arXiv)，CSV+JSON 输出")
    ap.add_argument("--query", required=True, help="检索关键词（建议英文，中文需配 --include-terms）")
    ap.add_argument("--sources", default="openalex,crossref,s2",
                    help="数据源，逗号分隔：openalex,crossref,s2,arxiv（默认前三者）")
    ap.add_argument("--journals", help="限定期刊缩写（如 RMRE,IJRMMS），默认全 26 刊")
    ap.add_argument("--category", help="限定期刊类别（A核心 B岩土 C地质 D隧道 E断裂 F能源 G三岩 H中文）")
    ap.add_argument("--all-journals", action="store_true", help="不限 26 刊白名单（开放检索）")
    ap.add_argument("--year-range", help="年份范围，如 2015-2026")
    ap.add_argument("--max-results", type=int, default=30, help="每个数据源取回上限（默认 30）")
    ap.add_argument("--sort", choices=["relevance", "citations", "date"], default="relevance",
                    help="各库取数排序（最终排序始终按综合评分）")
    ap.add_argument("--include-terms", help="相关性判定词，逗号分隔（默认取检索词分词）")
    ap.add_argument("--exclude-terms", default=DEFAULT_EXCLUDE, help="排除词表（正则，标题匹配）")
    ap.add_argument("--top", type=int, default=20, help="高质量 JSON 收录篇数上限")
    ap.add_argument("--min-score", type=float, default=40, help="高质量 JSON 评分门槛（0-100，默认 40）")
    ap.add_argument("--s2-api-key", default=s2_api_key(),
                    help="Semantic Scholar API Key（默认自动从 .env 读取）")
    ap.add_argument("--s2-rate", type=float, default=None,
                    help="S2 请求速率（每秒请求数），默认 0.55，防高频请求被封")
    ap.add_argument("-o", "--output", help="输出前缀：生成 前缀_检索结果总表.csv / 前缀_高质量论文.json / 前缀_合并去重.jsonl")
    args = ap.parse_args()

    if args.s2_rate is not None:
        s2_set_rate(args.s2_rate)

    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    # 白名单模式：OpenAlex 用 source id 硬过滤；其他库取回后按期刊名匹配
    selected = [] if args.all_journals else resolve_selection(args.journals, args.category)
    sids = [JOURNALS[k]["sid"] for k in selected] if selected else None

    if args.include_terms:
        include_terms = [t.strip() for t in args.include_terms.split(",") if t.strip()]
    else:
        include_terms = [t for t in re.split(r"[\s,;]+", args.query) if t and t.lower() not in STOPWORDS]

    records = []
    source_status: dict[str, str] = {}
    for src in sources:
        sys.stderr.write(f"[{src}] searching...\n")
        before = len(records)
        try:
            if src == "openalex":
                records.extend(search_openalex(args.query, args.year_range, args.max_results,
                                                sids if selected else None, args.sort))
            elif src == "crossref":
                records.extend(search_crossref(args.query, args.year_range, args.max_results, args.sort))
            elif src == "s2":
                # S2 无 Key 限流严格，退避短一些避免整轮检索被拖太久
                records.extend(search_s2(args.query, args.year_range, args.max_results,
                                         args.sort, args.s2_api_key))
            elif src == "arxiv":
                records.extend(search_arxiv(args.query, args.year_range, args.max_results))
            else:
                sys.stderr.write(f"  unknown source '{src}', skipped\n")
                source_status[src] = "unknown source"
                continue
            got = len(records) - before
            source_status[src] = f"ok ({got} 条)"
        except RuntimeError as e:
            source_status[src] = f"失败（{e}）"
            sys.stderr.write(f"  [{src}] FAILED: {e}，跳过该库继续\n")
        except Exception as e:
            source_status[src] = f"失败（{e}）"
            sys.stderr.write(f"  [{src}] failed (skipped): {e}\n")
        time.sleep(1)

    failed = {k: v for k, v in source_status.items() if not v.startswith("ok")}
    if failed:
        sys.stderr.write(f"⚠ 有数据库未取回数据：{failed}（结果仅基于其余数据库，可稍后重试补全）\n")

    # 去重 → 白名单过滤（crossref/s2/arxiv 取回后过滤）→ 评分
    merged = dedupe(records)
    if selected:  # 白名单模式：丢弃不匹配的期刊（arXiv 显式指定时豁免）
        keep_arxiv = "arxiv" in sources
        merged = [p for p in merged
                  if (keep_arxiv and p["source"] == "arxiv")
                  or (p.get("journal_abbr") or journal_matches(p.get("journal", "")))]
    scored = [score_paper(p, include_terms, args.exclude_terms) for p in merged]
    # 排序：综合评分 → 年均被引 → 被引；被排除的沉底
    scored.sort(key=lambda x: (not x["excluded_reason"], -x["score"], -x.get("cpy", 0), -(x.get("citations") or 0)))
    high = [p for p in scored if not p["excluded_reason"] and p["score"] >= args.min_score][:args.top]

    n_by_src = {}
    for p in merged:
        for s in p.get("sources", []):
            n_by_src[s] = n_by_src.get(s, 0) + 1
    sys.stderr.write(
        f"\n汇总：原始 {len(records)} 条 → 去重 {len(merged)} 条（各库命中 {n_by_src}）"
        f" → 高质量 {len(high)} 篇（评分≥{args.min_score}，前 {args.top}）\n"
        f"相关性判定词：{include_terms}\n")

    if not args.output:
        for p in scored[:20]:
            sys.stderr.write(f"  {p['score']:>5.1f} | {(p.get('year') or '----')} | "
                             f"{(p.get('journal_abbr') or '---')[:8]:8} | {(p.get('title') or '')[:70]}\n")
        sys.stderr.write("\n（未指定 -o，仅打印预览。用 -o PREFIX 生成 CSV/JSON/JSONL 三件套）\n")
        return

    prefix = args.output
    csv_path = f"{prefix}_检索结果总表.csv"
    json_path = f"{prefix}_高质量论文.json"
    jsonl_path = f"{prefix}_合并去重.jsonl"
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        f.write(to_csv(scored))
    with open(json_path, "w", encoding="utf-8") as f:
        f.write(to_high_quality_json(scored, args, high))
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for p in scored:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    print(f"CSV 总表（{len(scored)} 条）: {csv_path}")
    print(f"JSON 高质量论文（{len(high)} 篇）: {json_path}")
    print(f"JSONL 合并去重（{len(scored)} 条）: {jsonl_path}")


if __name__ == "__main__":
    main()
