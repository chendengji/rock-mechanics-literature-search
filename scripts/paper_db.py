#!/usr/bin/env python3
"""JSONL paper database management.

Subcommands: add, search, merge, tag, stats, export.
Dedup rules (borrowed from literature-downloader-skill, priority high→low):
  1. normalized DOI exact match
  2. source ID (arxiv_id / paperId / openalex_id)
  3. normalized-title exact match
  4. title Jaccard similarity fallback (threshold, default 0.8)
Duplicate records are MERGED into the most complete one (never dropped silently).

Usage:
    python paper_db.py merge --inputs arxiv.jsonl s2.jsonl --output merged.jsonl
    python paper_db.py stats --input paper_db.jsonl
    python paper_db.py search --input paper_db.jsonl --query "transformer"
    python paper_db.py tag --input paper_db.jsonl --ids "2401.12345" --tags core method
    python paper_db.py add --input paper_db.jsonl --record '{"title":"...", "arxiv_id":"..."}'
    python paper_db.py export --input paper_db.jsonl --format csv
"""

import argparse
import csv
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lit_common as lc  # noqa: E402


def load_jsonl(path: str) -> list[dict]:
    """Load records from a JSONL file."""
    records = []
    if not os.path.exists(path):
        return records
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def save_jsonl(records: list[dict], path: str):
    """Save records to a JSONL file."""
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def get_paper_id(paper: dict) -> str:
    """Get the canonical ID for a paper."""
    return paper.get("arxiv_id") or paper.get("paperId") or ""


def deduplicate(records: list[dict], threshold: float = 0.85) -> list[dict]:
    """Deduplicate: DOI → source ID → normalized-title exact → Jaccard fallback.

    Duplicates are merged into the first-seen (most complete) record.
    """
    kept: list[dict] = []
    by_doi: dict[str, dict] = {}
    by_pid: dict[str, dict] = {}
    by_ntitle: dict[str, dict] = {}
    token_sets: list[set] = []

    for rec in records:
        doi = lc.normalize_doi(rec.get("doi"))
        pid = lc.source_id(rec) or get_paper_id(rec)
        ntitle = lc.normalize_title(rec.get("title"))

        target = None
        if doi and doi in by_doi:
            target = by_doi[doi]
        elif pid and pid in by_pid:
            target = by_pid[pid]
        elif ntitle and ntitle in by_ntitle:
            target = by_ntitle[ntitle]
        elif ntitle:
            toks = lc.tokenize(ntitle)
            for kept_rec, prev in zip(kept, token_sets):
                if lc.jaccard(toks, prev) >= threshold:
                    target = kept_rec
                    break

        if target is None:
            kept.append(rec)
            if doi:
                by_doi[doi] = rec
            if pid:
                by_pid[pid] = rec
            if ntitle:
                by_ntitle[ntitle] = rec
            token_sets.append(lc.tokenize(ntitle))  # keep indexes aligned
        else:
            lc.merge_records(target, rec)

    return kept


def merge_databases(inputs: list[str], output: str, threshold: float = 0.8):
    """Merge multiple JSONL files with deduplication."""
    all_records = []
    for path in inputs:
        records = load_jsonl(path)
        print(f"Loaded {len(records)} from {path}", file=sys.stderr)
        all_records.extend(records)

    merged = deduplicate(all_records, threshold)
    save_jsonl(merged, output)
    print(f"Merged: {len(all_records)} -> {len(merged)} unique papers -> {output}", file=sys.stderr)


