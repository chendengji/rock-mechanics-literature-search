#!/usr/bin/env python3
"""
显式多轮迭代检索：每轮 3 组并行 → 相关性评价/缺口分析 → 补词/优化 → 下一轮
最少 3 轮，质量收敛才停。

用法示例:
    python iterative_search.py \
        --topic "methods to inject water into hard rock (granite/sandstone) for rockburst prevention" \
        --side-a "water injection|imbibition|saturat|wetting|water content|moisture|aqueous" \
        --side-b "electroosmosis|electrokinetic|microwave|ultrasonic|pulsed|plasma|electrohydraulic|electromagnetic|waterjet" \
        --year-range 2000-2026 --per-query 50 --min-rounds 3 -o C:/Users/QZ/Documents/paper/lit_water_injection_rock_20260828/result

每轮产物:
  {prefix}_round{N}.jsonl / .csv / _queries.txt
最终汇总:
  {prefix}.csv / .jsonl / _中间层/
"""

import argparse
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import lit_common as lc
import lit_paths
from search_rock_journals import JOURNALS, build_tier_map, resolve_selection, search


# ---------- 默认词表 ----------
DEFAULT_SIDE_A = (r"water injection|water infusion|imbibition|saturat|wetting|wett|water content|moisture|water transport|water flow|aqueous")
DEFAULT_SIDE_B = (r"electroosmosis|electrokinetic|microwave|ultrasonic|ultrasound|pulsed (discharge|power|electric)|electrohydraulic|electromagnetic|electropulse|plasma|waterjet|hydrojet|laser|radio frequency")
DEFAULT_EXCLUDE = (r"water (conveyance|diversion|transfer|inrush|level)|hydropower|引水|headrace|penstock|tailrace|powerhouse|seepage|coupled hydro|hydro-mechanical|hydrothermal|water-rock interaction|enhanced oil recovery|oil recovery|carbonate reservoir|petroleum")


def label_relevance(paper: dict, side_a: str, side_b: str, exclude_regex: str) -> str:
    """
    给单篇论文打相关性标签：
    - "core"     : 标题同时命中 side-a 与 side-b（直接切题）
    - "relevant" : 摘要命中双侧、或标题单侧+摘要单侧（可能相关）
    - "method"   : 仅命中 side-b（方法类文献，可能迁移）
    - "water"    : 仅命中 side-a（含水/渗吸类，可能为背景）
    - "noise"    : 命中排除表，或无任何信号
    """
    text = (paper.get("title", "") + " " + paper.get("abstract", "")).lower()
    title = paper.get("title", "").lower()
    # 命中检测
    def hit(regex, txt):
        return re.search(regex, txt, re.I) is not None
    a_title = hit(side_a, title)
    b_title = hit(side_b, title)
    a_abs   = hit(side_a, text)
    b_abs   = hit(side_b, text)
    excl    = hit(exclude_regex, text)

    if excl:
        return "noise"
    if a_title and b_title:
        return "core"
    if (a_title and b_abs) or (b_title and a_abs) or (a_abs and b_abs):
        return "relevant"
    if b_title or b_abs:
        return "method"
    if a_title or a_abs:
        return "water"
    return "noise"


