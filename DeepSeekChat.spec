# -*- mode: python ; coding: utf-8 -*-


hiddenimports = [
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[("assets", "assets")],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DeepSeek Chat",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/app-icon.icns",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="DeepSeek Chat",
)

app = BUNDLE(
    coll,
    name="DeepSeek Chat.app",
    icon="assets/app-icon.icns",
    bundle_identifier="com.local.deepseek-chat",
    info_plist={
        "CFBundleName": "DeepSeek Chat",
        "CFBundleDisplayName": "DeepSeek Chat",
        "CFBundleShortVersionString": "2.0.0",
        "CFBundleVersion": "2.0.0",
        "CFBundleIconFile": "app-icon.icns",
        "NSHighResolutionCapable": True,
    },
)
