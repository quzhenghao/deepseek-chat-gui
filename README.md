# DeepSeek Chat 本地客户端

<p align="center">
  <img src="assets/app-icon.png" width="120" alt="DeepSeek Chat 图标">
</p>

一个基于 Python 与 PySide6 的轻量桌面客户端。它直接调用你自己的 DeepSeek API，支持官方付费模型、流式输出、深度思考强度、图片输入和本地对话历史。

本项目是非官方客户端，与 DeepSeek 官方无隶属或背书关系。

<p align="center">
  <a href="https://github.com/quzhenghao/deepseek-chat-gui/releases"><img src="https://img.shields.io/badge/下载-v0.1-4B7BF5?logo=github" alt="下载"></a>
  <img src="https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/PySide6-6.11-41CD52" alt="PySide6">
  <img src="https://img.shields.io/badge/macOS-Apple%20Silicon-black" alt="macOS">
</p>

## 功能

- 使用自己的 API 密钥直接请求 `https://api.deepseek.com`
- 支持 DeepSeek V4 Flash、V4.1 Flash 限时内测、V4 Pro 与 V4 Vision
- 深度思考可随时开关，强度可选 `Low`、`High`、`Max`
- 思考阶段显示动态小图标，思考内容默认折叠；正文到达后才显示答案
- SSE 流式输出，生成过程中可随时停止
- 支持 Markdown、代码块、表格、列表、引用、链接与本地矢量 LaTeX 数学公式
- 视觉模型支持选择、拖入或粘贴 PNG、JPEG、GIF、WebP 图片
- 对话、设置和图片仅保存在本机
- 支持浅色与深色主题
- 支持为每个新对话自动注入自定义系统提示词
- 每轮回答完成后基于全部对话上下文自动生成精短历史标题
- 全部操作图标使用矢量绘制，高分屏下保持清晰
- macOS 运行时使用独立 Dock 图标，并提供高分辨率 PNG、SVG 和 ICNS 资源

## 支持的模型

| 界面名称 | API 模型 ID | 图片输入 |
| --- | --- | --- |
| DeepSeek V4 Flash | `deepseek-v4-flash` | 否 |
| DeepSeek V4.1 Flash（限时至 9/10） | `deepseek-v4.1-flash-expires-on-0910` | 是 |
| DeepSeek V4 Pro | `deepseek-v4-pro` | 否 |
| DeepSeek V4 Vision | `deepseek-v4-flash-vision-exp` | 是 |

模型和参数以 [DeepSeek API 快速开始](https://api-docs.deepseek.com/)、[Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode/) 与 [Vision](https://api-docs.deepseek.com/guides/vision/) 为准。

上表模型均支持思考模式开关；`deepseek-v4.1-flash-expires-on-0910` 与 `deepseek-v4-flash-vision-exp` 接受图片输入。客户端把界面选择原样映射为 API 的 `model`，思考模式把 `Low`、`High`、`Max` 分别发送为 `low`、`high`、`max`。

V4.1 Flash 是限时内测模型，模型 ID 已注明于 9 月 10 日到期。它目前可能不会出现在 `/models` 返回值中，因此客户端连接官方 DeepSeek API 并同步模型时会额外保留这一条；是否开放及实际停止时间仍以账号调用结果为准。

DeepSeek 当前接受 `low`、`high`、`max` 三档思考强度，客户端界面使用对应的英文名称 `Low`、`High`、`Max`。

## 下载与安装（macOS）

从 [Releases](https://github.com/quzhenghao/deepseek-chat-gui/releases) 下载最新的
`DeepSeek-Chat-0.1.0-macos-arm64.dmg`，打开镜像后把 `DeepSeek Chat` 拖入
“应用程序”即可完成安装。安装包当前为本地 ad-hoc 签名；首次打开若提示
“无法验证开发者”，请右键点击应用并选择“打开”，或在“系统设置 → 隐私与安全性”中允许打开。

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

首次启动会自动进入全屏设置页。

1. 在“API 密钥”中填写 DeepSeek API Key。
2. 保持默认 API 地址 `https://api.deepseek.com`。
3. 点击“测试连接”。连接成功后，客户端会同步该账号当前可用的模型 ID。
4. 在“基础配置”中选择默认模型、思考模式、强度和主题。
5. 如有需要，在“个性化”中填写系统提示词。它会作为隐藏的系统消息加入此后每个新对话，并位于首条用户消息之前。
6. 保存设置并开始对话。

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
└── media/               已发送的本地图片副本
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

测试覆盖请求参数、流式与非流式响应解析、图片消息、数学公式边界解析、矩阵/分段/多行公式、矢量 DOM 输出、窄屏公式溢出、全上下文标题生成、配置迁移、对话存储和思考折叠状态。

## 项目结构

```text
deepseek-chat-gui/
├── main.py
├── requirements.txt
├── requirements-dev.txt
├── DeepSeekChat.spec
├── scripts/
│   ├── package_macos.sh
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
│   ├── markdown.py
│   ├── storage.py
│   ├── worker.py
│   └── ui/
│       ├── controls.py
│       ├── icons.py
│       ├── image_strip.py
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

脚本先用 PyInstaller 生成 `dist/DeepSeek Chat.app`，再用系统自带的
`hdiutil` 打包为 `release/DeepSeek-Chat-<版本>-macos-arm64.dmg`。镜像内包含
应用本体和指向 `/Applications` 的快捷方式，打开后把应用拖入
“应用程序”即可完成安装。

构建产物是未经过 Apple 公证（notarization）的本地签名包。首次打开时，如果
macOS 提示“无法验证开发者”，请右键点击应用并选择“打开”，或在系统设置的
“隐私与安全性”中允许打开。需要正式分发时，可在此基础上接入 Apple
Developer ID 签名与公证。

## 发布到 GitHub

1. 在本机初始化仓库并提交代码（首次执行一次）：

   ```bash
   git init -b main
   git add .
   git commit -m "Initial commit"
   ```

2. 在 GitHub 上创建同名仓库，然后关联并推送：

   ```bash
   git remote add origin git@github.com:OWNER/deepseek-chat-gui.git
   git push -u origin main
   ```

3. 使用 GitHub CLI 创建 Release 并上传 DMG：

   ```bash
   ./scripts/release_github.sh
   ```

   该脚本会读取 `app/__init__.py` 中的版本号，创建 `v<版本>` 标签，把
   `release/` 下的 DMG 作为资产上传，并自动生成变更说明。

## 常见问题

### 点击发送后提示模型不存在

在设置中点击“测试连接”重新同步模型列表。自定义网关需要填写它实际支持的模型 ID，而不是界面展示名。

### 图片按钮不可用

先在顶部切换到 DeepSeek V4 Vision。其他模型不接受图片输入。

### macOS Dock 启动瞬间短暂出现 Python 图标

直接执行脚本时，系统可能在 Qt 窗口创建前短暂显示 Python 图标；窗口建立后会切换为项目图标。若打包为 `.app`，使用 `assets/app-icon.icns` 写入应用包的 `CFBundleIconFile` 可让启动全程显示正确图标。