def analyze_round(papers: list[dict], side_a: str, side_b: str, exclude_regex: str,
                  current_queries: list[str]) -> dict:
    """
    对本轮结果做相关性评价与缺口分析，返回：
    {
      "labels": {"core": n, "relevant": n, ...},
      "gap_analysis": "缺少哪方面关键词的文字分析",
      "missing_dims": ["缺维度1", "缺维度2"],
      "new_terms": ["新术语1", "新术语2", ...],
      "bad_queries": ["表现差的查询词"],
      "good_queries": ["表现好的查询词"]
    }
    """
    labels = Counter()
    query_stats = {q: {"core":0, "relevant":0, "total":0} for q in set(p.get("query","") for p in papers)}
    for p in papers:
        lab = label_relevance(p, side_a, side_b, exclude_regex)
        labels[lab] += 1
        q = p.get("query", "")
        if q in query_stats:
            query_stats[q]["total"] += 1
            if lab in ("core", "relevant"):
                query_stats[q][lab] += 1

    # 识别表现好/差的查询
    good_q = [q for q, s in query_stats.items() if s["total"]>0 and (s["core"]+s["relevant"])/s["total"] >= 0.3]
    bad_q  = [q for q, s in query_stats.items() if s["total"]>0 and (s["core"]+s["relevant"])/s["total"] < 0.1]

    # 从 core/relevant 论文的标题/摘要提取新术语（排除已有查询词）
    texts = []
    for p in papers:
        if label_relevance(p, side_a, side_b, exclude_regex) in ("core", "relevant"):
            if p.get("title"): texts.append(p["title"])
            if p.get("abstract"): texts.append(p["abstract"][:500])
    all_text = " ".join(texts).lower()

    existing = set()
    for q in set(p.get("query","") for p in papers):
        existing.update(q.lower().split())
    stop = {"the","a","an","of","in","on","at","to","for","and","or","is","are","with","by","from","using","via","its",
            "基于","研究","method","study","analysis","effect","experimental","numerical","using","based","via"}
    words = re.findall(r"[a-z\u4e00-\u9fff]{3,}", " ".join(texts))
    ngrams = []
    for i in range(len(words)):
        ngrams.append(words[i])
        if i+1 < len(words): ngrams.append(f"{words[i]} {words[i+1]}")
        if i+2 < len(words): ngrams.append(f"{words[i]} {words[i+1]} {words[i+2]}")
    freq = Counter(ng for ng in ngrams if ng not in stop and ng not in existing and not any(c.isdigit() for c in ng))

    # 优先包含 side-a/b 关键字的术语
    def score(t):
        s = freq[t] * 10
        for k in side_a.lower().split("|"):
            if k and k in t: s += 50
        for k in side_b.lower().split("|"):
            if k and k in t: s += 50
        return s
    new_terms = sorted(freq.keys(), key=score, reverse=True)[:12]

    # 缺口分析文本
    core_n = labels.get("core", 0)
    rel_n  = labels.get("relevant", 0)
    meth_n = labels.get("method", 0)
    water_n = labels.get("water", 0)
    noise_n = labels.get("noise", 0)
    total = sum(labels.values())
    gap = []
    if core_n + rel_n == 0:
        gap.append("本轮无直接切题文献，需大幅扩展 side-a × side-b 组合或换词")
    elif core_n < 3:
        gap.append("直接切题文献较少，需强化 side-a × side-b 显式组合查询")
    if meth_n > core_n + rel_n:
        gap.append("仅命中方法侧文献较多，需补 side-a 关键词（注水/渗吸/饱和）以拉回应用场景")
    if water_n > core_n + rel_n:
        gap.append("仅命中含水/渗吸背景文献较多，需补 side-b 方法关键词以聚焦技术手段")
    if noise_n > total * 0.3:
        gap.append("噪声较高，建议补充排除词或用引号词组精确查询")

    # 表现差的查询词分析
    bad_reasons = []
    for q in bad_q:
        if "waterjet" in q.lower() or "hydrojet" in q.lower():
            bad_reasons.append(f"'{q}' 多落在切割/钻进而非注水饱和，考虑改为 'water injection' 或补 side-a")
        if "microwave" in q.lower() and "imbibition" not in q.lower():
            bad_reasons.append(f"'{q}' 多落在微波致裂，缺 'imbibition'/'water' 限定，建议加 'water imbibition'")
        if "ultrasonic" in q.lower() and "water" not in q.lower():
            bad_reasons.append(f"'{q}' 多落在超声检测/监测，缺 'water imbibition/saturation' 限定")
    gap.extend(bad_reasons)

    return {
        "labels": dict(labels),
        "gap_analysis": "; ".join(gap) if gap else "本轮覆盖较均衡，core+relevant 占比尚可",
        "missing_dims": ["side-a×side-b 显式组合不足" if core_n < 3 else "",
                         "side-a 关键词不足" if meth_n > core_n+rel_n else "",
                         "side-b 关键词不足" if water_n > core_n+rel_n else ""],
        "new_terms": new_terms,
        "good_queries": good_q,
        "bad_queries": bad_q
    }


