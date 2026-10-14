#!/usr/bin/env python3
"""把检索结果 JSONL 写入 Zotero 条目（本地 API 优先，Web API 备选）。

数据流：search_rock_journals.py / iterative_search.py 的 JSONL → 本脚本 → Zotero 条目。
写入前按 DOI 查重，重复条目跳过；可自动创建/复用分类（collection）并打标签。

本地 API（推荐）：
  - 需要 Zotero 客户端正在运行，且已开启
    设置 → 高级 → "允许本机其他应用与 Zotero 通信"
  - 首次写入会弹出授权对话框：请选 **"总是允许"**（Always Allow），
     之后 Key 会缓存到技能目录的 .cache/zotero_local.json，后续不再弹窗

Web API（备选，跨机器但需联网同步）：
  - 需要 zotero.org 的 API Key（勾选允许写入）和用户 ID
  - 用 --web --user-id X --api-key Y 传入

用法:
    # 默认本地 API，写入分类"含水率与岩爆"，自动打标签
    python zotero_import.py results.jsonl --collection "含水率与岩爆" --tag "文献检索"

    # 只写指定 DOI（先筛选后入库）
    python zotero_import.py results.jsonl --only-doi 10.1016/j.jrmge.2023.06.019,10.1007/s40948-024-00807-4

    # 预检模式：只查重不写入，看哪些已在库
    python zotero_import.py results.jsonl --dry-run
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

LOCAL_BASE = "http://localhost:23119/api"
WEB_BASE = "https://api.zotero.org"
# Key 缓存放在技能目录自身的隐藏 .cache 下，不占用其他软件目录
KEY_CACHE = Path(__file__).resolve().parent.parent / ".cache" / "zotero_local.json"
APP_NAME = "WorkBuddy 岩石力学文献检索技能"


class ZoteroWriter:
    def __init__(self, web: bool = False, user_id: str = "", api_key: str = ""):
        self.web = web
        self.user_id = user_id
        self.api_key = api_key
        self.base = WEB_BASE if web else LOCAL_BASE
        self.server_id = None
        self.local_key = None
        if not web:
            self._load_cached_key()

    # ---------- 底层请求 ----------
    def _request(self, method: str, path: str, body: dict | list | None = None,
                 extra_headers: dict | None = None) -> tuple[int, dict | list | None, dict]:
        headers = {"Content-Type": "application/json"}
        if self.web:
            headers["Zotero-API-Key"] = self.api_key
            url = f"{self.base}/users/{self.user_id}{path}"
        else:
            if self.server_id:
                headers["Zotero-Server-ID"] = self.server_id
            if self.local_key:
                headers["Zotero-API-Key"] = self.local_key
            url = f"{self.base}/users/0{path}"
        if extra_headers:
            headers.update(extra_headers)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw) if raw else None), dict(resp.headers)
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                parsed = json.loads(raw) if raw else None
            except Exception:
                parsed = None
            return e.code, parsed, dict(e.headers)

    # ---------- 本地 API 连接与授权 ----------
    def connect(self) -> bool:
        if self.web:
            status, _, _ = self._request("GET", "/collections?limit=1")
            if status != 200:
                print("Error: Web API 认证失败，检查 --user-id / --api-key", file=sys.stderr)
                return False
            return True
        # 本地：探测 + 拿 Server-ID
        try:
            with urllib.request.urlopen(f"{LOCAL_BASE}/", timeout=5) as resp:
                self.server_id = resp.headers.get("Zotero-Server-ID", "")
        except Exception as e:
            print(f"Error: 无法连接 Zotero 本地 API（{e}）。\n"
                  f"请确认：1) Zotero 客户端已打开；2) 设置 → 高级 → "
                  f"勾选『允许本机其他应用与 Zotero 通信』", file=sys.stderr)
            return False
        if not self.server_id:
            print("Error: 本地 API 未返回 Server-ID（Zotero 版本过旧，需 7.1+）", file=sys.stderr)
            return False
        # 缓存的 Key 有效性：试一次读操作（读不需要 Key，改试轻量写探测——直接信任缓存，写入失败时重授权）
        if self.local_key:
            print(f"使用缓存授权 Key（server_id={self.server_id[:8]}...）", file=sys.stderr)
        return True

    def authorize(self) -> bool:
        """弹出 Zotero 授权对话框。用户选『总是允许』后 Key 永久缓存。"""
        # 注意：授权端点在 /api/local/authorize（不在 /users/0 下），需直接构造 URL
        url = f"{LOCAL_BASE}/local/authorize"
        req = urllib.request.Request(
            url, method="POST",
            data=json.dumps({"appName": APP_NAME}).encode(),
            headers={
                "Content-Type": "application/json",
                "Zotero-Server-ID": self.server_id,
                # 若有过期缓存 Key 一并带上，服务端可识别续期
                **({"Zotero-API-Key": self.local_key} if self.local_key else {}),
            })
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:  # 阻塞等待用户点弹窗
                status, body = resp.status, json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as e:
            status = e.code
            try:
                body = json.loads(e.read() or b"{}")
            except Exception:
                body = None
        if status == 403:
            print("Error: 你在 Zotero 弹窗中选择了拒绝", file=sys.stderr)
            return False
        if status == 429:
            print("Error: 授权请求被限流，请等几秒重试（不要循环重试）", file=sys.stderr)
            return False
        if status != 200 or not body or not body.get("key"):
            print(f"Error: 授权失败 HTTP {status}: {body}", file=sys.stderr)
            return False
        self.local_key = body["key"]
        if body.get("remember"):
            KEY_CACHE.parent.mkdir(parents=True, exist_ok=True)
            KEY_CACHE.write_text(json.dumps({
                "key": self.local_key, "server_id": self.server_id, "remember": True,
            }, ensure_ascii=False), encoding="utf-8")
            print("授权成功（已选『总是允许』，Key 已缓存，下次不再弹窗）", file=sys.stderr)
        else:
            print("授权成功（一次性 Key，本次会话有效；建议下次选『总是允许』）", file=sys.stderr)
        return True

    def _load_cached_key(self):
        if KEY_CACHE.exists():
            try:
                cached = json.loads(KEY_CACHE.read_text(encoding="utf-8"))
                self.local_key = cached.get("key")
                self.server_id = cached.get("server_id")
            except Exception:
                pass

    def ensure_write_access(self) -> bool:
        if self.web:
            return True
        if not self.local_key:
            print("首次写入需要授权：请留意即将弹出的 Zotero 对话框，选『总是允许』...", file=sys.stderr)
            time.sleep(1)
            return self.authorize()
        return True

    # ---------- 查重 / 分类 / 写入 ----------
    def exists(self, paper: dict) -> bool:
        doi = (paper.get("doi") or "").strip()
        if doi:
            status, items, _ = self._request(
                "GET", f"/items?format=json&limit=5&q={urllib.parse.quote(doi)}")
            if status == 200 and items:
                return True
        title = (paper.get("title") or "").strip().lower()
        if title and len(title) > 12:
            status, items, _ = self._request(
                "GET", f"/items?format=json&limit=5&q={urllib.parse.quote(paper['title'][:60])}")
            if status == 200 and items:
                for it in items:
                    if (it.get("data", {}).get("title", "") or "").strip().lower() == title:
                        return True
        return False

    def get_or_create_collection(self, name: str) -> str | None:
        status, cols, _ = self._request("GET", "/collections?format=json&limit=100")
        if status == 200 and cols:
            for c in cols:
                if c.get("data", {}).get("name") == name:
                    return c["data"]["key"]
        status, body, _ = self._request(
            "POST", "/collections", body=[{"name": name, "parentCollection": False}])
        if status == 200 and body and body.get("success"):
            key = body["success"].get("0")
            if key:
                print(f"已创建分类：{name}", file=sys.stderr)
                return key
        if status == 409:
            # 已存在但上面没翻到（分页），再翻一次
            print(f"Warning: 分类 {name} 创建冲突，改用未分组写入", file=sys.stderr)
        else:
            print(f"Warning: 分类创建失败 HTTP {status}，条目将不分组", file=sys.stderr)
        return None

    def write_items(self, papers: list[dict], collection_key: str | None,
                    tag: str) -> tuple[int, int]:
        ok, fail = 0, 0
        batch = []
        for p in papers:
            item = paper_to_item(p, collection_key, tag)
            batch.append((p, item))
            if len(batch) >= 25:
                o, f = self._post_batch(batch)
                ok, fail = ok + o, fail + f
                batch = []
        if batch:
            o, f = self._post_batch(batch)
            ok, fail = ok + o, fail + f
        return ok, fail

    def _post_batch(self, batch) -> tuple[int, int]:
        items = [it for _, it in batch]
        status, body, _ = self._request("POST", "/items", body=items)
        if status == 401 and not self.web:
            # Key 失效（缓存的是一次性 Key 或已过期）→ 重新授权再试一次
            print("Key 失效，重新授权...", file=sys.stderr)
            if self.authorize():
                status, body, _ = self._request("POST", "/items", body=items)
        if status in (200, 201) and body and "success" in body:
            ok = len(body.get("success", {}))
            fail = len(body.get("failed", {}))
            if fail:
                print(f"Warning: {fail} 条写入失败: {body.get('failed')}", file=sys.stderr)
            for p, _ in batch:
                print(f"  [OK] {p.get('title', '')[:70]}", file=sys.stderr)
            return ok, fail
        print(f"Error: 批量写入失败 HTTP {status}: {str(body)[:300]}", file=sys.stderr)
        return 0, len(batch)


def paper_to_item(p: dict, collection_key: str | None, tag: str) -> dict:
    """检索 JSONL 字段 → Zotero journalArticle 条目。"""
    creators = []
    for a in p.get("authors", [])[:30]:
        a = a.strip()
        if not a:
            continue
        if "," in a and len(a.split(",")) == 2:          # "Smith, J."
            last, first = [x.strip() for x in a.split(",", 1)]
            creators.append({"creatorType": "author", "firstName": first, "lastName": last})
        elif " " in a:                                     # "J. Smith" → 取最后一段为姓
            parts = a.split()
            creators.append({"creatorType": "author", "firstName": " ".join(parts[:-1]),
                             "lastName": parts[-1]})
        else:                                              # 中文名单名（苏国韶）或单名
            creators.append({"creatorType": "author", "name": a})
    item = {
        "itemType": "journalArticle",
        "title": p.get("title", ""),
        "creators": creators,
        "publicationTitle": p.get("journal") or p.get("venue") or "",
        "DOI": (p.get("doi") or "").strip(),
        "date": str(p.get("year") or ""),
        "abstractNote": p.get("abstract") or "",
        "url": f"https://doi.org/{p['doi']}" if p.get("doi") else (p.get("pdf_url") or ""),
        "shortTitle": "",
        "libraryCatalog": "OpenAlex",
        "tags": [{"tag": tag}] if tag else [],
    }
    if collection_key:
        item["collections"] = [collection_key]
    return item


def main():
    ap = argparse.ArgumentParser(description="检索结果 JSONL → Zotero 条目")
    ap.add_argument("jsonl", help="search_rock_journals.py / iterative_search.py 输出的 JSONL")
    ap.add_argument("--collection", help="目标分类名（不存在则自动创建）")
    ap.add_argument("--tag", default="文献检索", help="自动标签（默认：文献检索）")
    ap.add_argument("--only-doi", help="只写入指定 DOI（逗号分隔），先筛选后入库")
    ap.add_argument("--dry-run", action="store_true", help="只查重预检，不写入")
    ap.add_argument("--web", action="store_true", help="使用 Web API（默认本地 API）")
    ap.add_argument("--user-id", help="Web API 用户 ID")
    ap.add_argument("--api-key", help="Web API Key")
    args = ap.parse_args()

    papers = [json.loads(l) for l in open(args.jsonl, encoding="utf-8") if l.strip()]
    if args.only_doi:
        want = {d.strip().lower() for d in args.only_doi.split(",")}
        papers = [p for p in papers if (p.get("doi") or "").lower() in want]
    print(f"待处理 {len(papers)} 条", file=sys.stderr)

    zw = ZoteroWriter(web=args.web, user_id=args.user_id or "", api_key=args.api_key or "")
    if not zw.connect():
        sys.exit(1)

    # 查重
    todo, dup, nodoi = [], [], []
    for p in papers:
        if not (p.get("doi") or "").strip():
            nodoi.append(p)
        if zw.exists(p):
            dup.append(p)
        else:
            todo.append(p)
    print(f"查重完成：可写入 {len(todo)}，已在库 {len(dup)}，无 DOI（仍可写）"
          f"{sum(1 for p in todo if not p.get('doi'))}", file=sys.stderr)
    if args.dry_run:
        for p in dup:
            print(f"  [已在库] {p.get('title','')[:70]}")
        for p in todo:
            print(f"  [新条目] {p.get('title','')[:70]}")
        return

    if not todo:
        print("没有需要写入的新条目。", file=sys.stderr)
        return
    if not zw.ensure_write_access():
        sys.exit(1)

    col_key = zw.get_or_create_collection(args.collection) if args.collection else None
    ok, fail = zw.write_items(todo, col_key, args.tag)
    print(f"完成：成功 {ok} 条，失败 {fail} 条"
          + (f"，分类：{args.collection}" if col_key else ""), file=sys.stderr)


if __name__ == "__main__":
    main()
