#!/usr/bin/env python3
"""任务目录标准布局：定义、初始化、路径解析、清单生成、历史目录迁移（仅标准库）。

为什么需要：过去每次检索都把脚本、原始命中、中间层、交付表、报告平铺在任务文件夹
根目录，文件一多就分不清"哪份是最终成果、哪份是中间产物"，助手和用户都要靠记忆找文件。
本模块把布局固化成代码，脚本按 `p(root, "03_final", "x.csv")` 取路径即可，
`init` 一次生成骨架 + README，`manifest` 随时导出全量文件清单。

标准布局（任务根目录 = Documents/paper/lit_<主题>_<YYYYMMDD>/）：
    00_config/       任务配置：检索词表、期刊范围、实际执行命令（可复现）
    01_sources/      外部来源快照：各数据源原始返回、跨库合并库
    02_intermediate/ 中间层：去重/标签/评分/摘要合并后的数据与候选表
    03_final/        最终交付：用户主要查看的分级表、含摘要表、references.bib
    04_reports/      分析报告：Markdown 结论、审计统计表
    05_pdf/          全文 PDF
    06_scripts/      本任务自写脚本
    07_logs/         运行日志与错误记录
    99_archive/      过期或被取代的产物（只读留档，不删）

命令行：
    uv run --directory "<技能目录>" scripts/lit_paths.py init   <任务目录> [--topic 主题] [--note 说明]
    uv run --directory "<技能目录>" scripts/lit_paths.py path   <任务目录> <类别> <文件名>
    uv run --directory "<技能目录>" scripts/lit_paths.py manifest <任务目录> [--hash]
    uv run --directory "<技能目录>" scripts/lit_paths.py migrate <任务目录> [--dry-run]
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

PAPER_ROOT = Path.home() / "Documents" / "paper"

# 类别目录名 → 用途说明（顺序即 README 展示顺序）
LAYOUT: list[tuple[str, str]] = [
    ("00_config", "任务配置：检索词表、期刊范围、实际执行命令（可复现）"),
    ("01_sources", "外部来源快照：各数据源原始返回、跨库合并库"),
    ("02_intermediate", "中间层：去重/标签/评分/摘要合并后的数据与候选表"),
    ("03_final", "最终交付：分级表、含摘要交付表、references.bib"),
    ("04_reports", "分析报告：Markdown 结论、审计统计表"),
    ("05_pdf", "全文 PDF"),
    ("06_scripts", "本任务自写脚本"),
    ("07_logs", "运行日志与错误记录"),
    ("99_archive", "过期或被取代的产物（只读留档，不删）"),
]
CATEGORIES = [name for name, _ in LAYOUT]
MARKER = ".lit_task.json"

README_TEMPLATE = """# {topic}

- 任务目录：`{root}`
- 创建时间：{created}
- 标准布局：`scripts/lit_paths.py`（`00_config` → `03_final` → `99_archive`）

## 先看哪里

| 我要看 | 位置 |
|--------|------|
| 最终分级文献表 / 含摘要交付表 | `03_final/` |
| 结论、解读、精读报告 | `04_reports/` |
| 全文 PDF | `05_pdf/` |
| 可复现的检索词与命令 | `00_config/` |
| 全部文件清单 | `MANIFEST.csv` |

## 数据链路

{chain}

## 目录说明

{layout}