def build_next_queries(current_queries: list[str], analysis: dict,
                       side_a: str, side_b: str, n_groups: int = 3) -> list[str]:
    """基于缺口分析与新术语生成下一轮 3 组查询词"""
    keep = [q for q in current_queries if q in analysis.get("good_queries", [])][:2]
    new_terms = analysis.get("new_terms", [])[:8]
    gap = analysis.get("missing_dims", [])

    new_qs = []
    a_terms = [t for t in side_a.split("|") if t][:3]
    b_terms = [t for t in side_b.split("|") if t][:4]

    # 针对缺口补词
    if any("side-a×side-b" in d for d in gap):
        for a in a_terms[:2]:
            for b in b_terms[:2]:
                new_qs.append(f"{a} {b}")
    if any("side-a" in d for d in gap):
        for a in a_terms[:2]:
            new_qs.append(f"{a} rock")
            new_qs.append(f"{a} granite")
    if any("side-b" in d for d in gap):
        for b in b_terms[:2]:
            new_qs.append(f"{b} water")
            new_qs.append(f"{b} rock water")

    # 新术语与 side-a/b 交叉
    for term in new_terms[:6]:
        for a in a_terms[:2]:
            new_qs.append(f"{a} {term}")
        for b in b_terms[:2]:
            new_qs.append(f"{term} {b}")
        new_qs.append(term)

    # 合并去重
    all_qs = keep + new_qs
    seen = set()
    uniq = []
    for q in all_qs:
        q_clean = q.strip()
        if q_clean and q_clean not in seen:
            seen.add(q_clean)
            uniq.append(q_clean)
    return uniq[:max(3, 3)]


def run_round(queries: list[str], sids: list[str] | None, sid_to_abbr: dict,
              max_results: int, year_range: str | None,
              min_citations: int, sort: str, scope: str = "all") -> list[dict]:
    all_hits = []
    for q in queries:
        sys.stderr.write(f"  polling: {q}\n")
        papers = search(q, sids, sid_to_abbr, max_results, year_range, 0, "relevance_score:desc", scope=scope)
        for p in papers:
            p["query"] = q
        all_hits.extend(papers)
    return all_hits


