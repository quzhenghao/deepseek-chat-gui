# DeepSeek 1.1.0

面向 macOS Apple Silicon 的 DeepSeek API 桌面客户端，提供原生 Chat 与官方 Harness。对话、图片和个性化设置保存在本机。

[下载 DeepSeek-1.1.0-macos-arm64.dmg](https://github.com/quzhenghao/deepseek-chat-gui/releases/download/v1.1.0/DeepSeek-1.1.0-macos-arm64.dmg) · macOS 14.4+

## Chat

| 模型 | API ID | 输入 |
| --- | --- | --- |
| DeepSeek V4.1 Flash 1017 | `deepseek-flash` | 文本、图片 |
| DeepSeek V4 Pro 0813 | `deepseek-v4-pro` | 文本 |

两个模型均支持 1,048,576 tokens 上下文和最多 393,216 tokens 输出。界面中的 Low、High、Max 分别对应 `low`、`high`、`max`。关闭深度思考可使用标准模式。 [模型列表](https://api-docs.deepseek.com/zh-cn/api/list-models/) · [思考模式](https://api-docs.deepseek.com/zh-cn/guides/thinking_mode/)

- **联网搜索**使用 DeepSeek 自研 Search 与 Fetch 接口，和对话共用 API 密钥。回答支持带编号的来源与可点击的参考链接。 [网页搜索与抓取](https://api-docs.deepseek.com/zh-cn/guides/search/)
- **本地排版**支持 Markdown、表格、代码复制、链接和离线 KaTeX。Flash 支持图片选择、拖入与粘贴。
- **会话管理**支持并行生成、会话草稿、历史记录、自动标题及浅色和深色主题。
- **Harness**可从顶部 Work Type 进入。安装包内置 Node.js 与官方 Harness 运行时，支持本地项目和后台预热。

## 安装

1. 打开 DMG，将 **DeepSeek.app** 拖入“应用程序”。
2. 首次启动填写 DeepSeek API 密钥，点击“测试连接”后保存设置。
3. 返回 Chat 选择模型，或从顶部 **Work Type** 进入 Harness。

安装包使用本地 ad-hoc 签名。若 macOS 拦截启动，请确认安装包来自本项目的 GitHub Release，在 Finder 尝试打开应用一次，再到“系统设置 → 隐私与安全性”选择“仍要打开”。 [Apple 支持](https://support.apple.com/zh-cn/102445)
