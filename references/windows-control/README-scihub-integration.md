# windows-control 技能集成说明（Sci-Hub 下载专用）

本子目录来自 `spliff7777/windows-control`（MIT License），来源仓库
`https://github.com/clawdbot/skills` commit `aca5437`（经 CocoLoop 商店分发 zip）。
原技能只做二进封装，未做修改，直接整套拷贝以供本技能在"另存为"系统对话框
等场景使用。

## 与本技能的结合点

- Sci-Hub 全自动下载闭环的最后一步：Chrome 阅读器"下载"按钮 → 系统"另存为"
  对话框 → 用 `save_dialog_confirm.py`（位于上级 `scripts/`）确认保存。
- 原 `scripts/handle_dialog.py` 使用 `Desktop(backend="uia")`，**对中文"另存为"
  对话框（类名 `#32770`，标准 Win32 通用对话框）不可见**，枚举不到。
- 正确做法：用 **win32 backend** 枚举顶层窗口，按 `class_name() == "#32770"`
  且标题含"另存为"/"Save As"定位对话框。

## 关键控件标识（win32 backend，"另存为"对话框）

| 控件 | class | control_id | 说明 |
|---|---|---|---|
| 文件名输入框 | `Edit` | 1001 | 可 `set_edit_text(完整路径)` 实现定向保存 |
| 保存按钮 | `Button` | 1 | 文本为"保存(&S)" |
| 取消按钮 | `Button` | 2 | 文本为"取消" |
| 地址栏 | `Edit` | 41477 | 当前目录（如"地址: 下载"） |

绕过 title 中文匹配的可靠定位：枚举 Desktop(win32) 顶层窗口，找
`class_name() == "#32770"` 且有标题者。

## 依赖

```
uv sync --directory "C:/Users/QZ/.config/opencode/skills/rock-mechanics-literature-search"
```

依赖声明在技能根目录 `pyproject.toml`（`pywinauto==0.6.9`、`pyautogui==0.9.54`、`pillow`），
由 uv 装入该技能目录 `.venv`；Python 由 uv 选用其托管的 CPython 3.12.x。
**不要 `pip install`、不要手装 Python**——本机 Python 统一由 uv 管理。
脚本运行：`uv run --directory "<技能目录>" scripts/save_dialog_confirm.py ...`。

## 用法提醒

- 脚本经 PowerShell→cmd 管道运行时中文参数/脚本正文会乱码，**一律写成临时
  `.py` 文件再执行**，或直接把目标路径作为 `save_dialog_confirm.py` 的 argv
  参数（内部 UTF-8 IO 包装，已处理）。
- `save_dialog_confirm.py "绝对路径.pdf" --wait 5`：等对话框 ≤5s，填路径保存。
- `save_dialog_confirm.py --keep`：保持默认文件名直接保存。