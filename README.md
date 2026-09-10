# DeepSeek 本地客户端

<p align="center">
  <img src="assets/app-icon.png" width="120" alt="DeepSeek 图标">
</p>

一个基于 Python 与 PySide6 的轻量桌面客户端。它直接调用你自己的 DeepSeek API，支持官方 V4.1 Flash、流式输出、真实对应的思考强度、图片输入、本地对话历史，以及官方 DeepSeek Harness 开发者预览版。

本项目是非官方客户端，与 DeepSeek 官方无隶属或背书关系。

<p align="center">
  <a href="https://github.com/quzhenghao/deepseek-chat-gui/releases"><img src="https://img.shields.io/badge/下载-v1.0.0-171717?logo=github" alt="下载"></a>
  <img src="https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/PySide6-6.11-41CD52" alt="PySide6">
  <img src="https://img.shields.io/badge/macOS-Apple%20Silicon-black" alt="macOS">
  <img src="https://img.shields.io/badge/Windows-待适配-lightgrey" alt="Windows 待适配">
</p>

## 核心优势

- **一个应用，两种工作方式**：在同一个 `DeepSeek` 桌面窗口中使用本地 Chat 和官方 DeepSeek Harness，顶部一键切换，保留统一的品牌、设置和使用习惯。
- **本地优先，数据边界清晰**：Chat 对话、图片和设置保存在本机；Harness 通过本机 loopback 嵌入，API 密钥仅以进程环境传递给官方适配器。
- **安装即用**：macOS 成品 DMG 已内置 Node.js 与固定版本 Harness 运行包，用户无需预装 Node.js、npm、npx 或手工配置环境，安装后即可开始配置 API。
- **从第一次使用就有引导**：没有 API Key 时自动进入设置页，按“填写密钥 → 测试连接 → 保存设置”的路径完成初始化；运行环境页面提供依赖检测、配置目录、升级入口和 Harness 预热开关。
- **更适合长对话**：流式输出默认跟随最新回答；用户向上阅读会自动暂停，点击圆形向下箭头即可回到底部并继续跟随，不打断阅读。
- **兼顾开发和日常问答**：保留 Markdown、代码复制、离线 KaTeX 数学公式、图片输入、深度思考、会话历史和自定义系统提示词，同时把 Harness 的项目、工具、审批和轨迹能力带进同一个工作流。

## 功能

- 使用自己的 API 密钥直接请求 `https://api.deepseek.com`
- 当前官方模型目录使用 `deepseek-flash`（界面名称 DeepSeek V4.1 Flash）
- 深度思考可随时开关；开启时强度为 `Low`、`High`、`Max`，关闭时发送官方 `thinking.type=disabled`
- 思考阶段显示动态小图标，思考内容默认折叠；正文到达后才显示答案
- SSE 流式输出，生成过程中可随时停止
- 支持 Markdown、代码块、表格、列表、引用、链接与本地矢量 LaTeX 数学公式
- 代码块带语言标签、等宽排版、横向滚动和一键复制；行内代码使用独立的代码样式
- 视觉模型支持选择、拖入或粘贴 PNG、JPEG、GIF、WebP 图片
- 对话、设置和图片仅保存在本机
- 支持浅色与深色主题
- 支持为每个新对话自动注入自定义系统提示词
- 新建会话时输入框居中；进入对话后输入框下沉到底部，模型流式输出会自动跟随最新位置
- 向上滚动会暂停自动跟随，并在输入框上方显示圆形向下箭头，可一键回到最新输出并恢复跟随
- 每轮回答完成后基于全部对话上下文自动生成精短历史标题
- 顶部 `Work Type` 栏用两个圆角按钮在 Chat 与官方 DeepSeek Harness 之间切换；原生 Chat 与设置侧栏保持浅灰底、黑白品牌，Harness 页面由官方 Web UI 管理项目、会话、工具、审批和轨迹
- 全部操作图标使用矢量绘制，高分屏下保持清晰
- macOS 运行时使用独立 Dock 图标，并提供高分辨率 PNG、SVG 和 ICNS 资源