def filter_db(db_path: str, output: str, *, min_score: float = 0.0, max_papers: int = 0,
              require_keywords: list[str] | None = None):
    """Filter papers by affinity_score threshold and optional keyword relevance."""
    records = load_jsonl(db_path)
    kept = []
    for rec in records:
        score = rec.get("affinity_score")
        if score is not None and score < min_score:
            continue
        if score is None and require_keywords:
            title_lower = rec.get("title", "").lower()
            if not any(k in title_lower for k in require_keywords):
                continue
        kept.append(rec)

    # Sort by score descending (None at end)
    kept.sort(key=lambda r: -(r.get("affinity_score") or 0))

    if max_papers > 0 and len(kept) > max_papers:
        kept = kept[:max_papers]

    save_jsonl(kept, output)
    print(f"Filtered: {len(records)} -> {len(kept)} papers -> {output}", file=sys.stderr)


def search_db(db_path: str, query: str, field: str = "title") -> list[dict]:
    """Search papers by keyword match in a field."""
    records = load_jsonl(db_path)
    query_lower = query.lower()
    results = []

    for rec in records:
        value = rec.get(field, "")
        if isinstance(value, list):
            value = " ".join(str(v) for v in value)
        if query_lower in str(value).lower():
            results.append(rec)

    return results


def tag_papers(db_path: str, ids: list[str], tags: list[str]):
    """Add tags to specific papers."""
    records = load_jsonl(db_path)
    tagged = 0

    for rec in records:
        pid = get_paper_id(rec)
        if pid in ids:
            existing = rec.get("tags", [])
            rec["tags"] = sorted(set(existing + tags))
            tagged += 1

    save_jsonl(records, db_path)
    print(f"Tagged {tagged} papers with {tags}", file=sys.stderr)


def compute_stats(db_path: str) -> dict:
    """Compute statistics about the paper database."""
    records = load_jsonl(db_path)
    if not records:
        return {"total": 0}

    sources = {}
    years = {}
    venues = {}
    with_abstract = 0
    with_pdf = 0
    total_citations = 0
    tags_dist = {}
    peer_reviewed_count = 0

    for rec in records:
        src = rec.get("source", "unknown")
        sources[src] = sources.get(src, 0) + 1

        year = rec.get("year")
        if year:
            years[year] = years.get(year, 0) + 1

        venue = rec.get("venue", "")
        if venue:
            venues[venue] = venues.get(venue, 0) + 1

        if rec.get("abstract"):
            with_abstract += 1
        if rec.get("pdf_url") or rec.get("pdf_path"):
            with_pdf += 1
        if rec.get("peer_reviewed"):
            peer_reviewed_count += 1

        total_citations += rec.get("citationCount", 0) or 0

        for tag in rec.get("tags", []):
            tags_dist[tag] = tags_dist.get(tag, 0) + 1

    return {
        "total": len(records),
        "peer_reviewed": peer_reviewed_count,
        "preprint_only": len(records) - peer_reviewed_count,
        "sources": sources,
        "years": dict(sorted(years.items(), key=lambda x: str(x[0]))),
        "top_venues": dict(sorted(venues.items(), key=lambda x: -x[1])[:10]),
        "with_abstract": with_abstract,
        "with_pdf": with_pdf,
        "total_citations": total_citations,
        "avg_citations": round(total_citations / len(records), 1),
        "tags": tags_dist,
    }


def export_csv(db_path: str) -> str:
    """Export paper DB as candidate-table CSV (metrics merged into every row)."""
    records = load_jsonl(db_path)
    if not records:
        return ""

    metrics_db = lc.load_metrics()
    fields = [
        "arxiv_id", "paperId", "openalex_id", "record_id",
        "title", "authors", "year", "venue", "journal_abbr",
        "citationCount", "cpy", "doi", "landing_page_url", "pdf_url",
        "tags", "source",
        # 期刊指标并入每行（缺失显示待核验，不编造）
        "impact_factor", "jcr_quartile", "metric_year", "metric_source", "indexing",
    ]

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for rec in records:
        row = dict(rec)
        if isinstance(row.get("authors"), list):
            row["authors"] = "; ".join(row["authors"])
        if isinstance(row.get("tags"), list):
            row["tags"] = "; ".join(row["tags"])
        row.update(lc.metrics_for(row.get("venue") or row.get("journal"),
                                  row.get("journal_abbr"), metrics_db))
        writer.writerow(row)

    return output.getvalue()


