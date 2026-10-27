# DeepSeek 1.1.0

面向 macOS Apple Silicon 的 DeepSeek API 桌面客户端，提供原生 Chat 与官方 Harness。

| 平台 | 安装包 |
| --- | --- |
| macOS 14+ · Apple Silicon | [DeepSeek-1.1.0-macos-arm64.dmg](https://github.com/quzhenghao/deepseek-chat-gui/releases/download/v1.1.0/DeepSeek-1.1.0-macos-arm64.dmg) |

## 模型与接口

| 模型 ID | 服务模型 | 输入 | 上下文 | 最大输出 |
| --- | --- | --- | --- | --- |
| `deepseek-flash` | DeepSeek V4.1 Flash 1017 | 文本、图片 | 1,048,576 tokens | 393,216 tokens |
| `deepseek-v4-pro` | DeepSeek V4 Pro 0813 | 文本 | 1,048,576 tokens | 393,216 tokens |

- 直接调用 DeepSeek `/chat/completions`，支持流式正文、深度思考及 `low` / `high` / `max` 强度。
- 设置页通过 `/models` 同步账号可用的受支持模型；兼容网关支持自定义 API 地址与模型 ID。
- 联网搜索通过函数工具调用执行，支持 DuckDuckGo 与 Tavily，回答包含来源编号和可点击的引用；工具请求完整回传历史思考内容。
- Flash 支持选择、拖入和粘贴 JPEG、PNG、GIF、WebP 图片。
- Markdown、代码复制、表格和 KaTeX 公式在本机渲染；支持并行对话、按会话保留草稿、本地历史与浅色/深色主题。
- DMG 内置 Node.js 与官方 Harness 运行时；Chat 与 Harness 在同一窗口切换，支持后台预热。

接口说明：[Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)、[模型元数据](https://api-docs.deepseek.com/api/list-models/)、[思考模式](https://api-docs.deepseek.com/guides/thinking_mode/)。

## 安装

1. 下载并打开 DMG，将 `DeepSeek.app` 拖入“应用程序”。
2. 首次启动进入设置页，填写 DeepSeek API Key，点击“测试连接”后保存设置。
3. 返回 Chat 选择模型；顶部 `Work Type` 可以切换到 Harness。

应用使用本地 ad-hoc 签名，尚未进行 Apple Developer ID 签名与公证。首次打开如被 macOS 阻止，请确认安装包来自本项目 Release，在 Finder 尝试打开一次后，进入“系统设置 → 隐私与安全性”，点击“仍要打开”。

## 源码构建

```bash
conda activate deepseek-chat
python -m pip install -r requirements-dev.txt
python -m pip check
QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v
./scripts/package_macos.sh
```