{note}
"""


# ---------- 基础工具 ----------

def sanitize_topic(topic: str) -> str:
    """主题词规整：小写、下划线连接、去掉空格与特殊字符。"""
    text = str(topic or "").strip().lower()
    text = re.sub(r"[\s/\\:,，、。;；'\"()（）\[\]]+", "_", text)
    text = re.sub(r"[^0-9a-z_\-一-鿿]+", "", text)
    text = re.sub(r"_{2,}", "_", text).strip("_-")
    return text or "task"


def new_task_dir(topic: str, when: str | None = None, root: Path | None = None) -> Path:
    """返回（不创建）新任务目录路径 Documents/paper/lit_<主题>_<YYYYMMDD>。"""
    stamp = when or datetime.now().strftime("%Y%m%d")
    return (root or PAPER_ROOT) / f"lit_{sanitize_topic(topic)}_{stamp}"


def is_task_root(path) -> bool:
    return (Path(path) / MARKER).exists()


def task_root_for(path) -> Path | None:
    """从任意文件/目录向上找最近的任务根（含标记文件）；找不到返回 None。"""
    cur = Path(path).resolve()
    if cur.is_file():
        cur = cur.parent
    for cand in [cur, *cur.parents]:
        if (cand / MARKER).exists():
            return cand
    return None


def p(root, category: str, name: str = "") -> Path:
    """按标准布局取路径并自动建父目录：p(root, "03_final", "table.csv")。"""
    if category not in CATEGORIES:
        raise ValueError(f"未知类别 {category!r}，可选：{', '.join(CATEGORIES)}")
    base = Path(root) / category
    base.mkdir(parents=True, exist_ok=True)
    return base / name if name else base


def ensure_layout(root) -> Path:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    for name, _ in LAYOUT:
        (root / name).mkdir(exist_ok=True)
    return root


# ---------- init ----------

def init_task(root, topic: str = "", note: str = "", when: str | None = None) -> Path:
    root = ensure_layout(root)
    marker = {"topic": topic, "created": when or datetime.now().isoformat(timespec="seconds"),
              "layout_version": 1, "categories": CATEGORIES}
    (root / MARKER).write_text(json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8")

    chain = ("```\n"
             "01_sources 原始命中 ──合并去重──▶ 02_intermediate 去重/标签/评分\n"
             "     └─摘要补全(fetch/fill/merge)─▶ 02_intermediate 候选表\n"
             "02_intermediate ──人工分级──▶ 03_final 分级交付表 ──▶ 04_reports 结论报告\n"
             "```")
    layout = "\n".join(f"- `{name}/` — {desc}" for name, desc in LAYOUT)
    readme = root / "README.md"
    if not readme.exists():
        readme.write_text(README_TEMPLATE.format(
            topic=topic or root.name, root=root, created=marker["created"],
            chain=chain, layout=layout, note=note.strip()), encoding="utf-8")
    (root / "00_config" / "commands.md").touch(exist_ok=True)
    write_manifest(root)
    return root


# ---------- manifest ----------

def _rows(root: Path) -> list[dict]:
    rows: list[dict] = []
    for f in sorted(root.rglob("*"), key=lambda p: str(p).lower()):
        if not f.is_file() or f.name in (".DS_Store",):
            continue
        if "__pycache__" in f.parts or f.suffix == ".pyc":
            continue
        rel = f.relative_to(root).as_posix()
        cat = rel.split("/", 1)[0] if "/" in rel else "(root)"
        rows.append({"类别": cat, "文件": rel,
                     "大小KB": round(f.stat().st_size / 1024, 1),
                     "修改时间": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")})
    return rows


def write_manifest(root, with_hash: bool = False) -> Path:
    import hashlib
    root = Path(root)
    rows = _rows(root)
    if with_hash:
        for row, f in zip(rows, sorted((p for p in root.rglob("*") if p.is_file()
                                        and "__pycache__" not in p.parts and p.suffix != ".pyc"),
                                       key=lambda p: str(p).lower())):
            h = hashlib.sha256()
            with f.open("rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            row["sha256"] = h.hexdigest()[:16]
    out = root / "MANIFEST.csv"
    fields = ["类别", "文件", "大小KB", "修改时间"] + (["sha256"] if with_hash else [])
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    return out


# ---------- migrate：历史平铺目录 → 标准布局 ----------

_MIGRATE_RULES: list[tuple[str, str]] = [
    # (正则, 类别)；自上而下首个命中即定
    (r"^README\.md$", "(root)"),
    (r"MANIFEST\.csv$", "(root)"),
    (r"\.py$", "06_scripts"),
    (r"\.log$", "07_logs"),
    (r"\.bib$", "03_final"),
    (r"\.pdf$", "05_pdf"),
    (r"^merged_all\.jsonl$", "01_sources"),
    (r"^raw(_.*)?$", "01_sources"),
    (r"_中间层", "02_intermediate"),
    (r"_候选文献表", "02_intermediate"),
    (r"^(web_abstracts|s2_fill|abstract_pool)", "02_intermediate"),
    (r"DOI.*\.txt$|待抓.*\.txt$", "02_intermediate"),
    (r"^result_.*(筛选|去重)", "02_intermediate"),
    (r"(分级交付表|交付表)", "03_final"),
    (r"_全表", "04_reports"),
    (r"_审计", "04_reports"),
    (r"\.md$", "04_reports"),
    (r"\.(jsonl|json|csv)$", "99_archive"),
]


def classify(name: str) -> str:
    for pattern, cat in _MIGRATE_RULES:
        if re.search(pattern, name, re.I):
            return cat
    return "99_archive"


_KEEP_AT_ROOT = {"README.md", "MANIFEST.csv", MARKER}


def migrate(root, dry_run: bool = False) -> list[tuple[str, str]]:
    """把任务根目录下平铺的文件/目录按规则搬进标准布局；返回 (原相对路径, 新相对路径)。"""
    root = Path(root)
    moves: list[tuple[str, str]] = []
    for item in sorted(root.iterdir(), key=lambda x: x.name.lower()):
        if item.name in _KEEP_AT_ROOT or item.name in CATEGORIES:
            continue  # 已归档的类别目录、清单与说明文件原地不动
        cat = classify(item.name)
        if cat == "(root)":
            continue
        dest = root / cat / item.name
        if dest.exists():
            stem, suf = item.stem, item.suffix
            n = 2
            while (root / cat / f"{stem}_{n}{suf}").exists():
                n += 1
            dest = root / cat / f"{stem}_{n}{suf}"
        moves.append((item.relative_to(root).as_posix(), dest.relative_to(root).as_posix()))
        if not dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(item), str(dest))
    if not dry_run:
        meta = {}
        if (root / MARKER).exists():
            try:
                meta = json.loads((root / MARKER).read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                meta = {}
        init_task(root, meta.get("topic") or root.name)  # 骨架与 README 补齐后再刷新清单
        log = root / "07_logs" / "migrate.log"
        stamp = datetime.now().isoformat(timespec="seconds")
        log.write_text(stamp + "\n" + "\n".join(f"{a}  ->  {b}" for a, b in moves) + "\n",
                       encoding="utf-8")
        write_manifest(root)
    return moves


# ---------- CLI ----------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="任务目录标准布局工具（定义见本文件顶部）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    q = sub.add_parser("init", help="创建标准布局骨架 + README + MANIFEST")
    q.add_argument("root")
    q.add_argument("--topic", default="")
    q.add_argument("--note", default="")
    q.add_argument("--when", default=None, help="YYYYMMDD（默认今天）")

    q = sub.add_parser("new", help="按主题生成并初始化新任务目录")
    q.add_argument("topic")
    q.add_argument("--when", default=None)
    q.add_argument("--note", default="")
    q.add_argument("--root", default=str(PAPER_ROOT))

    q = sub.add_parser("path", help="取标准布局下的路径并建父目录")
    q.add_argument("root")
    q.add_argument("category", choices=CATEGORIES)
    q.add_argument("name", nargs="?", default="")

    q = sub.add_parser("manifest", help="导出 MANIFEST.csv")
    q.add_argument("root")
    q.add_argument("--hash", action="store_true", help="附 sha256 前 16 位（慢，大文件慎用）")

    q = sub.add_parser("migrate", help="把平铺的旧目录迁入标准布局")
    q.add_argument("root")
    q.add_argument("--dry-run", action="store_true")

    args = ap.parse_args(argv)
    try:
        if args.cmd == "init":
            print(init_task(args.root, args.topic, args.note, args.when))
        elif args.cmd == "new":
            print(init_task(new_task_dir(args.topic, args.when, Path(args.root)),
                            args.topic, args.note, args.when))
        elif args.cmd == "path":
            print(p(args.root, args.category, args.name))
        elif args.cmd == "manifest":
            print(write_manifest(args.root, args.hash))
        elif args.cmd == "migrate":
            moves = migrate(args.root, args.dry_run)
            print(f"{'(dry-run) ' if args.dry_run else ''}{len(moves)} 项")
            for a, b in moves:
                print(f"  {a}  ->  {b}")
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
