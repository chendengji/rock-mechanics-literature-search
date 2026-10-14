# Sci-Hub 全文 PDF 下载操作规范

> 铁律：**只用 chrome-devtools MCP 工具模拟人类操作实体 Chrome**；严禁任何代码解析
> 网页、fetch、requests、playwright 等程序化抓取（对 sci-hub 的验证码/反爬全部失效，
> 且会触发封禁）。系统"另存为"对话框属于 Windows 桌面窗口，由
> `scripts/save_dialog_confirm.py`（pywinauto win32 backend）自动确认——等价于人类
> 在弹窗里填路径点保存，不算程序化抓取。

## 1. 前置条件

| 项 | 要求 |
|---|---|
| 实体 Chrome | 已用调试端口启动：`chrome.exe --remote-debugging-port=9222 --remote-allow-origins=* --user-data-dir="%LOCALAPPDATA%\ChromeDebug9222"` |
| MCP chrome-devtools | opencode 配置中已启用，且指向该端口 |
| Python 环境 | uv 管理：`uv run --directory "C:/Users/QZ/.config/opencode/skills/rock-mechanics-literature-search"` 自动选用 uv 托管 CPython 3.12.x；pywinauto 等依赖声明在技能目录 `pyproject.toml`，已装入该目录 `.venv`（win32 backend） |

## 2. 操作步骤

1. **导航**：`chrome-devtools_new_page` 打开 `https://sci-hub.st/{DOI}`（镜像按序
   尝试 `.st`→`.ru`→`.se`）。
2. **过证书警告**（若出现"隐私设置错误"）：点"高级"→"继续前往 ...（不安全）"。
3. **等人机验证自动通过** → 页面跳转到可访问镜像（实测常为 `sci-net.xyz`）→
   PDF 在内置阅读器加载。
4. **下载**：多次 `Tab` 让阅读器工具栏暴露下载按钮 →
   `chrome-devtools_click` 点"下载" → 弹系统"另存为"对话框。
5. **自动确认保存**：运行
   `uv run --directory "C:/Users/QZ/.config/opencode/skills/rock-mechanics-literature-search" scripts/save_dialog_confirm.py "<任务pdf目录>\<作者>_<年份>_<短题>.pdf"`
   （win32 backend 定位 `#32770`"另存为" → 文件名框填目标路径 → 点"保存"），
   PDF 直接落盘到目标位置，**无需人工**；或 `--keep` 存默认目录。
6. **核对与收尾**：核对 PDF 大小/文件头 `%PDF-`；必要时移入
   `Documents\paper\lit_...\pdf\`；更新 `fulltext_status=downloaded`。

## 3. 限速与纪律（强制）

- 每篇 DOI 下载之间至少等待 8-15 秒；对同一镜像连续操作 ≤3 篇后停 1 分钟以上，
  避免触发频控。
- 每个 MCP 动作之间留 ≥1-2 秒（先 `Start-Sleep`）；禁止连续快速点击或批量连发。
- 一次会话最多处理约 10-15 篇；超量后提醒用户分批。
- 若遇到"未能加载 PDF / 重新加载"，点"重新加载"重试 1-2 次仍失败则记为失败并
  换 DOI/镜像，**不得反复重试同一篇**。
- 浏览器内所有操作必须用 chrome-devtools MCP 工具（snapshot 查看 / click /
  press_key）；**不得**用 `chrome-devtools_evaluate_script` 解析 DOM、不得注入下载脚本。

## 4. 常见问题

- **隐私设置错误 / 证书警告** → 走 2.2 点"高级→继续前往"。
- **"你是机器人吗？"验证页** → 等待自动通过；不要点任何元素。
- **"未能加载 PDF 文档"** → 点"重新加载" 1-2 次；仍失败 → 换镜像或记为失败。
- **下载按钮在快照里不出现** → 连按几次 Tab（阅读器工具栏需要焦点链暴露）；或先单击 PDF 内容区再 Tab。
- **点"下载"后 Downloads 只出现 `.tmp` 固住不动** → 是"另存为"对话框在前台等待确认；
  正常运行 `save_dialog_confirm.py`（它按 `#32770` 类名找对话框，标题中文与否都行）。
- **对话框找不到（脚本报错）** → 先确定 `#32770` 窗口存在：win32 枚举顶层窗口里应有
  标题"另存为"的 `#32770`；若没有，说明 Chrome 未弹窗（这次点击可能被下载栏吞掉），
  换镜像或重新点一次下载。
- **同名文件冲突弹窗**（"替换或跳过"）→ 用 `references/windows-control/scripts/handle_dialog.py`
  相关脚本，或 win32 按按钮文本点"替换"。建议保存时用唯一文件名避免冲突。
- **点击"下载"后什么也没发生** → Chrome 可能把该 PDF 判定为需真人授权；换 DOM 直链/换镜像。
- **中文路径写不进去 / 控制台乱码** → 脚本路径参数用 ASCII；如需中文路径，可把目标写成
  临时 ASCII 路径再在 Python 内 `os.rename`，或把脚本放 UTF-8 文件里执行。

## 5. 合规提示

Sci-Hub 的使用涉及版权与所在地区法律风险，仅供个人学术研究。请遵守所在地区与平台条款；
系统接入的实体 Chrome 属于用户，本规范仅用于个人科研用途的文献获取。