def save_round(prefix: str, round_num: int, queries: list[str], papers: list[dict]):
    Path(f"{prefix}_round{round_num}.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in papers), encoding="utf-8")
    Path(f"{prefix}_round{round_num}_queries.txt").write_text(
        "\n".join(queries), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="显式多轮迭代检索：每轮3组→相关性评价/缺口分析→优化词表→下一轮，最少3轮")
    ap.add_argument("--topic", required=True, help="研究主题描述（用于相关性判断与词表生成）")
    ap.add_argument("--side-a", default=DEFAULT_SIDE_A, help="主题A词表（正则）")
    ap.add_argument("--side-b", default=DEFAULT_SIDE_B, help="主题B词表（正则）")
    ap.add_argument("--exclude", default=DEFAULT_EXCLUDE, help="假阳性排除词表（正则）")
    ap.add_argument("--year-range", help="年份范围，如 2000-2026")
    ap.add_argument("--per-query", type=int, default=50, help="每组检索词取回上限")
    ap.add_argument("--min-rounds", type=int, default=3, help="最少迭代轮数（默认 3）")
    ap.add_argument("--max-rounds", type=int, default=6, help="最多迭代轮数（默认 6）")
    ap.add_argument("--scope", choices=["all", "whitelist"], default="all")
    ap.add_argument("--journals", help="期刊缩写列表")
    ap.add_argument("--category", help="期刊类别")
    ap.add_argument("--min-final", type=int, default=20)
    ap.add_argument("--min-signal", choices=["s", "a", "T"], default="s")
    ap.add_argument("--output", "-o", help="输出文件前缀（不含后缀）；给了 --task 时可省，默认写到 <task>/02_intermediate/{topic}")
    ap.add_argument("--task", help="任务根目录（标准布局，见 scripts/lit_paths.py）；自动分流："
                                    "各轮原始命中→01_sources/，分析→04_reports/，最终前缀→02_intermediate/")
    ap.add_argument("--min-score", type=float, default=0.0)
    args = ap.parse_args()

    # 标准布局分流：--task 存在时，-o 只需给文件名，其余按类别落位
    task_root = None
    if args.task:
        task_root = lit_paths.init_task(args.task, args.topic)
        if not args.output:
            args.output = str(lit_paths.p(task_root, "02_intermediate", "result"))
        elif not Path(args.output).is_absolute():
            args.output = str(lit_paths.p(task_root, "02_intermediate", args.output))
        out_path = Path(args.output)
        sources_dir = str(lit_paths.p(task_root, "01_sources"))
        reports_dir = str(lit_paths.p(task_root, "04_reports"))
        args.output = str(out_path)
    else:
        sources_dir = reports_dir = None

    from search_rock_journals import JOURNALS, build_tier_map, resolve_selection
    from lit_common import dedupe_papers, write_candidates_csv

    # 期刊选择
    if args.journals or args.category:
        if args.scope == "all":
            sys.stderr.write("Note: --journals/--category given -> switching to whitelist strict mode\n")
        args.scope = "whitelist"
        selected = resolve_selection(args.journals, args.category)
    else:
        selected = list(JOURNALS.keys())
    if not selected:
        print("Error: no valid journals selected", file=sys.stderr)
        sys.exit(1)
    selected_sids = [JOURNALS[k]["sid"] for k in selected]
    sid_to_abbr = {JOURNALS[k]["sid"]: k for k in selected}
    scope_desc = ("ALL OpenAlex (whitelist as bonus)" if args.scope == "all"
                  else f"{len(selected_sids)} whitelist journals")
    sys.stderr.write(f"Scope: {scope_desc}\n")

    # 初始 3 组查询词（基于 side-a × side-b 简单组合 + topic）
    def build_initial_queries():
        a_terms = [t.strip() for t in args.side_a.split("|") if t.strip()][:4]
        b_terms = [t.strip() for t in args.side_b.split("|") if t.strip()][:5]
        qs = []
        for a in a_terms[:2]:
            for b in b_terms[:2]:
                qs.append(f"{a} {b}")
        if args.topic:
            qs.append(args.topic)
        seen = set()
        uniq = []
        for q in qs:
            if q not in seen:
                seen.add(q)
                uniq.append(q)
        return uniq[:3]

    current_queries = build_initial_queries()
    all_deduped = []
    round_num = 0

    for round_num in range(1, args.max_rounds + 1):
        sys.stderr.write(f"\n=== Round {round_num} ===\n")
        sys.stderr.write(f"Queries ({len(current_queries)}): {current_queries}\n")

        # 实际 sid 列表
        if args.scope == "whitelist":
            sid_list = selected_sids
        else:
            sid_list = None

        # 跑本轮
        hits = run_round(current_queries, sid_list, sid_to_abbr, args.per_query, args.year_range, 0, "relevance_score:desc", args.scope)

        # 去重
        deduped = lc.dedupe_papers(hits)
        sys.stderr.write(f"  fetched={len(hits)} -> deduped={len(deduped)}\n")

        # 保存本轮（--task 时原始命中进 01_sources/，检索词也留档）
        Path(sources_dir or "", f"{Path(args.output).name}_round{round_num}.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in deduped), encoding="utf-8")
        Path(sources_dir or "", f"{Path(args.output).name}_round{round_num}_queries.txt").write_text(
            "\n".join(current_queries), encoding="utf-8")

        # 相关性评价 + 缺口分析
        analysis = analyze_round(deduped, args.side_a, args.side_b, args.exclude, current_queries)
        sys.stderr.write(f"  Labels: {analysis['labels']}\n")
        sys.stderr.write(f"  Gap: {analysis['gap_analysis']}\n")
        sys.stderr.write(f"  New terms: {analysis['new_terms'][:8]}\n")
        sys.stderr.write(f"  Good queries: {analysis.get('good_queries',[])}\n")
        sys.stderr.write(f"  Bad queries: {analysis.get('bad_queries',[])}\n")

        # 保存分析（--task 时进 04_reports/）
        Path(reports_dir or "", f"{Path(args.output).name}_round{round_num}_analysis.json").write_text(
            json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")

        # 收敛判断
        if round_num >= args.min_rounds:
            # 简单收敛判断：core+relevant 新增 < 3 且已达最小轮数
            core_rel = sum(1 for p in deduped if label_relevance(p, args.side_a, args.side_b, args.exclude) in ("core","relevant"))
            if core_rel < 3 and round_num >= args.min_rounds:
                sys.stderr.write(f"  Converged: only {core_rel} core+relevant new papers.\n")
                break

        # 生成下一轮查询词
        current_queries = build_next_queries(current_queries, analysis, args.side_a, args.side_b)

    sys.stderr.write("\n=== All rounds done ===\n")
    # 每轮已分别落盘 {output}_round{N}.jsonl 与 {output}_round{N}_queries.txt；
    # 最终汇总（合并去重 + 漏斗 + 候选表 CSV）由 lit_common 的
    # dedupe_papers / rank_papers / write_candidates_csv 完成。
    Path(sources_dir or "", f"{Path(args.output).name}_all_queries.txt").write_text(
        "\n".join(current_queries), encoding="utf-8")
    if task_root:
        lit_paths.write_manifest(task_root)
    sys.stderr.write(f"\n=== Done {round_num} rounds ===\n")
    sys.stderr.write(f"任务目录: {task_root or Path(args.output).parent}\n")
    sys.stderr.write(f"检索词留档: {Path(sources_dir or '', Path(args.output).name + '_all_queries.txt')}\n")
    sys.stderr.write("单轮 jsonl 已保存，可对 *_round*.jsonl 合并后跑候选表导出\n")


if __name__ == "__main__":
    main()