def main():
    parser = argparse.ArgumentParser(description="JSONL paper database management")
    sub = parser.add_subparsers(dest="command", required=True)

    # merge
    p_merge = sub.add_parser("merge", help="Merge multiple JSONL files with deduplication")
    p_merge.add_argument("--inputs", nargs="+", required=True, help="Input JSONL files")
    p_merge.add_argument("--output", required=True, help="Output JSONL file")
    p_merge.add_argument("--threshold", type=float, default=0.8, help="Title similarity threshold (fallback)")

    # search
    p_search = sub.add_parser("search", help="Search papers by keyword")
    p_search.add_argument("--input", required=True, help="Paper DB JSONL file")
    p_search.add_argument("--query", required=True, help="Search query")
    p_search.add_argument("--field", default="title", help="Field to search (default: title)")

    # tag
    p_tag = sub.add_parser("tag", help="Add tags to papers")
    p_tag.add_argument("--input", required=True, help="Paper DB JSONL file")
    p_tag.add_argument("--ids", nargs="+", required=True, help="Paper IDs to tag")
    p_tag.add_argument("--tags", nargs="+", required=True, help="Tags to add")

    # add
    p_add = sub.add_parser("add", help="Add a paper record")
    p_add.add_argument("--input", required=True, help="Paper DB JSONL file")
    p_add.add_argument("--record", required=True, help="JSON string of paper record")

    # stats
    p_stats = sub.add_parser("stats", help="Show database statistics")
    p_stats.add_argument("--input", required=True, help="Paper DB JSONL file")

    # filter
    p_filter = sub.add_parser("filter", help="Filter papers by score/keywords")
    p_filter.add_argument("--input", required=True, help="Paper DB JSONL file")
    p_filter.add_argument("--output", "-o", required=True, help="Output JSONL file")
    p_filter.add_argument("--min-score", type=float, default=0.0, help="Minimum affinity_score threshold")
    p_filter.add_argument("--max-papers", type=int, default=0, help="Maximum number of papers to keep (0=unlimited)")
    p_filter.add_argument("--keywords", nargs="*", help="For papers without score, require these keywords in title")

    # export
    p_export = sub.add_parser("export", help="Export database")
    p_export.add_argument("--input", required=True, help="Paper DB JSONL file")
    p_export.add_argument("--format", choices=["csv", "jsonl"], default="csv")
    p_export.add_argument("--output", "-o", help="Output file (default: stdout)")

    args = parser.parse_args()

    if args.command == "merge":
        merge_databases(args.inputs, args.output, args.threshold)

    elif args.command == "search":
        results = search_db(args.input, args.query, args.field)
        for rec in results:
            print(json.dumps(rec, ensure_ascii=False))
        print(f"Found {len(results)} matches", file=sys.stderr)

    elif args.command == "tag":
        tag_papers(args.input, args.ids, args.tags)

    elif args.command == "add":
        record = json.loads(args.record)
        records = load_jsonl(args.input)
        records.append(record)
        records = deduplicate(records)
        save_jsonl(records, args.input)
        print(f"Added record, DB now has {len(records)} papers", file=sys.stderr)

    elif args.command == "filter":
        filter_db(args.input, args.output, min_score=args.min_score,
                  max_papers=args.max_papers, require_keywords=args.keywords)

    elif args.command == "stats":
        stats = compute_stats(args.input)
        print(json.dumps(stats, indent=2))

    elif args.command == "export":
        if args.format == "csv":
            output = export_csv(args.input)
        else:
            records = load_jsonl(args.input)
            output = "\n".join(json.dumps(r, ensure_ascii=False) for r in records)

        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(output)
            print(f"Exported to {args.output}", file=sys.stderr)
        else:
            print(output)


if __name__ == "__main__":
    main()
