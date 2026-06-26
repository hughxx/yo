# 邮件 / WeLink 单机助手（standalone）

本地抓取 Outlook 邮件 / WeLink 群聊 → 产出 **HTML + Markdown** 落盘，**不连服务器、不做提炼、不推经验引擎**。

设计详见 [`DESIGN.md`](./DESIGN.md)。

## 技术栈
- 前端：Next.js 14.1 + React 18.2 + TypeScript + TailwindCSS 4 + Sass + Zustand
- 桌面运行时：Tauri 2.x（Rust 核心）
- Outlook 操作：外置 `outlook_cli.exe`（Python + win32com）
- WeLink 拉取：外置 `welink-cli`（既有二进制）

## 环境准备（装一次）

| 用途 | 需要安装 |
|---|---|
| 前端 | Node.js 18+、pnpm（`npm i -g pnpm`） |
| Rust 核心 | Rust 工具链。**本仓库用 GNU 工具链** `stable-x86_64-pc-windows-gnu`（`rustup default stable-x86_64-pc-windows-gnu` + mingw-w64）。默认 MSVC 一般也能编（`[lib]` 已设 `crate-type=["rlib"]`），若遇 `export ordinal too large` 链接错再切 GNU |
| 两个 sidecar | Python 3.x + pip（`build.py` 会自动 `pip install` pywin32 / pyinstaller / html2text） |
| WebView2 | Win11 自带；NSIS 安装包也会自动带。NSIS 本体 Tauri 首次打包自动下载，无需手装 |

> **welink-cli** 是单独的既有二进制，不在本仓库、也不随包打。程序按
> 「设置里的路径 → 环境变量 `WELINK_CLI` → PATH 中的 `welink-cli`」顺序解析；
> 把它的路径写进 `WELINK_CLI` 环境变量，或丢进 PATH 即可。

## 开发

```bash
# 1. 安装前端依赖（首次）
pnpm install

# 2. 启动开发（Tauri 起窗口 + Next dev）
pnpm tauri dev

# 仅构建前端静态产物
pnpm build            # 输出到 out/

# 仅类型检查 Rust 核心
cd src-tauri && cargo check
```

> pnpm 11 对未批准的原生构建脚本会报错，本仓库已在 `pnpm-workspace.yaml` 用
> `allowBuilds: { '@parcel/watcher': false }` 显式跳过该可选依赖的原生构建。

## 打包（Windows）

一键：

```bash
build_all.bat        # 依次打 outlook_cli.exe + html2md.exe + Tauri 安装包
```

> 两个 exe 必须先打好：`tauri.conf.json` 把它们作为 resources 打进包，
> 编译期会校验文件存在，缺了直接失败。安装包名是中文，故用 NSIS（MSI 对中文名会失败）。

或手动：

```bash
python sidecar/outlook_cli/build.py   # outlook_cli.exe（Outlook COM）
python sidecar/html2md/build.py       # html2md.exe（HTML→MD）
pnpm tauri build                      # 安装包 → src-tauri/target/release/bundle/nsis/
```

## 目录
```
src/          前端（Next.js）
src-tauri/    Rust 核心（Tauri）
sidecar/      outlook_cli.exe + html2md.exe 源码与打包脚本
```
