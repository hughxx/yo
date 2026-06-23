"""把 html2md 打包成单文件 html2md.exe（PyInstaller）。

产物：sidecar/html2md/dist/html2md.exe
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> int:
    subprocess.run(
        [sys.executable, '-m', 'pip', 'install', '-r', str(HERE / 'requirements.txt')],
        check=True,
    )
    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--onefile',
        '--noconsole',
        '--name', 'html2md',
        '--distpath', str(HERE / 'dist'),
        '--workpath', str(HERE / 'build'),
        '--specpath', str(HERE),
        str(HERE / 'html2md.py'),
    ]
    return subprocess.run(cmd, check=False).returncode


if __name__ == '__main__':
    raise SystemExit(main())
