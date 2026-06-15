"""把 outlook_cli 打包成单文件 outlook_cli.exe（PyInstaller）。

产物：sidecar/outlook_cli/dist/outlook_cli.exe
Tauri 打包时会把它作为资源带进安装包（见 tauri.conf.json）。
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> int:
    # 确保依赖就绪
    subprocess.run(
        [sys.executable, '-m', 'pip', 'install', '-r', str(HERE / 'requirements.txt')],
        check=True,
    )
    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--onefile',
        '--noconsole',
        '--name', 'outlook_cli',
        # win32com 时区支持必须显式带上
        '--hidden-import', 'win32timezone',
        '--distpath', str(HERE / 'dist'),
        '--workpath', str(HERE / 'build'),
        '--specpath', str(HERE),
        str(HERE / 'outlook_cli.py'),
    ]
    return subprocess.run(cmd, check=False).returncode


if __name__ == '__main__':
    raise SystemExit(main())
