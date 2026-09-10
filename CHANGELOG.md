# 更新日志

## v1.0.0 — 2026-09-10

这是一次面向正式使用场景的重大升级：DeepSeek Chat 与官方 DeepSeek Harness 被整合到同一个桌面应用中，同时补齐安装运行时、首次使用引导和长对话交互体验。

### 核心能力

- **Chat / Harness 一体化**：在同一个 `DeepSeek` 窗口中使用本地 Chat 和官方 Harness，顶部通过 `Work Type` 一键切换，统一品牌、设置和使用习惯。
- **Harness 官方 Web UI 集成**：使用固定版本 `@deepseek-ai/dsh@0.1.5-rc.1`，支持项目、工具、审批、文件和轨迹等官方能力；内嵌页面限制在本机 loopback 服务。
- **启动后静默预热**：Chat 启动后默认在后台提前启动 Harness，用户无需先切换页面即可让运行时保持温热；可在“设置 → 运行环境”中关闭。
- **安装即用**：macOS DMG 内置 Node.js `22.19.0`、Harness CLI 和生产依赖，不要求用户提前安装 Node.js、npm、npx 或手工修改 PATH。

### UI 与交互

- 顶部 `Work Type` 字体、字重和按钮尺寸与主界面统一，保留原有布局，不改变切换逻辑。
- DeepSeek 品牌区调整为黑白鲸鱼图标、`deepseek` 字标和 `CHAT` 徽标，侧栏、设置页和 Harness 切换栏统一为中性黑白视觉语言。
- 新建对话时输入框居中显示；进入普通对话后输入框下沉到底部，最后一条回答不会被遮挡。
- 模型流式输出默认跟随最新内容；用户向上滚动或拖动滚动条后自动暂停，点击圆形向下箭头即可回到最新位置并恢复跟随。
- 应用图标、窗口标题、macOS Bundle、`.app`、DMG 卷标和文件名统一使用 `DeepSeek`。
- 应用图标改为纯黑白方案：黑色圆角底配白色鲸鱼，PNG、SVG、ICNS 和运行时图标保持同源。

### 设置与防呆

- 首次没有 API Key 时自动进入设置页，并提示“填写 API 密钥 → 测试连接 → 保存设置”。
- 新增“设置 → 运行环境”，可查看 Node.js / npx / Harness 状态、打开配置目录、进入 Node.js 更新页面、配置 Harness 项目目录和查看官方文档/仓库。
- API Key 继续保存在本机配置中，并通过进程环境传递给 Harness，不写入 Harness 的适配器 YAML。
- 官方模型目录同步到当前 `deepseek-flash` 路由，旧模型 ID 自动迁移，最大输出限制与 Harness 适配器对齐为 256,000 token。

### 内容渲染

- 代码块增加语言标签、等宽排版、横向滚动和一键复制。
- 数学公式继续使用随应用携带的 KaTeX DOM 离线渲染，长公式在独立区域内横向滚动，不撑宽消息列。
- 保留 Markdown、图片输入、深度思考、会话历史、自定义系统提示词和自动标题等原有功能。

### 发布资产

| 平台 | v1.0.0 | 状态 |
| --- | --- | --- |
| macOS Apple Silicon | `DeepSeek-1.0.0-macos-arm64.dmg` | 已提供 |
| Windows | — | 待适配 |

当前 v1.0.0 安装包为 Apple Silicon macOS 版本，使用本地 ad-hoc 签名，尚未接入 Apple Developer ID 签名和 notarization。首次打开时 macOS 可能显示“无法验证开发者”，或显示“Apple 无法检查‘DeepSeek’是否包含恶意软件”，并阻止应用启动。请确认 DMG 来自本项目的 GitHub Releases，先尝试打开一次，再到“系统设置 → 隐私与安全性”向下滚动到“安全性”区域，在对应提示旁点击“仍要打开”（英文系统为 `Open Anyway`），按提示确认即可。详见 [Apple 官方说明](https://support.apple.com/zh-cn/102445)。Windows 安装包位置已预留，后续适配完成后再添加，不上传空文件或占位安装包。

## v0.1.0 — 2026-09-09

首个 Apple Silicon macOS 安装版，提供基础的 DeepSeek API 对话能力：

- 支持流式输出、深度思考、图片输入、Markdown、代码块、表格和离线 KaTeX 数学公式。
- 支持本地对话历史、浅色/深色主题、自定义系统提示词和自动生成历史标题。
- 提供 `DeepSeek-Chat-0.1.0-macos-arm64.dmg` 成品安装包。
