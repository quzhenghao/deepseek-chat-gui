# DeepSeek Chat GUI：Windows 完整移植实施与验收说明书

> 给在 **原生 Windows 电脑**上拿到本仓库的 AI 助手执行。本文是改造规范和验收门槛，不表示 Windows 版本已经构建或通过验证。目标是保留现有 Chat、Harness、数据和交互能力，同时让每个界面在 Windows 上清楚、完整、可点击、可滚动。任何一项门槛失败，都继续修复并重验，不以“能启动”代替移植完成。

## 0. 基线、范围与实施原则

- 分析基线：[本仓库 `main` 源码](https://github.com/quzhenghao/deepseek-chat-gui/tree/main)，版本 `app/__init__.py::__version__ == "1.0.0"`。2026-09-14 的 macOS 后续修复包含输入框 84/252 高度、可中断的流式跟随、平滑展开和多会话并行；开始移植时先记录 `git rev-parse HEAD` 并核对远端，再按实际提交差异重做风险盘点，不直接套用旧行号。
- `v1.0.0` Release 的同名 macOS DMG 是后续修复构建，标签仍指向初始发布提交 `7df1d7f`。Windows 移植须从最新 `main` 获取源码，不能以 Release 标签或 DMG 中的源码版本号推断功能提交已包含在克隆中。
- 本说明书以移植开始时 `main` 的 **Git 跟踪文件**为准；本机忽略的供应产物和未提交改动不会随 GitHub 克隆到 Windows。Windows 助手应先确认自己克隆的提交和工作树，再对照本说明书实施。
- 主目标：Windows 10/11 **x64** 原生运行和原生打包。Windows ARM64 应作为另一个独立构建/验收目标，不能把 x64 包改名为 ARM64 包；若目标电脑是 ARM64，先核对 PySide6、PyInstaller、Node 和 Harness 原生依赖的对应 wheel/包，再建立同等测试矩阵。
- 保留 macOS 路径与既有 `scripts/package_macos.sh`、`scripts/vendor_harness.sh`、`scripts/release_github.sh` 的功能。Windows 代码使用明确的平台分支，不能把 macOS 的 `.app`、Darwin Node、签名/DMG 流程混进 Windows 成品。
- 首个 Windows 成品采用 PyInstaller **onedir**，交付整个 `dist/DeepSeek/`（可再压缩为 ZIP）；随后如需安装器，再在通过相同验收后包装整个目录。PyInstaller 需要在目标操作系统构建，不能用 macOS 产物充当 Windows 构建。参见 [PyInstaller 官方跨平台说明](https://pyinstaller.org/en/stable/operating-mode.html)。
- 开发与验收使用仓库内 `.venv/` 和任务专属 `.tmp/windows-port/`，测试数据通过 `DEEPSEEK_CHAT_GUI_HOME` 定向到该临时目录。不要安装全局 npm 包、修改全局 PATH/注册表来掩盖应用缺陷；清理时只处理本次生成且有记录的目录。正式应用的用户数据仍按项目现有规则位于 `Path.home() / ".deepseek_chat_gui"`。

### 功能等价合同

必须保留：API Key/自定义地址与模型同步；Chat SSE 流式输出、取消生成、思考折叠和 Low/High/Max；**每个会话独立 `ChatWorker`，多个会话可同时输出，切换历史或新建对话不取消其他会话；运行中的输入框可提前键入下一轮内容，切换后按会话恢复未发送文字、光标和待发送图片；侧栏用与思考区同源的旋转指示器标记仍在执行的会话**；**Chat 输入框普通 84 逻辑像素、展开 252 逻辑像素的两档目标高度、约 60fps 非线性展开/收起、右上角矢量切换按钮及两档内部纵向滚动，输入、删除、发送与新对话均不因文本长度改变所选高度**；联网搜索函数调用、引用和来源链接；图片选择/拖入/粘贴、8 张上限、32 MiB 上限、历史持久化与原图打开；Markdown、代码复制、表格、链接、离线 KaTeX（公式、矩阵、长公式滚动）；新对话、历史标题、重命名、单项/批量删除和媒体清理；浅色/深色主题、系统提示词、设置验证；Chat/Harness 切换、**仅预热 Harness 本地服务、用户切换时才创建并加载 WebEngine 页面**、项目目录、官方 Harness 页面及其工作区、工具、终端、审批和轨迹；退出时关闭属于本应用的进程。官方 Harness 版本是开发者预览，实际服务端能力仍以固定包和用户账号为准，不把外部服务变动误判成桌面移植成功或失败。

## 1. 仓库结构与依赖结论

| 层 | 文件/依赖 | 当前作用与 Windows 结论 |
| --- | --- | --- |
| 入口 | `main.py` | PySide6 `QApplication`，显式 `Fusion` 样式、PNG 窗口图标；可跨平台。窗口/任务栏图标及 DPI 要在 Windows 实测。 |
| 路径 | `app/__init__.py`, `app/config.py`, `app/storage.py`, `app/diagnostics.py` | `sys._MEIPASS` 资源定位；用户目录为 `~/.deepseek_chat_gui`，JSON 以 `.tmp` 原子替换，媒体当前存**绝对路径**。Windows 新数据可工作，跨电脑搬运旧媒体需单独迁移。 |
| API | `app/api.py`, `app/worker.py` | `requests` 流式请求、搜索、标题后台线程，主体无 POSIX API；DuckDuckGo/网页读取的 User-Agent 写死为 Macintosh，需调整与回归。 |
| Chat UI | `app/ui/main_window.py`, `sidebar.py`, `message_bubbles.py`, `settings_dialog.py`, `controls.py`, `icons.py`, `image_strip.py` | `MainWindow._streams` 按会话 ID 管理流式任务，界面切换只重建可见气泡；`_drafts` 在应用运行期间保存每个会话的未发送输入，关闭应用不承诺草稿持久化。侧栏复用 `ThinkingIndicator`。悬浮输入区使用固定 84/252 逻辑像素的可滚动编辑器；外层 composer 在展开动画每帧和图片条变化时同步重排。另有大量固定宽高、绝对定位、透明弹窗/菜单和 Mac 字体假设；Windows 字体、缩放、低逻辑分辨率仍是主要视觉风险。 |
| 富文本 | `app/markdown.py`, `app/ui/message_bubbles.py` | 普通文字用 `QTextBrowser`，公式和代码块用 `QWebEngineView + QWebChannel + KaTeX`；Windows 需验 `file:///C:/...` 基准 URL、WebEngine 进程/资源/字体、滚动和复制。`app/markdown.py` 已有 Consolas 分支。 |
| Harness | `app/harness.py`, `app/ui/harness_page.py`, `app/ui/main_window.py` | 启动官方 `@deepseek-ai/dsh@0.1.5-rc.1` 的 `dsh web`，loopback token URL 嵌入 WebEngine。`warm()` 只启动本地服务，页面仅在切到 Harness 后创建；须保留此顺序。Node 路径、`npx`、Unix 进程组及 `ps/lsof/killpg` 清理在 Windows 必改。 |
| Python 依赖 | `requirements.txt`: `PySide6>=6.8,<7`, `requests>=2.31,<3`, `markdown-it-py>=3,<5`; `requirements-dev.txt`: `pyinstaller>=6.11,<7`, `ruff>=0.6,<1` | 使用 Windows x64 CPython 3.11 建隔离环境，完成第一次通过后记录实际解析版本并锁定构建环境。PySide6 的 Qt WebEngine、Qt Network、Qt WebChannel、Qt SVG/图像插件必须实际导入/打包核验。 |
| 资源 | `assets/app-icon.png`（1024²）、`assets/app-icon.icns`、SVG、`assets/vendor/katex/{katex.min.js,katex.min.css,fonts/*.woff2,LICENSE}` | PNG/内置 KaTeX 可跨平台；`.icns` 不可当 Windows 可执行文件图标，应从 PNG 生成多尺寸 `.ico`。KaTeX 字体和 QSS SVG 要随包保留。 |
| 构建 | `DeepSeekChat.spec`, `scripts/*.sh`, `.gitignore`, `README.md`, `CHANGELOG.md`, `update.md` | `.spec` 无条件创建 `BUNDLE`、使用 `.icns`；脚本使用 bash、Darwin tarball、codesign、hdiutil 和 DMG。需要独立 Windows 供应/打包/发布路径和文档。 |
| 测试 | `tests/` 已纳入 Git | 源码克隆包含 API、存储、Markdown、Qt 与 WebEngine 回归。Windows 仍须补平台进程、路径、桌面视觉和干净机验收；CI 要防止零测试假通过。 |

当前本机已有的、被 Git 忽略的 `vendor/harness/` 是 **Darwin arm64** 供应结果，内有 `@vscode/ripgrep-darwin-arm64`、`@img/sharp-darwin-arm64`、`@koromix/koffi-darwin-arm64` 等，不能复制到 Windows；`node-pty` 虽带多平台预编译 `.node`，其余 optional/native 包仍按安装平台选择。顶层 `dsh@0.1.5-rc.1` 使用 `^` 版本的传递依赖，本机供应树实际出现 `0.1.5-rc.2`，所以“顶层固定”并不等于整树可复现。Windows 供应必须在 Windows 上建立并提交 `package-lock.json`，再用 `npm ci`。可核对 [npm 官方包元数据](https://registry.npmjs.org/%40deepseek-ai%2Fdsh/0.1.5-rc.1) 和 [官方 Harness 仓库](https://github.com/deepseek-ai/deepseek-harness)。

## 2. Windows AI 助手应按此顺序实施

### 阶段 A：确认环境和复现基线

1. 在新克隆上运行 `git rev-parse HEAD`、`git status --short`、`git ls-files`，记录提交和用户已有改动。保留用户文件；若与开始移植时记录的 `main` 提交不同，逐文件重查本说明书的风险点。
2. 在 Windows PowerShell（非 WSL）确认操作系统、`[Environment]::Is64BitProcess`、`py -3.11 --version`、`node --version`（系统 Node 可没有）、显示器逻辑工作区和缩放比例。建议先用 Windows x64 Python 3.11；当前 `requirements` 是范围约束，首次通过后锁定具体解析版本。
3. 用 `py -3.11 -m venv .venv` 建仓库内虚拟环境；用 `./.venv/Scripts/python.exe -m pip install -r requirements.txt -r requirements-dev.txt` 安装，不调用裸 `pip`。检查 `import PySide6.QtWebEngineWidgets, PySide6.QtWebChannel, PySide6.QtNetwork`；通过 `QImageReader.supportedImageFormats()` 确认 PNG/JPEG/GIF/WebP。若缺某格式，修复 Qt 插件供应，不能删掉用户界面的格式承诺。
4. 用项目内独立数据目录做初次源码启动：PowerShell 中设 `$env:DEEPSEEK_CHAT_GUI_HOME = (Join-Path (Get-Location) '.tmp/windows-port/user-data')`。首次只验 Chat 窗口时可先把 `harness_warm_start` 设为 `false`，隔离尚未移植的 Node 启动路径，然后 `./.venv/Scripts/python.exe main.py`。确认首次设置页、欢迎页、窗口图标和中文输入；Harness 运行时改完后必须再把预热设为 `true` 复验服务先启动而 WebEngine 不抢先绘制。源码启动只能证明第一关，不算完成。
5. 如需准备回归基线，仓库自带的 `assets/screenshots/{welcome,settings,web-search,chat-latex,harness}.png` 均为 1360×900 的 macOS 参考图；它们是布局与信息层级参照，Windows 字体/抗锯齿不同，不要求像素逐点相同。

阶段 A 第 4 步的隔离配置可在首次启动前这样建立；这是分阶段诊断用配置，不能替代最终的预热验收：

```powershell
$env:DEEPSEEK_CHAT_GUI_HOME = Join-Path (Get-Location) '.tmp/windows-port/user-data'
New-Item -ItemType Directory -Force -Path $env:DEEPSEEK_CHAT_GUI_HOME | Out-Null
[System.IO.File]::WriteAllText((Join-Path $env:DEEPSEEK_CHAT_GUI_HOME 'config.json'), '{"harness_warm_start":false}', [System.Text.UTF8Encoding]::new($false))
./.venv/Scripts/python.exe main.py
```

### 阶段 B：让 Harness 有真正的 Windows 运行时

1. 新增 `scripts/vendor_harness_windows.ps1`（或等价的仓库内 Python 构建脚本），只在 Windows x64 执行；使用 `build/windows-harness-stage/` 暂存，只在验证完整后原子移动到被忽略的 `vendor/harness-win-x64/`。遇到已有未知目录先报错，不能无条件 `Remove-Item -Recurse`。修改 `.gitignore` 增加该供应目录的规则。Mac 原有 `vendor/harness/` 不动。
2. 从 [Node 官方 v22.19.0 发行目录](https://nodejs.org/download/release/v22.19.0/)取得 `node-v22.19.0-win-x64.zip`，与 [官方 SHASUMS256](https://nodejs.org/download/release/v22.19.0/SHASUMS256.txt)核对：`ea3fad0e67a991d8477d8c01344b56e69c676ccb733f065b22436994b1253f86`。保持压缩包内 `node.exe`、`npm.cmd`、`npx.cmd`、npm 模块和 LICENSE 的相对结构，供应目录中的节点约定为 `vendor/harness-win-x64/node/node.exe`。下载/解压都只在阶段目录中进行。
3. 新增并提交 Windows 专用 Harness 清单（例如 `packaging/harness-windows/package.json` 和 `package-lock.json`），`dependencies` 中写精确的 `"@deepseek-ai/dsh": "0.1.5-rc.1"`。**在 Windows 上**生成/审查锁文件；供应脚本把清单复制到阶段目录，设置阶段目录内的 `npm_config_cache`，执行内置 `npm.cmd ci --prefix <阶段目录> --omit=dev`。不要沿用 macOS 脚本的 `--no-package-lock`；不要为了让安装表面成功而统一使用 `--ignore-scripts`，因为 `node-pty`、`koffi` 等包含原生安装/后安装步骤。如预编译包缺失或要求编译，查清并锁定相应 Windows x64 依赖，再重做阶段，不能把 Darwin 的 `.node` 带入。
4. 对阶段目录做静态+运行检查：存在 `node/node.exe` 和 `node_modules/@deepseek-ai/dsh/lib/bin.js`；运行 `node.exe --version` 为 v22.19.0；`node.exe <bin.js> --version` 能执行；`npm ls --omit=dev --all` 无缺失；Windows x64 的 `@vscode/ripgrep-win32-x64`、`node-addon-require-builtin-win32-x64-msvc`、`@koromix/koffi-win32-x64`、`@img/sharp-win32-x64` /相关依赖按锁文件出现，且没有把 Darwin-only 可执行/原生包当作 Windows 依赖。特别实测 Harness 的项目浏览、搜索、终端、文件操作和审批；通过 `--version` 不能证明这些原生模块可用。
5. `app/__init__.py` 的 `HARNESS_BUNDLE_DIR` 在 `sys.platform == "win32"` 时指向 `vendor/harness-win-x64`，其余平台保留原路径。`DeepSeekChat.spec` 的 `datas` 只收当前平台的供应目录，并映射到同一相对位置；不要把 Mac 供应目录整个收进 Windows 包。

### 阶段 C：改造 `app/harness.py` 的平台边界

按函数实施，不能只把字符串 `node` 改成 `node.exe`：

| 位置 | 必须修改的行为 | 验证点 |
| --- | --- | --- |
| `find_node`, `find_npx`, `find_bundled_harness_cli`, `bundled_harness_available`（约 46–99 行） | Windows 优先核查 **供应目录内**的 `node/node.exe` 和 CLI；源码模式才查系统 `node.exe`。`bundled_harness_available` 不能通过“系统 Node + 随包 CLI”误报为完全内置。macOS 的 `/opt/homebrew/bin` 等候选只能存在于 Darwin 分支。 | 移走系统 Node/清空测试 PATH 后，完整包仍显示“已内置”且 Harness 能启动；故意删供应 `node.exe` 后状态显示缺失。 |
| `start`（约 233–333 行） | 完整包直接以 `node.exe` 为 `QProcess` 的**绝对** program，参数为 CLI `bin.js web --no-open --port <port>`，这样不会经过 shell/`npx.cmd`。源码回退若用 npm，定位系统 `node.exe` 加 `node_modules/npm/bin/npx-cli.js` 后仍由 Node 执行；若只有 `.cmd` 却无可用 Node，明确报错。Qt 的 `QProcess` 对 Windows batch/cmd 的参数规则与普通可执行文件不同，不能把 `shutil.which("npx")` 的 `.cmd` 结果原样作为可靠 program。[Qt QProcess 文档](https://doc.qt.io/qt-6/qprocess.html)有 Windows 启动/引号说明。 | 在安装路径含空格和中文时检查真实 program/arguments；无需全局 Node；无短暂控制台窗口；首启和重启都解析到含 `?token=` 的 127.0.0.1 URL。 |
| 子进程环境（约 284–316 行） | 继承系统环境并前置实际 `node.exe` 所在目录到 `PATH`，保留 `SystemRoot`/临时目录等系统变量。保留 `DSH_HOME`、缓存、API Key、base URL；Windows 不强制写入 `LANG=zh_CN.UTF-8` 与 `LC_ALL=zh_CN.UTF-8`，用 UTF-8 解码子进程输出并实测中文路径。日志对 token/API Key 脱敏。 | `settings.yaml` 不含密钥；Web UI 可读中文目录；日志无完整 Key/token。 |
| `_configure_process_isolation`, `stop`, `_process_finished`, `_kill_port_owner`（约 110–132、335–469、548–571 行） | `UnixProcessParameters`、`os.killpg`、`ps`、`lsof`、`signal.SIGKILL` 仅在 POSIX 分支使用。Windows 为启动的 Node 进程创建**仅属于本次 Harness 实例**的 Job Object，使用 `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` 或 `TerminateJobObject` 管理子进程树；记录 PID、job handle、启动代次，停止/崩溃/超时后清理并关闭句柄。若采用 `QProcess.started` 后 `AssignProcessToJobObject`，检测并处理分配失败及早期子进程竞态；必要时用受控挂起创建或等价机制。绑定 Job 失败时清理已启动的本实例进程并报错，不能报告成功后放任其成为孤儿。不要按端口扫全机后杀未证实归属的 PID。Windows Job Object 的子进程继承和关闭语义见 [Microsoft 文档](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)。 | 关闭窗口、切换配置导致重启、启动超时、异常退出各做 20 次：旧 Node/工具子进程消失、端口释放，不碰同机其他 Node 服务，界面无 5 秒同步冻结。 |
| `_read_output`, `_HARNESS_URL_RE`, `_probe`, `_maybe_ready` | 保留 stdout/stderr 双通道、按代次防旧回调；使用增量 UTF-8 解码，避免中文恰跨读块被 `�` 替换。只接受本机 loopback 与 token；服务端短暂可连不等于认证已完成。端口从“取空闲再释放”到真正绑定存在竞态，发生冲突时重新分配并有限次数重试。 | 分块输出、CRLF、启动失败、错误 token、端口占用的测试均有明确状态；外部地址不加载到内嵌页面。 |
| `_process_error`, `_startup_timed_out` | 错误文本区分“内置 Node 损坏/CLI 缺失/系统 Node 缺失/端口冲突”，不总写“无法启动 npx”；超时提示不能在内置包下误说“首次下载官方运行包”。 | 设置页、Harness 状态页显示真实可执行的修复建议。 |

`app/ui/main_window.py::showEvent/_schedule_harness_warm/_warm_harness` 在主窗口首次显示后安排预热；`app/ui/harness_page.py::warm()` 只调用 `runtime.start()`，不创建 `QWebEngineView`。保留这个平台无关的边界：当前页是 Chat 时，即使主窗口退到后台或最小化，服务就绪/失败信号也不应让隐藏的 Harness 页绘制或刷新状态。用户切换时，`MainWindow._switch_mode()` 必须先把 `page_stack` 指到 Harness，再调用 `HarnessPage.start()`；即使当前 `_mode` 已是 `harness`、但设置页占着 stack，也要恢复当前页。`_on_ready()` 用 `QStackedWidget.currentWidget()` 与可见/最小化状态判断；若就绪时已选 Harness 但窗口最小化，以 `_surface_pending` 延后到恢复显示；若就绪时仍在 Chat，保持服务运行，等首次切换由 `start()` 创建页面。设置改变导致服务重启时，不得在 Chat 上显示 Harness 状态或重建 WebEngine。针对 Windows 的窗口显示、最小化、还原时序做真实桌面测试；如 Qt 在某种还原路径不发 `HarnessPage.showEvent`，应补窗口状态变化处理并确保待绘制状态只消费一次。验证预热全程 Chat 无整窗刷新/闪烁、无输入丢失，首次切换才展示加载状态并最终显示页面，反复切换/重启不白屏。

新基线的 `app/ui/controls.py` 已移除 `SystemIdleClock` 和 `IdleDispatcher`；Windows 移植无需增加 `GetLastInputInfo` 或重建后台空闲绘制调度器。保留 `app/ui/harness_page.py` 的独立 `QWebEngineProfile`、会话 cookie 清空、仅允许当前 loopback origin、外链交系统浏览器，以及 `dispose()` 异步销毁顺序。`_working_directory()`（约 374–385 行）不能把安装后的 `Path.cwd()` 当默认项目：它在 Windows 快捷方式启动时可能是 `C:\Windows\System32` 或程序安装目录。优先用户设置的现存项目路径，否则用用户主目录；同步更改设置页“留空则使用当前工作目录”的提示。

### 阶段 D：确保 Windows 的 UI、资源和输入完整

| 文件 | 精确改动/检查 |
| --- | --- |
| `app/ui/theme.py` | `FONT_STACK`（约 86 行）现为 `.AppleSystemUIFont` / Helvetica Neue / PingFang SC。在 Windows 分支使用可解析的 Segoe UI + Microsoft YaHei UI/等价 CJK 字体，并用 `QFontMetrics` 看真实宽度；`QComboBox`/`QSpinBox`/复选框的 `image: url(...)` 需把 SVG 路径构造为经 Qt 编码的本地 URL（尤其是 `C:`、空格、中文路径），验证下拉箭头、上下箭头、勾号全部显示。保留 Fusion 和颜色、间距的设计意图。 |
| `app/ui/controls.py` | `build_flat_menu`、`RoundedComboBox`、`ConfirmationDialog`、`NoticeDialog`、`HoverTipWidget` 在 Windows 下实测 `WA_TranslucentBackground`、frameless、mask 的圆角和阴影。若透明窗口呈黑角/黑底、菜单被截或无法点中，只对 Windows 做 QSS/窗口 flag 的针对性修正；保留右键不取消消息选区、Escape 关闭、键盘导航。 |
| `app/ui/main_window.py::MainWindow`, `sidebar.py::ConversationItem` | 保留会话 ID → `StreamContext`/`ChatWorker` 的映射，不退回单一 `_worker` 或切换即 `cancel()`。Qt 工作线程只产生信号，主线程按所属会话更新上下文与存储；只有会话仍是当前可见页且气泡有效时才操作 Qt 控件。切换时先断开旧气泡引用再清空消息视图，返回时从已存历史和内存中的未完片段重建。完成/失败的后台回调必须归属原会话，清除对应侧栏旋转状态；无正文失败用 `role=error` 保存在历史中且不得传入后续 API 上下文。新对话不停止旧线程，同一会话生成中暂缓发送但保留预输入；删除会话只取消该会话，退出时取消并等待全部 Chat/标题线程。`ThinkingIndicator` 要在侧栏重建、浅深主题、高 DPI、选中/悬停和批量模式下可见且不留下运行的旧定时器。 |
| `app/ui/main_window.py`, `sidebar.py`, `settings_dialog.py` | `MainWindow.setMinimumSize(920,640)`、侧栏 280/56、输入卡最小 480、设置侧栏 280，以及欢迎页 composer 的 59% 悬浮定位，在 Windows 125%/150% 时可能超过实际逻辑工作区。当前欢迎页已按 composer 高度把 y 夹在可见范围；移植时仍须验证普通/展开两档、图片条同时出现及低逻辑分辨率。先通过 `QScreen.availableGeometry()` 决定初始窗口大小；为小逻辑视口建立紧凑布局：Chat 侧栏自动折叠到 56px rail（区分用户主动折叠状态），输入卡放弃固定 480 下限并在剩余宽度内缩放，设置侧栏/表单在窄宽度下收缩或换行、内容继续可滚。所有控件仍可达到，不能通过隐藏功能解决溢出。窗口移到不同 DPI 显示器时重新计算布局。Qt 6 使用设备独立像素；缩放策略只有在实测确需时才在创建 `QApplication` 前设置，不在发布脚本中强制 `QT_SCALE_FACTOR`。[Qt High DPI 说明](https://doc.qt.io/qt-6/highdpi.html)、[缩放取整策略](https://doc.qt.io/qt-6/qguiapplication.html)。 |
| `app/ui/main_window.py::ChatTextEdit`, `app/ui/icons.py`, `app/ui/theme.py` | 保留普通 84、展开 252 逻辑像素的编辑器目标高度与 `ScrollBarAsNeeded`；长段落、无空格长串和多行粘贴都必须在编辑器 viewport 内换行或滚动，不得撑高卡片或盖住工具栏。展开/收起图标由 `icons.py` 矢量绘制，按钮在编辑器右上角可点击、可键盘聚焦，深浅色与高 DPI 下可辨。编辑器文本变化只更新发送状态；点击展开/收起后以 16 ms 精确定时器和非线性缓动逐帧改变高度，外层 composer 与聊天 viewport 底部净空逐帧跟随，最终值分别精确回到 84/252。图片条变化后也同步布局。输入、删除、发送清空、新对话、历史切换后保持用户所选高度；若窗口逻辑高度不足，仍须让工具栏和提示可达。 |
| `app/ui/theme.py::MESSAGE_CONTENT_MAX_WIDTH`, `message_bubbles.py::UserBubble` | 当前输入框可见编辑区域、AI 正文区域、用户气泡正文在宽视口下共用 **820 逻辑像素**的最大排版宽度；输入卡外宽约 880，气泡外框加各自内边距。用户短句用实际显示字体的行宽计算自然宽度，不能以允许汉字断行的 `QTextDocument.idealWidth()` 估算，否则短消息也会换行。窄窗口按可用聊天栏缩小，不允许固定用户气泡宽度超出 viewport；在 Windows 中英混排、emoji、标点、链接、长无空格字符串和 100%–200% DPI 下验证。 |
| `app/ui/main_window.py::ChatTextEdit.insertFromMimeData` | 现在仅接收 `QImage`，Windows 截图工具/剪贴板可能给 `QPixmap` 或文件 URL。分别处理有效 `QImage`、`QPixmap.toImage()`、受支持的本地文件 URL；保留纯文本和 `Enter`/`Shift+Enter`/IME 预编辑行为。验证中文微软拼音的候选确认不会误发送。拖入文件仍只接受视觉模型，路径含空格/中文。 |
| `app/ui/image_strip.py`, `message_bubbles.py::OpenImageLabel` | `rounded_thumbnail` 当前按逻辑 `size×size` 画一次，再由高 DPI 屏放大；依实际 `devicePixelRatio` 生成足够像素、设置 pixmap DPR，保留抗锯齿圆角/内侧描边。验证 PNG/JPEG/GIF/WebP、8 张排列和原图打开。 |
| `app/ui/message_bubbles.py::_MathWebView` | 约 422 行把 `f"{KATEX_DIR.resolve()}/"` 传给 `QUrl.fromLocalFile`，Windows 混合反斜杠与斜杠，且可能有中文/空格。用 `QUrl.fromLocalFile` 从规范化**目录**构造末尾 `/` 的 base URL；核实 HTML 中 `katex.min.css`、`katex.min.js`、所有 WOFF2 相对 URL 的实际加载。保持 `qrc:///qtwebchannel/qwebchannel.js` 可用。分式行高、矩阵/分段、公式横滚、代码复制和长回答内部纵滚须在真实 WebEngine 上验，不能只看 HTML 字符串。 |
| `app/ui/harness_page.py` | `QWebEngineProfile` 的 storage/cache 指向可写的用户目录；设置页/消息外链使用 `QDesktopServices` 打开默认浏览器/图片查看器。检查 Windows 防火墙/代理情况下 loopback Web UI，设置更新后旧 profile/cookie 不复用；代码不能把认证 token 画到截图或发到外网。 |
| `main.py`, `app/ui/icons.py` | 保留 PNG 窗口图标及矢量绘制图标。为打包 EXE 设置 `.ico`；如 Windows 任务栏显示 Python/默认图标，给此应用设置稳定且独有的 AppUserModelID，并对源码/打包态分别测试任务栏分组、Alt+Tab、开始菜单快捷方式。现有 `icon()` 用 3 倍 DPR 绘制，应在 100%–200% 缩放下检查清晰度，包括输入框右上角的展开/收起图标。 |
| `app/api.py` | 约 414 与 553 行的 Macintosh User-Agent 仅用于搜索页面请求；改为应用自己的中性标识或合理的平台 UA，保持 DDG Lite 解析/Tavily/页面读取与引用测试。API SSE 核心不需要改平台语义。 |

### 阶段 D.1：流式跟随和动画的原生 Windows 方案

1. **以已显现内容决定可滚动高度。** `RichText` 的普通文本仍用完整 `QTextDocument` 保留 Markdown 格式，但原生控件高度只到最后一个已显现字符所在的行；恢复字符格式时按连续片段批量处理。公式/代码的 WebEngine 页面只报告最后一个已显现字符的底边；`style`、`script`、代码工具栏与 KaTeX 的隐藏语义节点不参与计数。用户看到的首屏不能提前占用完整回答的高度。Windows 上分别用纯文本、连续长段落、代码块、公式和混排实测；对比 `QScrollBar.maximum()` 与已显现正文高度，不能用“透明文字占满页面”模拟键入。Qt 的滚动范围受子控件大小与布局约束，见 [QScrollArea 文档](https://doc.qt.io/qt-6/qscrollarea.html)。
2. **统一人工滚动优先级。** `ChatView` 的 viewport、内嵌 `QTextBrowser`、WebEngine 转发的滚轮、触控板像素滚动，以及滚动条拖动都须暂停自动跟随。向上、向下都算用户介入；程序自己移动滚动条不得误判成用户操作。继续跟随按钮启动约 16 ms 一帧的加速—减速追赶，目标在回答继续生长时动态更新；按钮点击的同一帧不得直接把 `QScrollBar.value()` 设为 `maximum()`。追赶过程中再次滚轮操作立即取消追赶并保留用户指定视角。原生 Windows Precision Touchpad 要同时测 `pixelDelta`、`angleDelta` 和惯性滚动阶段，避免一次手势先暂停又被后续异步布局重新开启。
3. **让输入区和侧栏逐帧更新，但避免重复重排正文。** 输入框的 84/252 高度动画由精准 16 ms 定时器驱动非线性缓动，`ChatWorkspace` 每帧用卡片真实高度更新底部净空与继续跟随按钮位置；结束后再同步一次布局，防止最后 1–2 像素丢帧。侧栏 280/56 宽度过渡也用非线性约 60fps 目标，导航页只在过渡起点或终点切换，宽度变化期间暂停富文本气泡逐帧重排，结束时统一按新宽度换行。Windows 的计时器可能因消息循环、WebEngine 绘制和显示器刷新率合并帧；记录真实帧时间与屏幕视频，若仍卡顿，先剖析主线程排版和原生 WebEngine 合成，不能靠缩短动画或隐藏内容掩盖停顿。
4. **低高度和高 DPI 是新边界。** 252 像素展开档在最小 920×640 逻辑窗口占去更大空间；再叠加图片条、系统标题栏和 150%/200% 缩放，必须确认输入工具栏、发送/停止键、继续跟随键和最后一行正文均可见且可点击。欢迎页居中以实际卡片高度重新定位；展开输入框时收起欢迎页建议按钮，避免它们被高卡片盖住，收起后恢复。DPI 改变、窗口缩窄、侧栏动画中反复点击展开键、流式输出时切换深浅主题，都要验证卡片不盖住消息、滚动条不跳尾、侧栏不闪换页。
5. **统一输入和输出的最大行宽。** 宽视口下用 `MESSAGE_CONTENT_MAX_WIDTH == 820` 作为三处可见文字区的单一目标：输入编辑器 viewport、AI `RichText`、用户 `RichText` 都实际量到 820 逻辑像素；不能只把三个外框设成同宽，因为它们的内边距、图标与边框不同。用户短句须根据真实字体度量保持单行，长句到 820 才换行；窗口变窄后用户气泡也要缩到可用栏宽。Windows 字体替换、125%/150% DPI、文本插入图片、侧栏运动后重新测几何和断行。

数据层：`app/config.py` 的 `Path.home()/".deepseek_chat_gui"`、`DEEPSEEK_CHAT_GUI_HOME`、`app/storage.py` 的 `Path`/`shutil.copy2` 与 JSON `.replace()` 可以留存；在 Windows 做路径含中文/空格、只读目录、已有 `.tmp`、无权限和重启后持久化测试。当前媒体在 `conversations.json` 里是绝对路径：**Windows 新会话**照旧可用；如果要求把 Mac 旧数据直接拷到 Windows，需增加 `ConversationStore.resolve_media_path()` 及兼容旧记录的迁移：只映射位于旧 `media/<conversation-id>/` 下的文件到新 `MEDIA_DIR`，保留原 JSON 备份且每步校验，更新展示/重发图片用到的 `app/api.py`、`message_bubbles.py` 调用；不要对任意路径做字符串替换，也不要自动删除源数据。此跨设备数据迁移是独立验收场景。

### 阶段 E：Windows 打包、资源审计与发布准备

1. 从 `assets/app-icon.png` 在隔离构建环境生成并提交 `assets/app-icon.ico`（含 16/24/32/48/64/128/256 像素层，透明通道正确），检查 Explorer、任务栏、小图标与高 DPI。PNG、SVG、KaTeX 仍随包。
2. 改 `DeepSeekChat.spec`：根据 `sys.platform` 选择当前平台 `HARNESS_BUNDLE_DIR` 和目标 data 子目录；Windows `EXE(icon="assets/app-icon.ico", console=False)` + `COLLECT`，**不创建** `BUNDLE`，不传 macOS 的 `argv_emulation/codesign_identity/entitlements_file` 等参数；Mac 分支保留 `.icns`、`BUNDLE` 和 info plist。`Analysis` 保留 `assets` 与 PySide6 WebEngine 的收集，按实际构建补 `QtWebChannel`、Qt Network、SVG/图像插件的隐藏导入/二进制。不能把 PyInstaller 找不到 WebEngine 的警告当作可忽略项。
3. 增加 `scripts/package_windows.ps1`：校验 Windows x64、虚拟环境解释器、供应包完整性和 `app.__version__`；调用 `python -m PyInstaller --clean --noconfirm DeepSeekChat.spec`；检查 `dist/DeepSeek/DeepSeek.exe`、`_internal/assets/vendor/katex/`、`_internal/vendor/harness-win-x64/` 及 Qt WebEngine/插件。PyInstaller onedir 默认把数据放 `_internal`，现有 `sys._MEIPASS` 定位应继续工作。打包成功再 ZIP **整个** `dist/DeepSeek`，不是只拷 `DeepSeek.exe`。
4. Qt WebEngine 的 Windows 成品必须含 `QtWebEngineProcess.exe`、WebEngine DLL、`qtwebengine_resources*.pak`、`icudtl.dat`、`qtwebengine_locales` 等当前 Qt 版本实际需要的文件；`qwindows.dll`、SVG、JPEG、GIF、WebP 插件须跟随 Qt 插件搜索路径。不要硬编码某一版 wheel 的确切目录；用构建目录检查 + 干净机器实际加载确认。[Qt WebEngine 部署清单](https://doc.qt.io/qt-6/qtwebengine-deploying.html)。若干净机缺 Visual C++ 运行库，按 [Qt Windows 部署说明](https://doc.qt.io/qt-6/windows-deployment.html)采用官方 Microsoft Redistributable/安装器方案，并重新在干净机验收；不从开发机随意拷 DLL。
5. `README.md` 增加 Windows 10/11 x64 的源码、便携包、数据目录、测试/故障排查说明；`CHANGELOG.md`、`update.md` 只有在 Windows 验收完成后才把“待适配”改成真实下载项。新增 Windows 发布脚本或扩展发布流程，读取版本、验证 ZIP 与校验和、在既有 GitHub Release 上传正确命名的 Windows 资产，不能在此之前发布占位包。不要改掉 macOS 下载说明。

## 3. 必须新增且提交的测试

从已跟踪的 `tests/` 开始运行现有回归，再在 Windows 克隆内补充并提交平台测试。尤其要补 Windows 专有的进程与路径场景，并在真实桌面复验输入框动画、多会话并行和 WebEngine 渲染。测试 runner 要打印实际测试数量，并设零测试为失败。推荐 `python -m unittest discover -s tests -v`；`QT_QPA_PLATFORM=offscreen` 只用于不依赖真实屏幕合成的 Widget 回归，真实 WebEngine 画面和帧率必须在交互式 Windows 桌面检查。

| 测试组 | 最小必测场景与通过条件 |
| --- | --- |
| 纯逻辑/存储 | 配置缺省/迁移/保存重开，中文和空格路径、图片拷贝/删除、绝对媒体路径兼容；请求体、视觉 data URL、标题上下文、SSE 分块、思考/正文、停止、DDG/Tavily/引用及坏响应。网络用本地 mock，不依赖实际密钥。 |
| 平台路径 | Windows `HARNESS_BUNDLE_DIR`、`node.exe`、CLI 探测；没有系统 Node 时仍正常；只有 `npx.cmd` 时不将其误作普通 exe；Mac 候选路径不进入 Windows 决策；QSS SVG、KaTeX base URL 在 `C:\Work Space\中文\...` 下有效。 |
| Harness 生命周期 | 以受控测试 Node 子进程模拟 web URL/token 和衍生子进程：ready、退出、超时、端口重试、重复启动/停止、设置变更、关闭应用。检查 Job Object/PID 归属、端口释放，别的 Node/监听端口不受影响。然后用真实内置 Harness 执行项目/终端/工具/审批的人工集成测试。 |
| Harness 预热与页面时序 | 预热开启且当前在 Chat 时，`warm()` 只调用服务启动；人为发出启动中、ready、failed 信号，再最小化/还原，断言 `HarnessSurface._web_view` 与 `_profile` 仍为空，`show_web`/`show_status` 未更新隐藏页，Chat 当前页不变。切到 Harness 后才调用一次 `show_web`；就绪信号在已选页且窗口最小化时先置 `_surface_pending`，还原后只绘制一次；在设置页选择同一个 Harness 模式，应先恢复 `page_stack` 再绘制。运行中改 API Key/项目设置后应停止旧实例并仅在下次进入时展示新状态。用真实 Windows 桌面补测可见闪烁/白屏。 |
| Qt Widget UI | `QTest` 验模式切换、侧栏折叠、欢迎/聊天输入位置、设置三页与验证、菜单/确认框、拖入/粘贴、剪贴板、IME、主题。输入框专测普通 84/展开 252 逻辑像素与 16 ms 非线性过渡：连续键入、无空格长串、多行粘贴、滚至首尾、逐步删除、全清、发送、新对话和历史切换后两档高度稳定；外层 composer 与消息 viewport 净空同步，展开按钮可点击且图标切换，最小窗口和高 DPI 下无溢出。布局断言用实际 `QFontMetrics`/可见区域，不只比固定坐标。 |
| 消息行宽 | 1280×820 及更宽窗口量取输入编辑器、AI 正文、用户正文的实际 viewport，最大宽度均为 820 逻辑像素；短中文/英文/混合消息发送后仍是一行，达到最大宽度后才换行。最小窗口与侧栏展开/收起途中不得水平越界；不同字体和 DPI 下用行布局数量与屏幕截图核对。 |
| 流式视角与动画 | 用长答案的可控 SSE 在 16 ms、50 ms 和突发大块三种节奏输入：完整文档可很长，但在键入前 10% 时正文控件高度和 `QScrollBar.maximum()` 只对应已显现部分。滚轮上下、触控板、滚动条拖动后保持用户视角；继续跟随首帧不跳底，中途再次干预可中断，完成后到达动态最下方。侧栏与输入框过渡记录中间帧、最终 280/56 与 84/252 尺寸、点击连发后的终态；加入代码/公式 WebEngine 后重复，确认外层滚轮转发与可见高度一致。 |
| Chat 并行与草稿 | 用两个可控 SSE mock 同时打开 A/B：A 生成中可输入草稿和图片、新建 B 并发生成；A/B 的旋转图标同时持续，来回切换时不发停止请求且各自内容、未发送文字、光标、图片分别恢复。B 在 A 页面完成后仅写 B 的历史并停止 B 图标；A 随后完成，回复不串页；同一会话生成时 Enter 不发送也不清空草稿，结束后可发送。另测单项/批量删除仅取消目标线程、错误与部分输出、标题线程、主题切换和退出时全部线程收束。Windows 用真机重复并发和快速切换，观察 Qt 消息循环及侧栏动画没有明显停顿。 |
| 真实 WebEngine UI | KaTeX JS/CSS/woff2 成功，公式 DOM、代码块复制、外链路由、长式横滚、长回答尾部可达、反复清空/重建不崩溃；Harness Web UI 的 `loadFinished(true)`、body 非空、同源导航、cookie 清理和重启。 |

可在 PowerShell 用仓库内虚拟环境执行：

```powershell
$env:DEEPSEEK_CHAT_GUI_HOME = Join-Path (Get-Location) '.tmp/windows-port/test-data'
./.venv/Scripts/python.exe -m unittest discover -s tests -v
./.venv/Scripts/python.exe -m ruff check app main.py tests
```

若用 offscreen，单独一轮设置 `$env:QT_QPA_PLATFORM = 'offscreen'`；真实显示轮次必须 `Remove-Item Env:QT_QPA_PLATFORM`，在用户桌面窗口可见状态运行。测试结束关闭所启动的 `DeepSeek.exe`/Node 进程，仅清理测试自己建立的 `test-data` 和阶段目录。

### 持续集成与交接流水线

新增 `.github/workflows/windows.yml`（或项目约定的等价 CI），按依赖关系安排：检出固定提交与子模块状态 → Windows x64 Python 3.11 隔离安装 → `ruff` 和零测试即失败的单元/Widget 测试 → 在 Windows 上依据已提交锁文件供应 Harness 并审计原生包 → PyInstaller onedir → 静态检查 EXE、Node、Qt WebEngine、KaTeX、图标、许可证及 ZIP SHA-256 → 上传构建产物与不含密钥的测试报告。测试 runner 须显式检查实际运行数量 `> 0`；日志、CI artifact 和截图不得含 API Key、token。若增加 macOS CI，用现有脚本做回归，保持两平台分支独立。CI 的无头 Widget 测试不能代替可见桌面与 Chromium 子视图测试：每个候选 ZIP 还必须在真实 Windows 桌面完成第 4、5 节矩阵并附构建号、截图、差异清单、复验记录，全部通过后才发布。依赖/锁文件或 UI 代码变更后重新跑对应阶段，不能沿用旧验收结果。

## 4. 视觉校验流程：截图 + 几何 + 真实交互

### 固定场景与采集

1. 先在隔离数据目录准备**确定性**假数据、假 API 响应；截图不使用真实 Key、Harness token、个人项目路径。等待窗口 show、Qt 事件队列、WebEngine `loadFinished`、`document.fonts.ready`、流式动画进入指定状态后才拍。窗口使用物理屏幕截图或验证可包含 Chromium 子视图的抓取方法；若 `QWidget.grab()` 得到空白 WebEngine，改用 OS 屏幕抓取，不能把空白截图判为通过。
2. 每组至少保存这些状态：欢迎/首次设置；设置基础、个性化、运行环境（含下拉框和错误提示）；Chat 文本回答、流式思考/已折叠、联网搜索引用；**普通 84 与展开 252 输入框各自输入超长文本、滚动到末尾、删除后恢复空白，以及欢迎页/聊天页的高度和动画中间帧**；**长回答首屏键入、滚轮暂停、继续跟随追赶、再次滚轮中断，以及含代码/公式时的相同序列**；**A/B 两会话同时执行的侧栏旋转指示、A 输出中已键入下一轮草稿、切到 B 后仍在生成及切回后的草稿和片段**；代码块复制按钮、复杂 KaTeX 与超长公式；图片待发送/发送后、8 图上限；侧栏展开/收起帧序列与批量删除确认；深色主题同组关键页；**Chat 可见且 Harness 服务已预热就绪、首次切换 Harness 的加载过程、已就绪/重启失败与工作区、最小化后还原**。仓库 `assets/screenshots/*.png` 给出 1360×900 的结构参照，实际 Windows 截图另存到任务专属验证目录，记录 Qt/Python/Windows/屏幕 DPI/窗口逻辑尺寸。
3. 覆盖窗口逻辑尺寸 **1360×900、1280×820、最小支持尺寸**；显示缩放 **100%、125%、150%、200%**（200% 可在高分屏），浅/深主题；至少一次双屏不同 DPI 之间拖动、最大化/还原、窗口缩窄、RDP/重连或分辨率改变。单屏物理工作区不够时记录实际逻辑 `availableGeometry()`，使用另一显示器或 VM，不能靠截掉窗口下部取得“正常”截图。
4. 运行自动几何扫描：遍历所有**可见且应交互**控件，断言有效 `geometry`、中心点落在相应可见父窗口/滚动 viewport 中；标签用 `QFontMetrics.boundingRect` 或可用高度检出截字；组合框弹层、右键菜单、通知、确认框落在 `screen.availableGeometry()`；滚动区底部控件能通过滚动到达。对 WebEngine 注入只读 JS，检查 `document.readyState`、`typeof katex`、`document.fonts.ready`、公式/代码 DOM 非空、`scrollWidth/clientWidth`、`scrollHeight/clientHeight` 和最后节点可达。
5. 与 macOS 参考图做**结构性**对照：顶部 Work Type 58 逻辑像素、Chat 侧栏展开约 280/收起 56、右顶栏 58、输入卡居中且不超过设计最大宽度、欢迎页/消息页均留合理可见边距；品牌、图标、按钮、状态、公式、底部 composer 全出现。跨 OS 字体字形与抗锯齿不同，不用整图精确像素相等作门槛。可以对稳定区域做图像差异热图/边框叠加，动态时间、动画、光标、真实 Harness 随版本变的内容单独遮罩；每个差异仍需人工判断。禁止用改图、隐藏控件或大幅放宽容差让失败“变绿”。

### 必查交互细节

- 中文微软拼音输入、候选框、Enter 确认、Shift+Enter 换行；粘贴截图、Explorer 文件复制粘贴、拖放；图片选择对话框与原图打开。
- 输入框两档高度的展开/收起按钮、鼠标滚轮/滚动条/键盘滚动、长文本尾部可见性；反复键入和删除后卡片不因文本长度跳变，发送清空或新对话后所选档位保持。图片条出现与消失后再重复，检查底部工具栏和消息列表不被遮挡。
- A 生成期间键入 A 的下一轮内容、粘贴图片，切到 B 编辑另一份草稿并发送；再访问 A，核验文字、光标、图片和已流出的正文各归原会话。A/B 同时运行时检查侧栏两处旋转图标持续转动、悬停菜单可用；完成、取消、失败、删除时只清除对应图标。当前 A 未完成时按 Enter 不能覆盖正在执行的 A，也不能丢失预输入。切换 Chat/Harness 或进入设置再返回，两个 Chat 请求仍正常结束。
- 所有下拉箭头、勾号、SVG Logo、任务栏图标、深浅色文字/背景/选中态；菜单圆角、无黑角、焦点键盘可用、弹层不跑出屏幕。
- 鼠标拖选普通文字/公式区域、`I` 形光标、右键保留选区、复制/全选/代码复制；点击空白取消选区。链接由默认浏览器打开。
- 长文本、长代码、表格、矩阵/分式/分段公式的宽高；长公式只在自身横滚，长回答尾部可达；输出首屏不预留未显现正文高度，默认视角随已显现文字逐步下移；触控板/滚轮向上或向下介入后立即暂停，点击“回到最新消息”时逐帧加速追到最新位置，追赶途中再次滚轮介入须立即中断。
- Harness 服务在 Chat 显示期间预热到 ready/failed、窗口退到后台与最小化还原、首次切换/再次切换、设置页回到同一 Harness 模式、配置更新后重启；记录连续屏幕画面或帧序列以捕捉单帧整窗刷新/缩小后弹回，检查 Chat 在预热期间不变、WebEngine 仅在选中 Harness 后创建、加载后无白屏。首次切换需记录点击到加载状态、页面首帧的时间和最长事件循环停顿，确保新增的前台建页成本不会让窗口长期无响应。继续验官方 Web UI 的项目选择/文件/终端/工具/审批；不把服务启动成功但页面空白当通过。

## 5. 成品验收与故障定位

1. 在当前 Windows 开发机运行 `scripts/package_windows.ps1`，核验 onedir 完整性和压缩包 SHA-256；从 `dist/DeepSeek/DeepSeek.exe` **直接启动**做一轮上述功能与视觉检查。检查 `.spec` 打包后的资源定位，而不是让源码目录恰好补上缺失资源。
2. 在**干净 Windows 10/11 x64 VM 或新用户环境**中，不预装 Python、Node、npm、不添加本仓库到 PATH；将 ZIP 解压到含空格与中文的目录，启动 `DeepSeek.exe`。用隔离测试 Key/本地 mock 完成 Chat 与 Harness；重启后设置、历史、图片可读取；应用退出后仅自身 Node/子进程消失。检查系统任务管理器、`Get-NetTCPConnection`、应用日志，不读取/干扰别的服务。
3. 重复一次安装器/便携包在标准权限用户下运行；不要以管理员身份启动来解决拖放/写权限问题。Windows Defender/SmartScreen 的签名或信誉提示要如实记录；签名是发布可信度问题，不能以关闭防护或要求管理员权限替代程序修复。
4. 失败按层定位：**无法启动**→ `.spec`/PySide6 DLL/qwindows/VC++；**Chat 正常、公式/代码空白**→ `QtWebEngineProcess`、pak、QWebChannel、KaTeX base URL/字体；**Harness 状态失败**→ Node/CLI/native npm 树、工作目录、环境、端口/token/Job；**只在高 DPI 截断**→ 可用逻辑工作区、字体度量、固定尺寸与 `QScreen` 重布局；**退出残留**→ Job/PID 归属与停止时序。软件渲染/GPU 关闭参数仅用于诊断，定位后再决定兼容实现，不能作为默认方式掩盖缺资源。

### 最终放行条件

- Windows x64 源码运行、自动测试、真实桌面 UI 测试、onedir、干净机 ZIP 五关全绿；测试数量非零，未跳过真实 WebEngine/Harness 验收。
- 两会话以上的并行输出、后台继续生成、按会话恢复草稿及图片、侧栏运行标记、后台完成/失败/删除与退出收束均通过自动测试和真实桌面操作；无跨会话回复或草稿串写。
- 每项功能合同有测试或带时间/构建号的人工记录，视觉矩阵有截图、差异清单与复验结果；没有遮挡、截断、空白、无法点击/复制/滚动、丢图标或不合理闪烁。
- Mac 分支的 `.spec`、供应/DMG 脚本保留，能在 macOS CI/真机回归；Windows 分支不声称已通过未经执行的 macOS 测试。
- 运行包里没有 Darwin 原生二进制冒充 Windows 依赖；无全局 Node/Python 前提；没有将 API Key/token 打进发布包、日志或截图。发布物名称/架构/版本/校验和与实际内容一致。
- 最终交接列明修改文件、执行命令、测试数量与结果、实际 Win 版本/DPI、ZIP 路径/哈希、任何未解决的外部 Harness/账号限制。测试启动的后台进程全部停止，确认归属的阶段与临时目录清理；不删用户原有文件或未知忽略文件。

## 6. 实施时参考的官方资料

- [本项目 `main` 源码](https://github.com/quzhenghao/deepseek-chat-gui/tree/main)
- [DeepSeek Harness 官方仓库与 Web 启动命令](https://github.com/deepseek-ai/deepseek-harness)
- [Node.js v22.19.0 Windows ZIP 与 SHA256](https://nodejs.org/download/release/v22.19.0/)
- [PyInstaller spec 与 Windows 构建说明](https://pyinstaller.org/en/stable/spec-files.html)
- [Qt `QProcess` Windows 可执行文件/命令行规则](https://doc.qt.io/qt-6/qprocess.html)
- [Qt WebEngine 部署资源](https://doc.qt.io/qt-6/qtwebengine-deploying.html)
- [Qt High DPI](https://doc.qt.io/qt-6/highdpi.html)
- [Microsoft Windows Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)
