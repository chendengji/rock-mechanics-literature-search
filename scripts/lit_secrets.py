#!/usr/bin/env python3
"""共享凭据与限速模块（仅标准库，用于本技能的所有检索脚本）。

自动从项目级 .env 文件读取各 API 密钥，避免每次手动传参、也避免密钥散落在各脚本里。

.env 候选路径（按序取第一个存在的）：C:\\Users\\QZ\\.config\\opencode\\.env（项目级唯一密钥文件）、
C:\\Users\\QZ\\Desktop\\MouseWithoutBorders\\ScreenCaptures\\.env（旧路径，已迁移）。
可用环境变量 LIT_ENV_FILE 覆盖。解析规则：逐行读 `KEY=value`，忽略 # 注释与空行。

当前支持：
  - Semantic Scholar：SEMANTIC_SCHOLAR_API_KEY（.env 键名）或 S2_API_KEY（备用键名）
    S2 免费/带 Key 均按请求速率限流，这里提供全局节流器 s2_throttle() 防止短时大量请求被封。

任何密钥都不会被打印 / 写入日志 / 写入结果文件。
"""
import os
import sys
import threading
import time

DEFAULT_ENV_FILES = (r"C:\Users\QZ\.config\opencode\.env",
                     r"C:\Users\QZ\Desktop\MouseWithoutBorders\ScreenCaptures\.env")

_SECRETS = None


def _env_file() -> str:
    override = os.environ.get("LIT_ENV_FILE", "")
    if override:
        return override
    for path in DEFAULT_ENV_FILES:
        if os.path.exists(path):
            return path
    return DEFAULT_ENV_FILES[0]


def load_secrets() -> dict:
    """读取 .env 并缓存。返回 {键: 值}，缺失的键返回空串。"""
    global _SECRETS
    if _SECRETS is not None:
        return _SECRETS
    secrets = {}
    path = _env_file()
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                # 去掉可选引号
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                    value = value[1:-1]
                if key:
                    secrets[key] = value
    except OSError as e:
        sys.stderr.write(f"[lit_secrets] 无法读取 .env({path}): {e}\n")
    _SECRETS = secrets
    return secrets


def _var(name: str) -> str:
    return name if name in os.environ else load_secrets().get(name, "")


def s2_api_key() -> str:
    """返回 Semantic Scholar API Key（优先环境变量 S2_API_KEY，其次 .env 的 S2_API_KEY /
    SEMANTIC_SCHOLAR_API_KEY）。"""
    return os.environ.get("S2_API_KEY", "") or load_secrets().get("S2_API_KEY", "") \
        or load_secrets().get("SEMANTIC_SCHOLAR_API_KEY", "")


# ---- Semantic Scholar 全局节流器 ----
# S2 限流严格：无 Key 约 100 请求/5 分钟；带 Key 限额更高但仍有限。
# 统一按全局速率排队，防止轮询多查询时短时大量请求被封。默认 0.55 req/s（约 1.8s/请求）。
_S2_LOCK = threading.Lock()
_S2_LAST = 0.0
_S2_QPS = 0.55


def s2_set_rate(qps: float) -> None:
    global _S2_QPS
    if qps and qps > 0:
        _S2_QPS = qps


def s2_throttle() -> None:
    """保证相邻两次 S2 请求至少间隔 1/_S2_QPS 秒（进程内全局串行化）。"""
    global _S2_LAST
    with _S2_LOCK:
        now = time.monotonic()
        interval = 1.0 / _S2_QPS
        wait = _S2_LAST + interval - now
        if wait > 0:
            time.sleep(wait)
        _S2_LAST = max(_S2_LAST + interval, time.monotonic())