## 当前模型与官方接口

| 界面名称 | API 模型 ID | 图片输入 | 上下文窗口 | 思考强度 |
| --- | --- | --- | --- | --- |
| DeepSeek V4.1 Flash | `deepseek-flash` | 是 | 1,000,000 | `off`、`low`、`high`、`max` |

本版本在 2026-09-10 重新核验了官方 /models、Chat Completions、Thinking Mode 和 Vision 路径。模型和参数以 [DeepSeek API 文档](https://api-docs.deepseek.com/)、[Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode/)、[Vision](https://api-docs.deepseek.com/guides/vision/) 与账号实际返回结果为准；客户端不会把已经不在当前目录中的旧模型继续作为内置选项。

客户端把界面选择映射为 API 的 `model=deepseek-flash`。思考开启时发送 `thinking: {"type":"enabled"}` 和 `reasoning_effort`（`low`、`high`、`max`）；思考关闭时发送 `thinking: {"type":"disabled"}`，并只发送标准模式的 `temperature`。这与官方 Thinking Mode 的字段和约束保持一致，避免在思考模式中继续传入不适用的温度参数。

在设置中点击“测试连接”时，客户端会读取账号的 GET /models 结果，并将当前官方 Flash 路由整理为界面模型；内置默认值始终是当前 Flash 路由。旧配置会自动迁移到 `deepseek-flash`；未知的未来模型 ID 会保留为可手动使用的模型，能力以端点实际响应为准。

官方适配器当前公开 `off`、`low`、`high`、`max` 四种推理状态；本地 Chat 界面用“深度思考”开关表达 `off`，用强度下拉框表达其余三档。最大输出设置上限与官方 Harness 适配器保持一致，为 256,000 token；留空则使用模型默认值。

## DeepSeek Harness 模式

窗口顶部的 `Work Type:` 栏提供两个圆角按钮（`Chat` / `Harness`），字体与主界面统一并略作放大加粗；当前模式使用高对比的黑白状态填充表示，不再使用下拉控件或鲸鱼图标。选择 `Harness` 后，官方 Web UI 从顶栏下方完整嵌入，官方项目/工作区侧栏不会被外层 UI 覆盖；选择项目后即可使用官方 Harness 的会话、工具、审批、文件和轨迹能力，顶栏始终可以把用户带回 Chat。Chat 与设置页则保留浅灰色侧栏、黑白 DeepSeek 标识和统一的中性控件样式。

集成使用官方 npm 包 `@deepseek-ai/dsh@0.1.5-rc.1`，启动命令等价于：

```bash
npx --yes --prefer-offline @deepseek-ai/dsh@0.1.5-rc.1 web --no-open --port <本地端口>
```

完整 macOS 安装包会在构建时把 Node.js `22.19.0` 与固定版本的官方 Harness 运行包一并放进 `.app`，安装后不要求用户另行安装 Node.js、npm 或 npx。开发环境运行源码时，如果项目旁边没有内置运行包，客户端才会回退到系统 `npx`，并在界面中明确显示当前环境状态；缺少依赖时可从设置 → 运行环境查看更新入口。API 密钥只通过 `DEEPSEEK_API_KEY` 进程环境传给官方适配器，不写入 Harness 配置文件。客户端首次启动 Harness 时在 `~/.deepseek_chat_gui/harness/settings.yaml` 生成一份可编辑的适配器设置，默认模型为 `deepseek-flash`，并设置 `reasoningEffort: high`、`thinking: enabled`、图片输入和 1,000,000 上下文窗口；已有设置不会被覆盖。默认情况下，Chat 启动后会静默预热 Harness，用户也可以在设置 → 运行环境中关闭该行为。

Harness 的项目目录可在官方页面中管理；客户端会优先使用配置中的有效项目路径，若未配置则以当前工作目录启动。Harness 是官方开发者预览版，模型生成的命令可能改变项目文件或执行本机工具，请只打开必要的项目目录并认真处理审批提示。集成代码使用 loopback 认证 URL，并限制内嵌页面只访问该本地服务；外部文档链接交给系统浏览器打开。

官方入口：[DeepSeek Harness](https://www.deepseek.com/harness/en/)、[官方仓库](https://github.com/deepseek-ai/deepseek-harness)、[官方文档](https://deepseek-harness.github.io/deepseek-harness/)。

## 下载与安装

从 [GitHub Releases](https://github.com/quzhenghao/deepseek-chat-gui/releases) 下载对应版本的成品安装包。Release 资产区只放可直接安装的最终安装包，不上传源码压缩包、构建缓存或开发依赖。

| 平台 | 0.1.0（历史版） | 1.0.0 | 当前状态 |
| --- | --- | --- | --- |
| macOS Apple Silicon | [下载历史版 DMG](https://github.com/quzhenghao/deepseek-chat-gui/releases/download/v0.1/DeepSeek-Chat-0.1.0-macos-arm64.dmg) | [下载 DMG](https://github.com/quzhenghao/deepseek-chat-gui/releases/download/v1.0.0/DeepSeek-1.0.0-macos-arm64.dmg) | 可用 |
| Windows | — | — | 待适配 |

当前推荐使用 `1.0.0`。打开 DMG 后将 `DeepSeek` 拖入“应用程序”即可完成安装。

> 首次打开提示（macOS Gatekeeper）：当前安装包使用本地 ad-hoc 签名，尚未接入 Apple Developer ID 签名与 notarization。macOS 可能提示“无法验证开发者”，或显示“Apple 无法检查‘DeepSeek’是否包含恶意软件”，并阻止应用直接打开。这是未经过 Apple 公证的下载包常见的系统安全提示，并不等同于项目主动请求关闭系统防护。请确认安装包来自本项目的 [GitHub Releases](https://github.com/quzhenghao/deepseek-chat-gui/releases) 后，先尝试打开一次；然后进入“系统设置 → 隐私与安全性”，向下滚动到“安全性”区域，在对应提示旁点击“仍要打开”（英文系统为 `Open Anyway`），按系统提示确认即可正常运行。Apple 说明该按钮通常会在首次尝试打开后的约一小时内出现，详见 [Apple：安全地打开 Mac App](https://support.apple.com/zh-cn/102445)。

## 使用现有 Conda 环境运行

项目已按 `deepseek-chat` 环境验证。进入项目目录后执行：

```bash
conda activate deepseek-chat
python -m pip install -r requirements.txt
python main.py
```

打包和发布还需要开发依赖（PyInstaller、ruff）：

```bash
python -m pip install -r requirements-dev.txt
```

如果在 PyCharm、IntelliJ IDEA 或其他 IDE 中运行，选择下面的解释器即可：

```text
/opt/anaconda3/envs/deepseek-chat/bin/python
```

最低依赖见 `requirements.txt`：

- PySide6 6.8–6.x
- requests 2.x
- markdown-it-py 3.x–4.x
- Qt WebEngine（随 PySide6 提供，用于本地矢量公式排版）

## 首次设置

首次启动会自动进入设置页，并在“基础配置”中显示配置引导。

1. 在“API 密钥”中填写 DeepSeek API Key。
2. 保持默认 API 地址 `https://api.deepseek.com`。
3. 点击“测试连接”。连接成功后，客户端会同步该账号当前可用的模型 ID。
4. 在“基础配置”中选择默认模型、思考模式、强度和主题。
5. 如有需要，在“个性化”中填写系统提示词。它会作为隐藏的系统消息加入此后每个新对话，并位于首条用户消息之前。
6. 保存设置并开始对话。

“设置 → 运行环境”可以重新检测 Node.js / npx、打开本地配置目录、查看 Node.js 更新入口、打开 Harness 官方文档和仓库，并设置 Harness 是否在 Chat 启动后后台预热。

API 密钥会以明文保存在本机配置文件中，方便下次启动自动加载。不要把配置目录提交到版本库，也不要在共享电脑上保存正式密钥。

## 对话操作

| 操作 | 方式 |
| --- | --- |
| 发送消息 | `Enter` |
| 输入换行 | `Shift + Enter` |
| 停止生成 | 点击输入框右下角的停止按钮 |
| 开关深度思考 | 点击输入框下方“深度思考”按钮 |
| 调整思考强度 | 使用深度思考按钮右侧下拉框 |
| 添加图片 | 视觉模型下点击附件按钮、拖入图片或粘贴图片 |
| 展开思考过程 | 点击“已完成深度思考” |
| 复制回答 | 点击回答下方复制按钮，或右键消息 |
| 管理对话 | 悬停历史项后打开更多菜单，可重命名或删除 |
| 批量删除 | 点击“最近对话”右侧选择图标 |

单张内联图片最大 32 MiB；客户端每条消息最多添加 8 张图片。发送时图片会复制到该对话的本地媒体目录，因此原始文件移动后仍可在历史中查看。

模型回答中的行内公式支持 `$...$` 和 `\(...\)`，独立公式支持 `$$...$$` 和 `\[...\]`，也能识别模型直接输出的 `align`、`equation` 等显示环境。公式由随应用打包的 KaTeX 在本机完成 DOM 与数学字体排版，不访问在线服务，也不经过 PNG、截图或低分辨率中间位图；行内分式会自然撑开行高，矩阵、分段函数和多行对齐会保留二维结构。超出消息宽度的独立公式只在自身区域提供横向滚动和溢出提示，不会撑宽或裁切整条回答。Markdown 行内代码和代码块中的公式分隔符会保持原样。

每轮回答完成后，客户端会额外调用一次当前对话所选模型，把全部可见的用户与助手文本总结为适合侧边栏显示的短标题；图片只以数量标记参与标题请求，不会为生成标题而重复上传。标题请求在后台运行，不会阻塞下一轮输入；它也会产生少量 API token 用量。

## 本地数据

默认数据目录为 `~/.deepseek_chat_gui/`：

```text
~/.deepseek_chat_gui/
├── config.json          API、模型、生成、主题与个性化设置
├── conversations.json   对话和消息记录
├── media/               已发送的本地图片副本
└── harness/              官方 Harness 设置、缓存与浏览器数据
```

删除一个对话时，其消息记录与对应媒体目录会一起删除。程序写入 JSON 时使用临时文件原子替换，降低异常退出造成历史损坏的风险。

可使用环境变量 `DEEPSEEK_CHAT_GUI_HOME` 临时指定独立数据目录，适合测试：

```bash
DEEPSEEK_CHAT_GUI_HOME=/path/to/test-data python main.py
```

## 测试

自动化测试不访问真实 API：

```bash
conda activate deepseek-chat
QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v
```

测试覆盖请求参数、流式与非流式响应解析、图片消息、模型目录迁移、数学公式边界解析、矩阵/分段/多行公式、矢量 DOM 输出、代码块复制、窄屏公式溢出、全上下文标题生成、Harness 配置初始化、产品模式切换、配置迁移、对话存储和思考折叠状态。

## 项目结构

```text
deepseek-chat-gui/
├── main.py
├── requirements.txt
├── requirements-dev.txt
├── DeepSeekChat.spec
├── scripts/
│   ├── package_macos.sh
│   ├── vendor_harness.sh  构建时下载并内置 Node.js 与 Harness
│   └── release_github.sh
├── assets/
│   ├── app-icon.svg
│   ├── app-icon.png
│   ├── app-icon.icns
│   ├── deepseek-mark.svg
│   ├── chevron-down.svg
│   ├── chevron-up.svg
│   ├── check-white.svg
│   └── vendor/katex/      本地 KaTeX 脚本、样式与 WOFF2 数学字体
├── app/
│   ├── api.py
│   ├── config.py
│   ├── harness.py
│   ├── markdown.py
│   ├── storage.py
│   ├── worker.py
│   └── ui/
│       ├── controls.py
│       ├── icons.py
│       ├── image_strip.py
│       ├── harness_page.py
│       ├── main_window.py
│       ├── message_bubbles.py
│       ├── settings_dialog.py
│       ├── sidebar.py
│       └── theme.py
└── tests/
```

## 打包 macOS 安装包

在 macOS（Apple Silicon）上执行：

```bash
conda activate deepseek-chat
python -m pip install -r requirements-dev.txt
./scripts/package_macos.sh
```

脚本先用 PyInstaller 生成 `dist/DeepSeek.app`，再用系统自带的
`hdiutil` 打包为 `release/DeepSeek-<版本>-macos-arm64.dmg`。镜像内包含
应用本体和指向 `/Applications` 的快捷方式，打开后把应用拖入
“应用程序”即可完成安装。

打包前脚本会执行 `scripts/vendor_harness.sh`：它下载固定版本的 Node.js
运行时，并在项目本地安装固定版本的 `@deepseek-ai/dsh` 及其依赖，随后由
PyInstaller 将 `vendor/harness/` 收进 `.app`。该目录是构建产物，已加入
`.gitignore`，不会被提交到源码仓库；在无网络的构建机上，如果本地已经有
完整的 `vendor/harness/` 可以离线复用。仅想调试原生 Chat 而跳过此步骤时，
可设置 `DEEPSEEK_SKIP_HARNESS_BUNDLE=1`，但生成的安装包在没有系统 Node.js
时将无法启动 Harness。

构建产物是未经过 Apple 公证（notarization）的本地 ad-hoc 签名包。首次打开时，
macOS 可能显示“无法验证开发者”，或显示“Apple 无法检查‘DeepSeek’是否包含恶意软件”，
随后阻止应用启动。请确认 DMG 来自本项目的 GitHub Releases，先尝试打开一次，
再进入“系统设置 → 隐私与安全性”，向下滚动到“安全性”区域，在对应提示旁点击
“仍要打开”（英文系统为 `Open Anyway`），并按提示确认。详见 [Apple 官方说明](https://support.apple.com/zh-cn/102445)。
需要正式分发时，可在此基础上接入 Apple Developer ID 签名与公证。

## 发布到 GitHub

源码发布和成品发布分开处理：先推送源码，再通过脚本创建只包含最终 DMG 的 Release。

```bash
git add .
git commit -m "Release DeepSeek 1.0.0"
git push origin main
```

构建并发布当前版本：

```bash
./scripts/package_macos.sh
./scripts/release_github.sh
```

脚本会读取 `app/__init__.py` 中的版本号，使用 `CHANGELOG.md` 作为 Release 说明，创建 `v<版本>` 标签并上传对应架构的 DMG。Windows 版本暂不上传，待适配位置会继续保留在 README 与 Release 说明中。

## 常见问题

### 点击发送后提示模型不存在

在设置中点击“测试连接”重新同步模型列表。自定义网关需要填写它实际支持的模型 ID，而不是界面展示名。

### 图片按钮不可用

当前内置的 DeepSeek V4.1 Flash 支持图片输入；如果附件按钮仍不可用，请确认顶部模型为 `deepseek-flash`，并检查图片格式与 32 MiB 大小限制。

### macOS Dock 启动瞬间短暂出现 Python 图标

直接执行脚本时，系统可能在 Qt 窗口创建前短暂显示 Python 图标；窗口建立后会切换为项目图标。若打包为 `.app`，使用 `assets/app-icon.icns` 写入应用包的 `CFBundleIconFile` 可让启动全程显示正确图标。
