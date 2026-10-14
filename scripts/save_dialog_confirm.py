#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""确认并定向保存 Chrome 触发的中文"另存为"系统对话框（win32 backend）。

背景：MCP 人机操作 Sci-Hub 点阅读器"下载"按钮后，Chrome 弹出系统"另存为"
对话框（标准 Windows #32770 通用对话框）。该对话框对 UIA backend 不可见，
但 win32 backend 完全可编程：文件名 Edit(ctrl_id=1001) + 保存按钮(ctrl_id=1)。
本脚本把"另存为"对话框的保存动作封装成一次调用，配合 MCP 流程实现全自动落盘。

用法：
    python save_dialog_confirm.py "C:/path/to/out.pdf"   # 填目标路径并保存
    python save_dialog_confirm.py --keep                  # 不改名，直接点保存（存到当前目录）
    python save_dialog_confirm.py --wait 3 --check 5      # 等待对话框出现（秒），超时报错

依赖：pywinauto（win32 backend）。中文路径无需转义，本脚本内部用文件方式运行。

注意：本脚本只操作系统"另存为"对话框，不解析网页、不 fetch、不注入脚本，
完全符合"MCP 人机操作 + 浏览器原生下载"的铁律。限速仍由外部人工节奏控制。
"""

import argparse
import sys
import io
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from pywinauto import Desktop

try:
    from pywinauto.findwindows import ElementNotFoundError
except ImportError:
    ElementNotFoundError = Exception


def find_save_dialog(timeout=5):
    """轮询查找中文"另存为"或英文 Save As 的标准对话框（#32770）。"""
    desktop = Desktop(backend="win32")
    deadline = time.time() + timeout
    while time.time() < deadline:
        for w in desktop.windows():
            try:
                if w.class_name() == "#32770" and w.window_text():
                    title = w.window_text()
                    if "另存为" in title or "Save As" in title:
                        return w
            except Exception:
                continue
        time.sleep(0.5)
    return None


NAME_EDIT_CONTROL_ID = 1001
SAVE_BUTTON_CONTROL_ID = 1
CANCEL_BUTTON_CONTROL_ID = 2


def find_controls(dlg, cls, ctrl_id):
    """在对话框子树中查找 class + control_id 匹配的控件。"""
    hits = []

    def walk(ctl):
        for c in ctl.children():
            try:
                ccls = c.class_name()
                cid = c.control_id()
                if ccls == cls and cid == ctrl_id:
                    hits.append(c)
            except Exception:
                pass
            walk(c)

    walk(dlg)
    return hits


def set_edit_text(edit, text):
    edit.set_edit_text(text)
    time.sleep(0.3)


def main():
    ap = argparse.ArgumentParser(description="确认并定向保存“另存为”系统对话框")
    ap.add_argument("path", nargs="?", default=None, help="目标保存路径（文件绝对路径）；省略则保持不变")
    ap.add_argument("--wait", type=int, default=3, help="等待对话框出现的最长秒数（默认 3）")
    ap.add_argument("--check", type=int, default=3, help="点保存后等待并汇报沙盒次数（秒，默认 3）")
    ap.add_argument("--keep", action="store_true", help="不修改文件名，直接点保存")
    args = ap.parse_args()

    if not args.keep and args.path is None:
        sys.stderr.write("[错误] 请提供目标保存路径，或使用 --keep 保持默认文件名\n")
        sys.exit(2)

    dlg = find_save_dialog(timeout=args.wait)
    if dlg is None:
        sys.stderr.write("[错误] 未在 %ss 内找到“另存为”对话框\n" % args.wait)
        sys.exit(1)

    title = dlg.window_text()
    print("[info] 对话框: %r" % title)

    edits = find_controls(dlg, "Edit", NAME_EDIT_CONTROL_ID)
    if not edits:
        sys.stderr.write("[错误] 未找到文件名输入框 (Edit id=%d)\n" % NAME_EDIT_CONTROL_ID)
        sys.exit(1)
    edit = edits[0]
    print("[info] 当前文件名编辑框: %r" % edit.window_text())

    if not args.keep:
        target = args.path.replace("/", "\\")
        set_edit_text(edit, target)
        print("[info] 已设置为: %s" % target)

    saves = find_controls(dlg, "Button", SAVE_BUTTON_CONTROL_ID)
    if not saves:
        sys.stderr.write("[错误] 未找到“保存”按钮 (Button id=%d)\n" % SAVE_BUTTON_CONTROL_ID)
        sys.exit(1)
    save_btn = saves[0]
    print("[info] 准备点击: %r" % save_btn.window_text())
    save_btn.click()
    time.sleep(args.check)
    print("[ok] 已点击保存")
    sys.exit(0)


if __name__ == "__main__":
    main()