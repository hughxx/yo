# 邮件 / WeLink 单机助手（standalone）

本地抓取 Outlook 邮件 / WeLink 群聊 → 产出 **HTML + Markdown** 落盘，**不连服务器、不做提炼、不推经验引擎**。

设计详见 [`DESIGN.md`](./DESIGN.md)。

## 技术栈
- 前端：Next.js 14.1 + React 18.2 + TypeScript + TailwindCSS 4 + Sass + Zustand
- 桌面运行时：Tauri 2.x（Rust 核心）
- Outlook 操作：外置 `outlook_cli.exe`（Python + win32com）
- WeLink 拉取：外置 `welink-cli`（既有二进制）

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
