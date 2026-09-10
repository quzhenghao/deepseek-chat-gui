# DeepSeek 1.0.0 更新说明

## 这份说明的对比口径

- 对比时间：2026-09-10（Asia/Shanghai）
- GitHub 线上基线：[main 分支](https://github.com/quzhenghao/deepseek-chat-gui/tree/main)
- 线上提交：[78399aa `Prepare v0.1 release`](https://github.com/quzhenghao/deepseek-chat-gui/commit/78399aa188e264396deac9e69edd59b82d753df9)，提交时间为 2026-09-09 22:37（+08:00）
- 线上标签：[v0.1](https://github.com/quzhenghao/deepseek-chat-gui/tree/v0.1) 当前与上述提交相同
- 本地状态：本次升级整理为 `1.0.0` 发布版本，源码与更新日志同步提交到 GitHub
- 差异规模：20 个已有文件发生修改，功能实现新增 `app/harness.py`、`app/ui/harness_page.py` 和 `scripts/vendor_harness.sh` 3 个文件；本说明另新增 `update.md`，并新增 `CHANGELOG.md`。构建目录、安装包和临时截图不计入源码差异

线上 `v0.1` 已具备基础的 DeepSeek API 对话、流式输出、深度思考、图片输入、本地历史、Markdown/公式渲染、主题切换和 macOS 打包能力。本地版本没有移除这些功能，而是围绕界面统一、Harness 工作流、安装即用和新手引导继续扩展。

## 主要升级点

### 1. Chat / Harness 产品切换和视觉统一

顶部的 `Work Type` 切换栏保留原有位置和交互，不进行大幅重构，但完成了细节统一：

- `Work Type:` 的字体与主界面 UI 统一，字号和字重略微提高；`Work` / `Harness`（实际显示为 `Chat` / `Harness`）按钮也做了适度放大加粗。
- 当前选中项使用高对比黑白样式，浅色主题下为黑底白字，与参考 Harness 界面一致；暗色主题同步反转为浅底深字。
- Chat 和 Harness 共用同一个产品级切换栏，避免在嵌入页面中重复出现模式控件。
- Chat 原生界面和设置页统一为中性的浅灰侧栏、白色画布、细边框、圆角卡片和黑白强调色。
- 图标统一采用矢量绘制或现有矢量资源，统一线宽、尺寸、悬停态和强调色，降低不同控件之间的视觉跳跃。

### 2. DeepSeek 品牌区和侧边栏改造

侧边栏按照参考 Harness Web UI 的品牌排列重新组织，同时保持原有会话管理功能：

- 使用更清晰的 DeepSeek 黑白标志，标志尺寸统一为 34 px。
- 增加可见的 `deepseek` 字标和黑底白字的 `CHAT` 徽标，形成“标志 + 字标 + 产品类型”的品牌组合。
- “新建对话”改为更醒目的圆角卡片按钮，保留新建会话行为。
- 最近对话、批量选择、重命名、删除、侧栏折叠和设置入口全部保留。
- 设置页左侧品牌区和主 Chat 侧栏使用同一套标志、字标、徽标和尺寸规范。

### 3. 新建对话与普通对话的输入框布局

输入框根据会话状态采用两种布局：

- 新建对话时，输入框保持在内容区域的视觉中心附近，并与欢迎标题、建议问题形成清晰层级。
- 产生消息后，输入框下沉为底部停靠区域，行为与现有对话工作流保持一致。
- 输入框最大宽度收窄到更接近参考图的阅读比例，避免超宽窗口下内容过于松散。
- 添加、附件、深度思考、强度选择、停止生成和发送等功能不变，只统一了按钮尺寸、圆角、间距和图标风格。

### 4. 模型输出跟随、手动阅读和回到底部

本地版本新增了针对长回答的阅读状态管理：

- 模型流式输出时，默认自动跟随最新内容，视角会停留在回答底部。
- 用户使用滚轮向上阅读、拖动滚动条或手动离开底部后，自动跟随立即暂停，不会被后续输出强行拉回。
- 暂停状态下，输入框上方会出现一个圆形浮动按钮，按钮中心为简约向下箭头。
- 点击该按钮会回到最新消息、恢复自动跟随，并继续跟随模型后续输出。
- 消息区域增加底部安全留白，最后一段回答不会被停靠输入框遮挡。
- 新发送一条用户消息时会重新建立跟随，保证连续提问的工作流自然衔接。

### 5. Harness 官方 Web UI 集成

本地版本不重新实现 Harness 的项目、工具、审批和轨迹逻辑，而是把官方开发者预览版作为独立运行时启动并嵌入：

- 新增 `app/harness.py`，负责官方 `dsh web` 运行时的查找、启动、端口探测、配置初始化、状态同步和退出清理。
- 新增 `app/ui/harness_page.py`，负责 Harness Web UI 的 Qt WebEngine 容器、状态页、失败重试、官方文档入口和本地回环访问限制。
- 当前固定使用官方 npm 包 `@deepseek-ai/dsh@0.1.5-rc.1`，避免每次启动无提示地拉取未知版本。
- Harness 只绑定本机 loopback 地址，外部链接交由系统浏览器打开，内嵌页面不会任意跳转到外部站点。
- API 密钥通过 `DEEPSEEK_API_KEY` 进程环境传递给 Harness，不写入 Harness 的 YAML 配置文件。
- 首次启动会生成可编辑的 `~/.deepseek_chat_gui/harness/settings.yaml`，已有用户配置不会被覆盖。
- 支持在设置中配置多个 Harness 项目目录；没有配置时继续使用当前工作目录作为回退路径。

### 6. 启动后静默预热 Harness

为改善从 Chat 切换到 Harness 的首次体验，本地版本增加了默认开启的后台预热：

- Chat 窗口启动并稳定后，延迟启动 Harness 服务，但不切换当前页面、不弹出干扰提示。
- Harness 进程和 Web 服务保持温热，用户切换过去时可以直接加载已准备好的本地服务。
- 预热默认为开启，用户可以在“设置 → 运行环境”中关闭。
- 应用退出时会主动停止 Qt 子进程，并清理可能残留的占用端口进程，避免下次启动遇到旧服务。
- 测试环境使用 offscreen 平台时会跳过预热，避免自动化测试产生后台服务和端口副作用。

### 7. 设置页、防呆引导和运行环境入口

设置页从单一配置表单扩展为更接近 Harness 的两栏设置工作区，同时保留原有基础配置和个性化内容：

- 首次没有 API 密钥时，启动后自动进入设置页。
- API 配置区显示明确的流程提示：填写 API 密钥 → 测试连接 → 保存设置 → 开始对话。
- 测试连接成功后按账号实际返回结果同步当前可用模型，避免继续显示已经退役的内置模型。
- 新增“运行环境”栏目，展示 Node.js、npx、Harness 运行包和应用数据目录状态。
- 提供“重新检测”“打开配置目录”和“Node.js 更新入口”，为环境排查和升级预留明确入口。
- 提供 Harness 预热开关、项目目录编辑/选择、官方文档和官方仓库入口。
- 页面说明 Harness 的本地数据位置、API 密钥传递方式、项目文件修改和命令执行风险。

### 8. 模型目录和 API 兼容性更新

对比线上 `v0.1`，模型目录和配置迁移逻辑进一步收紧到当前官方接口状态：

- 默认官方路由更新为 `deepseek-flash`，界面标签继续显示为易读的 `DeepSeek V4.1 Flash`。
- 模型目录版本提升，旧版本中的临时 ID、旧 Pro 路由和旧视觉别名会迁移或清理。
- 官方 `/models` 返回值作为可用性依据，同时保留未来未知模型 ID，便于自定义网关或新模型提前使用。
- 最大输出 token 上限与当前 Harness 适配器对齐为 256,000。
- 设置页和 API 层共用同一套官方模型规范化逻辑，避免“设置页能选、发送时却失败”的不一致。

### 9. Markdown、代码和数学内容体验

本地版本继续收紧回答内容的显示细节：

- fenced code block 增加语言标签和复制按钮，代码保留原始转义内容。
- 代码块、行内代码、表格、列表、引用和链接统一为中性黑白视觉风格。
- 数学公式继续使用随应用携带的 KaTeX DOM 渲染，不使用截图或低分辨率位图。
- 长公式在自己的区域内横向滚动，不撑宽消息列；模型回答中的换行和流式未闭合公式保持稳定。
- 公式和 Markdown 输入仍经过安全转义，代码块中的公式分隔符不会被误解析。

### 10. 应用名称和黑白图标统一

应用名称和图标从运行时到安装包统一收口：

- 应用显示名称改为 `DeepSeek`，窗口标题、macOS Bundle 名称和 `.app` 名称保持一致。
- DMG 文件名和安装镜像卷标改为 `DeepSeek-<版本>-macos-<架构>.dmg` / `DeepSeek`。
- 现有鲸鱼矢量图标改为黑底白色鲸鱼的纯黑白方案，运行时窗口/Dock 图标、PyInstaller 使用的 ICNS 和 PNG 资源保持同源。
- 安装包中不再出现 `DeepSeek Chat.app` 这一旧应用名称；`Chat` 仍作为产品工作模式和侧栏徽标保留。

### macOS 首次打开提示

当前 macOS 安装包使用本地 ad-hoc 签名，尚未接入 Apple Developer ID 签名和 notarization。首次打开时，macOS 可能显示“无法验证开发者”，或显示“Apple 无法检查‘DeepSeek’是否包含恶意软件”，并阻止应用直接启动。确认 DMG 来自本项目的 [GitHub Releases](https://github.com/quzhenghao/deepseek-chat-gui/releases) 后，先尝试打开一次，再进入“系统设置 → 隐私与安全性”，向下滚动到“安全性”区域，在对应提示旁点击“仍要打开”（英文系统为 `Open Anyway`），按系统提示确认即可。Apple 官方说明见 [安全地打开 Mac App](https://support.apple.com/zh-cn/102445)；该按钮通常会在首次尝试打开后的约一小时内出现。

## 安装即用和打包方案

### 已实现的运行时集成

新增 `scripts/vendor_harness.sh` 作为构建时供应链脚本：

- 固定下载 Node.js `22.19.0`，按 Apple Silicon 或 Intel 架构选择对应压缩包。
- 在项目本地安装固定版本的 `@deepseek-ai/dsh` 及其生产依赖。
- 校验 Node 可执行文件和 Harness CLI 入口完整后，才交给 PyInstaller 收集。
- `DeepSeekChat.spec` 会在存在 `vendor/harness/` 时将运行时放进 `.app` 资源目录。
- 已打包应用优先直接调用内置 Node + Harness CLI，不要求用户安装 Node.js、npm、npx 或手工配置 PATH。
- 源码开发环境没有内置运行时才回退到系统 `npx`，并在设置页显示当前环境状态。

### 本轮构建验证

本地已生成并验证 Apple Silicon 1.0.0 安装包：

- [DeepSeek-1.0.0-macos-arm64.dmg](release/DeepSeek-1.0.0-macos-arm64.dmg)，约 435 MB。
- DMG 通过 `hdiutil verify`，SHA-256 已记录在 `release/SHA256SUMS`。
- 已验证 `.app` 内含 Node 可执行文件和官方 Harness CLI，并验证冻结应用能够启动、预热、退出。
- 该安装包为本地 ad-hoc 签名，尚未接入 Apple Developer ID 签名和 notarization；首次打开可能触发“无法验证开发者”或“Apple 无法检查‘DeepSeek’是否包含恶意软件”提示，需要在“系统设置 → 隐私与安全性 → 安全性”中点击“仍要打开”；正式公开分发前仍需补齐 Apple 签名与公证。

### 当前发布边界

- `1.0.0` 是当前正式升级版本；线上既有 `v0.1` 作为历史版本保留，两个版本均只提供 macOS Apple Silicon DMG 成品。
- Release 页面为 Windows 预留平台位置，但目前不上传 Windows 空文件或占位安装包。
- 当前已构建的是 macOS Apple Silicon 安装包；Intel 或 universal 版本需要在对应构建目标上重新打包和验证。
- `vendor/harness/`、`build/`、`dist/` 和临时 UI 截图已清理。源码仓库只保留构建脚本，DMG 中保留完整运行时，以避免把数百 MB 的二进制依赖直接提交到源码仓库。
- API 配置仍按现有行为保存在本机配置文件中；不要把个人配置目录或 API 密钥提交到版本库。

## 验证记录

本轮在本地 Conda `deepseek-chat` 环境完成：

```text
57 tests passed
ruff check app main.py scripts       All checks passed
python -m compileall -q app main.py  passed
hdiutil verify ...dmg                checksum is VALID
```

此外，使用 offscreen Qt 对欢迎页、普通对话页、设置页、运行环境页和长回答滚动状态做了截图核验，重点检查了：

- 顶部 Work Type 字体、字重、按钮尺寸和选中态；
- DeepSeek 标志、字标、`CHAT` 徽标和侧栏间距；
- 新建对话居中输入框与普通对话底部输入框的切换；
- 模型流式输出暂停跟随后的圆形向下箭头位置；
- 设置页卡片、运行环境入口和深浅色主题的一致性。

## 代码改动索引

| 文件 | 主要职责 |
| --- | --- |
| `app/ui/main_window.py` | 顶部 Work Type 栏、Chat 工作区、居中/底部输入框、Harness 预热调度 |
| `app/ui/sidebar.py` | 品牌区、侧栏、新建对话、模式切换器和按钮尺寸 |
| `app/ui/message_bubbles.py` | 流式输出、滚动状态、暂停跟随和恢复跟随 |
| `app/ui/settings_dialog.py` | 首次 API 引导、运行环境页、Harness 项目和预热设置 |
| `app/harness.py` | 官方 Harness 运行时生命周期、配置、端口和内置 Node 查找 |
| `app/ui/harness_page.py` | 官方 Harness Web UI 的嵌入、状态和安全导航边界 |
| `app/ui/theme.py`、`app/ui/controls.py`、`app/ui/icons.py` | 统一主题、圆角控件、图标和对话框视觉系统 |
| `app/config.py`、`app/api.py` | 模型目录迁移、官方模型同步、Harness 配置项和输出上限 |
| `scripts/vendor_harness.sh`、`scripts/package_macos.sh`、`DeepSeekChat.spec` | 内置运行时供应、PyInstaller 收集和 DMG 打包 |
| `tests/` | API、配置迁移、Markdown/公式、UI、模式切换和 Harness 行为回归测试 |

## 后续正式发布建议

1. 先审阅本文件和工作树差异，确认产品文案、Harness 预览版风险提示和版本号。
2. 在干净的 Apple Silicon 环境重新执行 `scripts/package_macos.sh`，并保留 DMG 与 `SHA256SUMS`。
3. 接入 Apple Developer ID 签名和 notarization，验证首次安装、权限提示、API 配置和 Harness 项目访问。
4. Windows 适配完成后再补充 Windows 安装包，不上传空文件或占位安装包。
5. 在没有 Node.js、npm、npx、API 环境变量和历史配置的干净用户环境中做一次安装即用验收。
