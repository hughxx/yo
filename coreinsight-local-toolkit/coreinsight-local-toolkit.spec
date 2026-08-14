# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_submodules


hiddenimports = (
    collect_submodules("uvicorn")
    + collect_submodules("pystray")
    + collect_submodules("psycopg2")
)

a = Analysis(
    ["toolkit_launcher.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("coreinsight_local_toolkit/web", "coreinsight_local_toolkit/web"),
        ("coreinsight_local_toolkit/assets", "coreinsight_local_toolkit/assets"),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="coreinsight-local-toolkit",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=r"D:\CoreInsight\LocalToolkit\runtime",
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="coreinsight_local_toolkit/assets/icon.ico",
)
