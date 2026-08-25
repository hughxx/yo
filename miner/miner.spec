# PyInstaller spec for the standalone Miner.
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

HERE = Path(SPEC).resolve().parent
ROOT = HERE.parent

a = Analysis(
    [str(HERE / "main.py")],
    pathex=[str(ROOT), str(ROOT / "pyqt_client")],
    binaries=[],
    datas=[
        (str(HERE / "web"), "miner/web"),
        (str(ROOT / "pyqt_client" / "assets"), "pyqt_client/assets"),
    ],
    hiddenimports=collect_submodules("modules") + [
        "pystray",
        "modules",
        "modules.email.outlook",
        "modules.email.html2md",
        "modules.welink.history",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="miner", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=True, console=False,
    icon=str(ROOT / "pyqt_client" / "assets" / "icon.ico"),
)
