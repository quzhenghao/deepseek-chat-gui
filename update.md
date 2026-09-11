# DeepSeek v1.0.0 更新说明

本次发布保持版本号 `v1.0.0`，用于覆盖更新 GitHub 上现有的说明和 Apple Silicon DMG。发布目标是把原生 Chat、官方 Harness 和本地渲染能力收拢到同一个可安装的 macOS 应用中。

> ## ⚠️ 首次打开必须手动允许
>
> 本项目目前没有 Apple Developer ID 签名和 notarization。安装完成后第一次打开时，macOS 可能显示“无法验证开发者”或“Apple 无法检查‘DeepSeek’是否包含恶意软件”，并阻止应用运行。
>
> 请先在 Finder 中尝试打开一次应用，再进入 **系统设置 → 隐私与安全性**，向下滚动到“安全性”区域，点击 **“仍要打开”**，按系统提示确认后即可正常运行。请确认安装包来自本 Release。

## 主要变化

### Chat 与 Harness 一体化

- 顶部 `Work Type` 统一提供 `Chat` / `Harness` 两种工作模式。
- Chat 使用原生 Qt 界面，Harness 使用官方 `@deepseek-ai/dsh@0.1.5-rc.1` Web UI。
- 两种模式共用设置页、API 配置、主题和运行环境入口，可以在同一个窗口内无缝切换。
- Chat 启动后可默认后台预热 Harness，首次切换时无需重新打开另一个应用。

### API 与多模型

- 本地端直接接入 DeepSeek API，不依赖网页版 Chat 的固定入口。
- “测试连接”会读取 API 的 `/models`，把当前账号实际有权限的模型同步到设置页。
- 同一客户端可以切换多个可用的付费模型，也支持自定义 API 地址和模型 ID；能否调用某个模型仍由 API 账号权限和服务端结果决定。
- 保留深度思考、`low` / `high` / `max` 强度、图片输入和自定义系统提示词。

### 本地 Markdown 与数学内容

- KaTeX、CSS 和数学字体随应用打包，公式在本地 DOM 中渲染，不依赖在线服务。
- 支持行内公式、独立公式、矩阵、分段函数、`align` / `equation` 等显示环境。
- 长公式只在公式区域横向滚动，不撑宽消息列表。
- 代码块保留语言标签、等宽排版和复制操作。

### 选择、复制和右键菜单

- AI 返回内容、深度思考内容和用户消息使用文本光标，鼠标悬停时显示 `I` 形光标。
- 左键点击消息区域之外会取消当前选区。
- 右键不会清除已有选区，现有的复制、全选等菜单仍可在选中状态下执行。
- 公式 WebEngine 表面和普通文本表面保持一致的选择与光标反馈。

### 界面细节

- 删除对话确认弹窗的背景圆角方框收敛为单层绘制，去除四角细微叠框。
- Chat 欢迎页、消息页、设置页、侧栏和模式切换栏使用统一的黑白中性视觉。
- 新建对话时输入框居中；已有消息时输入框停靠在底部。
- 流式回答默认跟随最新内容；用户向上阅读时暂停跟随，点击按钮后恢复。
- 本地会话、图片副本、自动标题、重命名和批量删除逻辑继续保留。

### 安装即用

- DMG 内置 Node.js `22.19.0`、Harness CLI 和生产依赖。
- 打包后的应用优先调用内置运行时，不要求用户手动安装 Node.js、npm、npx 或修改 PATH。
- Harness 只监听本机 loopback，API Key 通过进程环境传递，不写入 Harness YAML。
- 应用退出时清理 Harness 子进程和临时资源。

## 版本与安装包

| 版本 | 平台 | 下载链接 | 状态 |
| --- | --- | --- | --- |
| `v1.0.0` | macOS Apple Silicon | [DeepSeek-1.0.0-macos-arm64.dmg](https://github.com/quzhenghao/deepseek-chat-gui/releases/download/v1.0.0/DeepSeek-1.0.0-macos-arm64.dmg) | 当前版本 |
| `v1.0.0` | Windows | 暂无 | 待适配 |

安装包由 PyInstaller 和系统 `hdiutil` 生成，DMG 中包含 `DeepSeek.app` 与 `/Applications` 快捷方式。Windows 和 Intel/universal 成品尚未发布，不上传占位文件。

## 安装与首次启动

1. 在上面的“版本与安装包”列表中点击对应版本的安装包链接。
2. 将 `DeepSeek.app` 拖到“应用程序”。
3. 首次打开进入设置，填写 API Key，点击“测试连接”同步当前账号模型并保存。
4. 返回 Chat；需要 Harness 时点击顶部 `Harness`。

当前包使用本地 ad-hoc 签名，未接入 Apple Developer ID 签名与 notarization。遇到安全提示时，请按文档顶部的“系统设置 → 隐私与安全性 → 仍要打开”步骤操作。

## 验证范围

- Python 单元测试：覆盖 API、模型目录迁移、Markdown/LaTeX、配置、存储、Chat/Harness 切换和 UI 交互。
- UI 截图核验：欢迎页、复杂数学回答页、设置页。
- DMG 构建：PyInstaller `.app`、内置 Node/Harness 运行时、Apple Silicon DMG。
- 交互回归：弹窗单层圆角、文本选区、`I` 形光标、右键菜单不取消选区、复制与全选。

## 已知提示

- `error messaging the mach port for IMKCFRunLoopWakeUpReliable` 是 macOS 输入法框架偶发的系统警告，不代表应用退出；客户端保留原生输入法，因此不通过环境变量禁用中文输入来隐藏它。
- 当前成品没有 Apple 公证，首次打开可能需要用户在“隐私与安全性”中手动允许。
- Harness 属于官方开发者预览运行时，项目文件修改、命令执行和审批操作请在页面中确认后再继续。

## 源码构建

```bash
conda activate deepseek-chat
python -m pip install -r requirements-dev.txt
QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v
./scripts/package_macos.sh
```

`scripts/release_github.sh` 默认使用本文件作为 GitHub Release 说明；版本号仍由 `app/__init__.py` 的 `__version__` 控制。
