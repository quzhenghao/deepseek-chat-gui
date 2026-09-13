# 版本与安装包

| 版本 | MacOS(Apple Silicon) | MacOS(Intel Silicon) | Windows |
| --- | --- | --- | --- |
| `v1.0.0` | [DeepSeek-1.0.0-macos-arm64.dmg](https://github.com/quzhenghao/deepseek-chat-gui/releases/download/v1.0.0/DeepSeek-1.0.0-macos-arm64.dmg) | 待适配 | 待适配 |

安装包由 PyInstaller 和系统 `hdiutil` 生成，DMG 中包含 `DeepSeek.app` 与 `/Applications` 快捷方式。Windows 和 Intel/universal 成品尚未发布，不上传占位文件。

安装步骤：

1. 在上面的列表中点击对应版本的安装包链接。
2. 将 `DeepSeek.app` 拖到“应用程序”。
3. 首次打开进入设置，填写 API Key，点击“测试连接”同步当前账号模型并保存。
4. 返回 Chat；需要 Harness 时点击顶部 `Harness`。

# 首次打开必须手动允许

本项目目前没有 Apple Developer ID 签名和 notarization。安装完成后第一次打开时，macOS 可能显示“无法验证开发者”或“Apple 无法检查‘DeepSeek’是否包含恶意软件”，并阻止应用运行。

请先在 Finder 中尝试打开一次应用，再进入 **系统设置 → 隐私与安全性**，向下滚动到“安全性”区域，点击 **“仍要打开”**，按系统提示确认后即可正常运行。请确认安装包来自本 Release。当前包使用本地 ad-hoc 签名，未接入 Apple Developer ID 签名与 notarization。

# 更新日志

## v1.0.0版本(Mac+Win)

- **Chat / Harness 一体化**：顶部 `Work Type` 统一提供 `Chat` / `Harness` 两种工作模式；Chat 使用原生 Qt 界面，Harness 使用官方 `@deepseek-ai/dsh@0.1.5-rc.1` Web UI；两种模式共用设置页、API 配置、主题和运行环境入口，可以在同一个窗口内无缝切换；Chat 启动后默认后台预热 Harness。
- **API 与多模型**：本地端直接接入 DeepSeek API；“测试连接”读取 API 的 `/models`，把当前账号实际有权限的模型同步到设置页；支持切换多个付费模型、自定义 API 地址和模型 ID；保留深度思考、`low` / `high` / `max` 强度、图片输入和自定义系统提示词。
- **联网搜索**：输入框提供“联网搜索”开关，设置页可配置默认状态和搜索服务商（默认 DuckDuckGo 免密钥，可选 Tavily）；通过 DeepSeek 官方 `function` 工具调用实现：模型给出查询，客户端执行搜索并把带编号的结果回传，回答按 `[1]`、`[2]` 标注引用并附参考来源。
- **本地 Markdown 与数学内容**：KaTeX、CSS 和数学字体随应用打包，公式在本地 DOM 中渲染，不依赖在线服务；支持行内公式、独立公式、矩阵、分段函数、`align` / `equation` 等显示环境；长公式只在公式区域横向滚动，不撑宽消息列表；代码块保留语言标签、等宽排版和复制操作。
- **安装即用**：DMG 内置 Node.js `22.19.0`、Harness CLI 和生产依赖，不要求用户手动安装 Node.js、npm、npx 或修改 PATH；Harness 只监听本机 loopback，API Key 通过进程环境传递，不写入 Harness YAML；应用退出时清理 Harness 子进程和临时资源。

# 验证范围

- Python 单元测试：覆盖 API、联网搜索、模型目录迁移、Markdown/LaTeX、配置、存储、Chat/Harness 切换和 UI 交互。
- UI 截图核验：欢迎页、联网搜索与引用、复杂数学回答页、设置页。
- DMG 构建：PyInstaller `.app`、内置 Node/Harness 运行时、Apple Silicon DMG。
- 交互回归：弹窗单层圆角、文本选区、`I` 形光标、右键菜单不取消选区、复制与全选。

# 已知提示

- `error messaging the mach port for IMKCFRunLoopWakeUpReliable` 是 macOS 输入法框架偶发的系统警告，不代表应用退出；客户端保留原生输入法，因此不通过环境变量禁用中文输入来隐藏它。
- Harness 属于官方开发者预览运行时，项目文件修改、命令执行和审批操作请在页面中确认后再继续。

# 源码构建

```bash
conda activate deepseek-chat
python -m pip install -r requirements-dev.txt
QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v
./scripts/package_macos.sh
```

`scripts/release_github.sh` 默认使用本文件作为 GitHub Release 说明；版本号仍由 `app/__init__.py` 的 `__version__` 控制。
