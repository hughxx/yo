# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all

webview_datas, webview_binaries, webview_hidden = collect_all('webview')

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=webview_binaries,
    datas=webview_datas + [('assets', 'assets'), ('web', 'web')],
    hiddenimports=webview_hidden + [
        'webview.platforms.edgechromium',
        'webview.platforms.winforms',
        'win32com.client',
        'pythoncom',
        'pywintypes',
        'win32timezone',
        'clr',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'tkinter'],
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
    name='问题定位助手',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets\\icon.ico'],
)
