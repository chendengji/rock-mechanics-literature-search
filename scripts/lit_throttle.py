"""跨进程共享的最小间隔节流器。

为什么要它
-----------
OpenAlex / Semantic Scholar 等 API 按 **出口 IP** 限流。同一台机器上只要同时跑两个
脚本进程（比如 agent 一边跑 iterative_search.py，一边跑 search_openalex.py），每个进程
各按 0.7 req/s 排队，出口速率就是 1.4 req/s，直接触发 429。

原来的 `_LAST_REQUEST_TIME` 是模块内变量，锁也只是 `threading.Lock`——**只在单进程内有效**。
本模块把"最近一次请求时间"落到技能目录 `.cache/` 下的锁文件里，用操作系统级文件锁串行化，
这样所有脚本进程共享同一条请求队列。

用法
----
    import lit_throttle

    lit_throttle.set_rate("openalex", 0.7)   # 可选：覆盖默认速率
    lit_throttle.throttle("openalex")        # 发请求前调用一次

节流器按 endpoint 名隔离：openalex / s2 / crossref 各一条队列，互不影响。

实现说明
--------
- Windows 用 `msvcrt.locking` 锁 1 字节；锁住期间计算等待并 sleep，其他进程在锁上阻塞，
  解锁后读到的是刚写入的新时间戳，自然顺延到下一个时间槽。
- `time.monotonic()` 在 Windows 上是 QPC（自开机起算），跨进程可比；重启后锁文件里的旧值
  会远小于当前时间，等待时间为负，自动不阻塞。
- 非 Windows 或锁文件不可写时，退回进程内节流（行为与旧版一致，不会报错）。
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

try:
    import msvcrt  # type: ignore[import-not-found]

    _HAVE_MSVCRT = True
except ImportError:  # 非 Windows
    _HAVE_MSVCRT = False

# 锁文件与技能目录同级：.cache/ 已在 .gitignore 中，不入库不带走。
_CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"

# 默认速率（请求/秒）：OpenAlex 保守取 0.7，Semantic Scholar 更严。
DEFAULT_QPS = {
    "openalex": 0.7,
    "s2": 0.55,
    "crossref": 0.8,
}

_LOCK_DIR_READY = False
_intervals: dict[str, float] = {}

_thread_lock = threading.Lock()
_inproc_last: dict[str, float] = {}

# 拿锁最多重试次数 × 每次睡眠 = 最长阻塞时间（约 90s），避免永久卡死
_MAX_LOCK_RETRIES = 3000
_LOCK_POLL = 0.03

# 系统重启后 time.monotonic() 归零，锁文件里旧时间戳可能远超当前值，
# 若直接 sleep(wait) 会卡 数小时/数天。超过该秒数的等待视为时钟失效，重置时间戳。
_MAX_SANE_WAIT = 60.0


def set_rate(name: str, qps: float) -> None:
    """设置某 endpoint 的请求速率（每秒请求数，必须 > 0）。"""
    if qps and qps > 0:
        _intervals[name] = 1.0 / float(qps)


def rate(name: str) -> float:
    """返回某 endpoint 当前速率（req/s）。"""
    return 1.0 / interval(name)


def interval(name: str) -> float:
    """返回某 endpoint 当前最小请求间隔（秒）。"""
    if name in _intervals:
        return _intervals[name]
    qps = DEFAULT_QPS.get(name, 0.7)
    return 1.0 / qps


def throttle(name: str = "openalex", intvl: float | None = None) -> float:
    """阻塞直到可以发下一个请求，返回占用的时间槽（monotonic 秒）。

    进程内串行化：保证同进程内相邻请求最小间隔；
    跨进程串行化：通过锁文件让所有脚本进程共用同一队列。
    """
    gap = interval(name) if intvl is None else float(intvl)
    if _HAVE_MSVCRT:
        ts = _throttle_cross_process(name, gap)
        if ts is not None:
            return ts
    return _throttle_in_process(name, gap)


def _lock_path(name: str) -> Path:
    return _CACHE_DIR / f"rate_{name}.lock"


def _throttle_cross_process(name: str, gap: float) -> float | None:
    """用文件锁 + 时间戳实现跨进程排队；任何 IO 失败都返回 None 让调用方退回进程内。"""
    global _LOCK_DIR_READY
    path = _lock_path(name)
    try:
        if not _LOCK_DIR_READY:
            path.parent.mkdir(parents=True, exist_ok=True)
            _LOCK_DIR_READY = True
        fh = open(path, "a+", encoding="ascii")
    except OSError:
        return None

    try:
        fh.seek(0)
        for _ in range(_MAX_LOCK_RETRIES):
            try:
                msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
            except OSError:
                time.sleep(_LOCK_POLL)
                continue

            try:
                fh.seek(0)
                raw = fh.read().strip()
                try:
                    last = float(raw)
                except ValueError:
                    last = 0.0

                now = time.monotonic()
                wait = last + gap - now
                if wait > _MAX_SANE_WAIT:
                    # 旧时间戳失效（系统重启/时钟重置）→ 视为队首，无需等待
                    wait = 0.0
                if wait > 0:
                    time.sleep(wait)

                ts = max(time.monotonic(), last + gap)
                fh.seek(0)
                fh.truncate()
                fh.write(f"{ts:.6f}\n")
                fh.flush()
                return ts
            finally:
                try:
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
        return None
    finally:
        fh.close()


def _throttle_in_process(name: str, gap: float) -> float:
    """退回方案：仅保证本进程内相邻请求最小间隔（与旧版行为一致）。"""
    with _thread_lock:
        last = _inproc_last.get(name, 0.0)
        now = time.monotonic()
        wait = last + gap - now
        if wait > 0:
            time.sleep(wait)
        ts = max(last + gap, time.monotonic())
        _inproc_last[name] = ts
        return ts
