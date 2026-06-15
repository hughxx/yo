# Standalone 单机版 设计文档

> 目标：把现有 `pyqt_client` + `server` 的「邮件 / WeLink 群聊」抓取能力，改造成**纯单机**桌面应用。
> 原则：**抓取 → 产出 HTML + Markdown → 落盘本地 → 结束**。不做提炼、不推经验引擎、不连服务器。

本目录（`standalone/`）下为该单机版的全部代码与资源，与旧的 `pyqt_client/`、`server/` 完全独立，互不引用。

---

## 1. 设计原则与「砍掉」清单

### 1.1 保留的能力
- **邮件**：读取本地 Outlook（含已挂载 PST）、按文件夹 + 规则（主题/正文关键词、发件人）匹配、批量导入 `.msg`、导入 `.pst`。
- **WeLink**：通过外置 `welink-cli` 拉取群聊历史，支持「开始/结束/总结」命令录制、按天自动归档。
- **图片转外链**：邮件内联图片（`cid:` 附件）、WeLink 云盘图片（`um_content`）通过**用户可配置的图片上传接口**换成公网超链接写入 HTML/MD；用户不配该接口时，产物里直接不含图片（详见 §6）。
- **HTML → Markdown** 转换。
- 所有设置项暴露在「设置」对话框，用户自行配置。

### 1.2 砍掉的概念（旧系统有，单机版不要）
| 砍掉 | 原因 |
|---|---|
| 服务器地址 / `backendUrl` / `ping` / 连通性检测 | 无后端 |
| 命名空间 `namespace` / `collection` | 无知识库分区概念 |
| 用户 `userId` / `UploadBy` / `userinfo` 补全 | 单机无多用户 |
| LLM **提炼**（`_call_llm` / daily agent / tool-call） | 只要原始 HTML+MD |
| OCR（`img.ocr` / `_enrich_with_ocr`） | 仅为喂 LLM，无 LLM 即无意义 |
| **经验引擎**推送（`engine.push_experience` / `EXPERIENCE_ENGINE_URL`） | 不外推 |
| `parse_status` / `done|pending|failed` 同步状态 | 无远端处理队列 |
| MySQL / SQLAlchemy / `server/db` | 本地用轻量记录即可（见 §7） |
| 规则「共享资源」确认弹窗（`接口人已知晓`） | 规则是本地私有的 |
| 图片上传到文件服务器返回公网 URL | 改为存本地相对路径 |

---

## 2. 总体架构

三层 + 两个外置 CLI：

```
┌─────────────────────────────────────────────────────────┐
│  前端 UI  (Next.js 14.1 / React 18.2 / TS / Tailwind 4   │
│           / Sass / Zustand)  —— 运行在 Tauri WebView      │
│   邮件面板 · WeLink 面板 · 设置对话框 · 本地产物浏览       │
└───────────────▲───────────────────────┬──────────────────┘
                │ Tauri invoke (command) │ events (日志/进度)
┌───────────────┴───────────────────────▼──────────────────┐
│  Rust 核心  (Tauri 2.x backend)                           │
│   · 调度：邮件扫描定时器 / WeLink 轮询                      │
│   · 规则匹配（主题/正文/发件人）                            │
│   · HTML → Markdown（Rust crate，§5.3）                    │
│   · 图片本地化下载（reqwest，§6）                           │
│   · 落盘：扁平 + 时间戳前缀（§6）                           │
│   · 设置读写（JSON）、本地去重记录                          │
└──────┬───────────────────────────────────┬───────────────┘
       │ 子进程 (stdin/args → stdout JSON)   │ 子进程
┌──────▼─────────────────┐      ┌───────────▼───────────────┐
│ outlook_cli.exe         │      │ welink-cli (既有外置二进制) │
│ (Python + win32com)     │      │ im query-history-message    │
│ Outlook COM 全部操作    │      │ （沿用旧实现，不在本仓维护）│
└─────────────────────────┘      └─────────────────────────────┘
```

**为什么 Outlook 要外置成 `outlook_cli.exe`**：Outlook 自动化只有 COM（`win32com`）这一条稳定路径，Rust / TS 都没有成熟封装。沿用旧 `ews_cli.exe` / `welink-cli` 已验证的「子进程 + stdout JSON」模式。

> ⚠️ COM 生命周期：`outlook_cli.exe` 内部每次会话必须配对 `CoInitialize` / `CoUninitialize` 并释放 MAPI 对象，否则会触发 `MAPI_E_NO_RESOURCES`（旧版踩过的坑，见 `outlook.py` 的 `_session()`）。直接复用旧 `_session()` 上下文管理器。

---

## 3. 技术栈与依赖

### 3.1 前端
| 类别 | 选型 |
|---|---|
| 框架 | Next.js 14.1（`output: 'export'` 静态导出给 Tauri 加载）+ React 18.2 |
| 语言 | TypeScript 5.2 |
| 样式 | TailwindCSS 4.1 + Sass |
| 状态 | Zustand |
| 包管理 | pnpm 9 |

### 3.2 桌面运行时 / Rust
- **Tauri 2.x**。
- 启用插件（**仅保留实际用到的**）：`dialog`（选文件/目录）、`fs`（读产物）、`clipboard`、`log`、`notification`、`os`、`process`（管理 sidecar）、`window-state`、`updater`（可选）、`global-shortcut`（可选）。
- **不启用 / 不引入**：`enigo`、`inputbot`、`clipboard-win`、`image`、`screenshots`（键鼠控制 / 截屏类——当前邮件与 WeLink 流程用不到，按用户确认裁掉）。

主要 Cargo 依赖：
| crate | 用途 |
|---|---|
| `reqwest`（或 `ureq`） | 图片本地化下载（WeLink 云盘 / 代理） |
| `tokio` | 异步运行时、定时器、子进程 |
| `htmd`（首选）/ `html2md` | HTML → Markdown（§5.3） |
| `serde` / `serde_json` | 设置、CLI JSON 交互 |
| `chrono` | 时间格式化、按天归档 |
| `regex` | 正文/命令解析、文件名清洗 |

### 3.3 Python sidecar
- `outlook_cli.exe`：Python 3.10+，`pywin32`（win32com）、`pyinstaller` 打包。**不含** `html2text`（MD 转换上移到 Rust）。

---

## 4. 目录结构（`standalone/`）

```
standalone/
├── DESIGN.md                  # 本文档
├── README.md                  # 构建 / 运行 / 打包说明
├── package.json               # pnpm
├── next.config.js             # output: 'export'
├── tailwind.config.ts
├── tsconfig.json
├── src/                       # Next.js 前端
│   ├── app/                   # 路由（单页：邮件 / WeLink / 产物 / 设置）
│   ├── components/
│   ├── store/                 # Zustand
│   ├── lib/tauri.ts           # invoke 封装
│   └── styles/
├── src-tauri/                 # Rust 核心
│   ├── tauri.conf.json
│   ├── Cargo.toml
│   ├── capabilities/          # Tauri 2 权限
│   └── src/
│       ├── main.rs
│       ├── commands.rs        # 暴露给前端的命令
│       ├── settings.rs        # 设置读写
│       ├── store.rs           # 本地去重记录 / sessions
│       ├── email/             # 扫描、规则匹配、落盘
│       ├── welink/            # 轮询、命令录制、按天归档
│       ├── htmlmd.rs          # HTML→MD
│       ├── images.rs          # 图片本地化
│       └── output.rs          # 落盘命名 + 写文件
├── sidecar/
│   └── outlook_cli/           # Python 源 + build 脚本（产物 → outlook_cli.exe）
│       ├── outlook_cli.py     # 入口（argparse 子命令）
│       ├── outlook.py         # 复用旧 win32com 封装
│       ├── requirements.txt
│       └── build.py
└── resources/                 # 图标等
```

---

## 5. 数据流

### 5.1 邮件流
1. 用户在 UI 配规则（主题关键词 / 正文关键词 / 发件人 / 逻辑 OR·AND）、扫描文件夹、扫描间隔。
2. Rust 定时器（或手动「刷新」）→ 调 `outlook_cli list` 取摘要列表 → 规则匹配（正文关键词命中需 `outlook_cli search-body`）。
3. 对每封命中且未处理过的邮件：`outlook_cli get --entry-id …` 取 HTML 正文 + 内联附件清单。
4. Rust：图片本地化（§6）→ `htmlmd` 转 MD → `output` 落盘 HTML+MD。
5. 记入本地「已处理」集合（按 `EntryID`/合成 ID 去重）。**到此结束**，不再上传。

`.msg` / `.pst` 导入走同一后半段：`outlook_cli msg-get --path` / `outlook_cli add-pst --path` 后并入列表。

### 5.2 WeLink 流
1. UI 配监听群（group_id / group_name）、开始/结束/总结命令、轮询间隔、按天归档时间。
2. Rust 轮询：`welink-cli im query-history-message --group-id … --query-count 20`。
3. 识别命令：
   - 开始命令 → 记录 session 起点；
   - 结束命令 → 截取区间消息 → 生成 HTML；
   - 总结命令（`名 工号 日期 时间` × 1 或 2 组）→ 定位区间 → 生成 HTML；
   - 按天归档定时器 → 取全天消息 → 生成 HTML。
4. 消息渲染 HTML 沿用旧 `_msgs_to_html`（移植到 Rust）；图片本地化（§6）→ MD → 落盘。
5. 本地 `last_ids` / `sessions` 记录（替代旧 `.welink_*.json`）。**结束**，不上传。

### 5.3 HTML → Markdown（Rust 核心层）
- 首选 crate **`htmd`**；产出规则尽量对齐旧 `html2text` 配置：不忽略链接/图片、不自动换行、统一 `-` 无序列表、保留表格、合并 3+ 空行、NBSP/全角空格归一化、去掉空 `![]()`。
- 旧逻辑里 Python 侧的后处理（正则清洗）在 `htmlmd.rs` 复刻一遍。
- ⚠️ 已知：换了转换引擎，MD 细节排版会与旧版略有差异（用户已确认接受）。

---

## 6. 图片处理：转外链（可配置上传接口）

**不做本地相对路径**。沿用旧系统「上传图片 → 拿公网 URL → 写回正文」的思路，但接口由用户在设置里配置。核心规则：

> **配了上传接口 → 图片换成超链接；没配 → 产物里直接不含图片。**

### 6.1 用户配置项
- **图片上传接口 URL**（对应旧 `POST /api/image/upload`，`multipart/form-data: file` → 返回 `{success, url}`）。**留空即关闭图片功能**。
- 云盘账号 / 密码（可选）：用于 WeLink 需登录才能下载的云盘图（复刻旧 `CLOUDDRIVE_ACCOUNT/PASSWORD`）。

### 6.2 流程
- **邮件内联图（`cid:`）**：`outlook_cli get` 把 `cid:` 附件 `SaveAsFile` 到临时文件，返回 `inline_images:[{cid, path}]`。
  - 配了上传接口 → Rust 读取该临时文件 `POST` 到接口，拿到公网 URL，把 HTML 里 `cid:xxx` 改写成该 URL；MD 转换后即为正常 `![](url)`。
  - 没配 → Rust 把 HTML 里所有 `cid:` 引用及 `<img>` 去除（或置空），MD 中不出现图片。
- **WeLink 云盘图 / 文件（`um_content`）**：解析得到 `download_url` + `extraction_code`。
  - 配了上传接口 → Rust `reqwest` GET 下载字节（需登录的用云盘账号），再 `POST` 到上传接口换公网 URL，写入 `_msgs_to_html` 渲染的 `<img src>`。
  - 没配 → 该图渲染为纯文字占位（如 `[图片] 文件名`）或直接省略，不产生外链。
- 上传 / 下载失败的单张图：降级为「无图」（HTML 去引用、MD 无图），记日志告警，**不中断**整条落盘。

> 旧 `POST /api/image/proxy`（云盘下载 + 上传二合一）在单机版拆成 Rust 内「下载（云盘账号）+ 上传（用户接口）」两步，等价。

---

## 7. 本地输出规范

用户选定：**扁平 + 时间戳前缀**。

```
<输出目录>/
  20260615_1530_Re_接口联调.html
  20260615_1530_Re_接口联调.md
  20260615_1612_周报汇总.html
  20260615_1612_周报汇总.md
```

> 只产出 `.html` 与 `.md` 两类文件，无图片子目录 —— 图片走外链（§6），未配上传接口则不含图片。

- 前缀 = 邮件接收时间 / 群聊起始时间，格式 `YYYYMMDD_HHMM`（同分钟冲突追加 `_SS` 或序号）。
- 标题清洗：去掉 `\ / : * ? " < > |` 与换行，截断长度（如 60 字），空标题回退主题→会话主题→`untitled`。
- HTML 为完整文档（带 `<meta charset=utf-8>`）；MD 为 §5.3 转换结果。
- 去重：已落盘条目的源 ID 记入本地 `processed.json`，避免重复导出（可在设置里「清空已处理记录」强制重导）。

---

## 8. 设置项（全部暴露在「设置」对话框）

| 分组 | 设置项 | 旧来源 |
|---|---|---|
| 通用 | **输出目录**（选目录） | 新增（替代上传） |
| 通用 | 标题最大长度、同名冲突策略 | 新增 |
| 邮件 | 扫描文件夹列表（增删） | `scanFolders` / folder add/remove |
| 邮件 | 扫描间隔（分钟）、是否自动扫描 | `scanIntervalMinutes` |
| 邮件 | 规则列表：名称 / 主题关键词 / 正文关键词 / 发件人 / 逻辑 | `email/rules` |
| WeLink | 监听群列表（group_id / group_name） | `welink/rules` |
| WeLink | 开始 / 结束 / 总结 命令 | `welinkStartCmd/EndCmd/SummaryCmd` |
| WeLink | 轮询间隔（秒） | `welinkPollInterval` |
| WeLink | 按天归档：开关 + 触发时间 | `welinkDailyRecord/Time` |
| 图片 | **图片上传接口 URL**（留空=产物不含图片） | `FILE_SERVER` / `/api/image/upload` |
| 图片 | 云盘账号 / 密码（WeLink 需登录链接时用） | `CLOUDDRIVE_ACCOUNT/PASSWORD` |
| Outlook | `outlook_cli.exe` 路径（默认随包） | — |
| WeLink | `welink-cli` 路径（默认 PATH） | — |

设置持久化为 `settings.json`（位置：Tauri app config dir）。规则、群、文件夹等列表项也并入该文件或同目录单独文件。

---

## 9. `outlook_cli.exe` 命令行规范

统一 `stdout` 输出 JSON，失败 `exit≠0` 且 `stderr` 为 `{"error": "..."}`；`CREATE_NO_WINDOW` 隐藏黑框。复用旧 `modules/email/outlook.py` 全部函数。

| 子命令 | 参数 | 输出 |
|---|---|---|
| `folder-list` | — | `["Store\\Inbox", ...]` |
| `list` | `--folders a,b` `--count N` | 邮件摘要数组（`item_id/subject/sender_name/sender_email/received_time/conversation_topic`） |
| `search-body` | `--folders a,b` `--keywords k1,k2` | 命中 `EntryID` 数组 |
| `get` | `--entry-id ID` | 详情 + `html_body` + `inline_images:[{cid,path}]` |
| `msg-get` | `--path file.msg` | 同 `get`（合成 ID 回退） |
| `add-pst` | `--path file.pst` | `{"display_name": "..."}` |
| `remove-pst` | `--display-name N` | `{"ok": true}` |

> 与旧 `cli.py` 的差异：去掉 EWS/config/rule 子命令（规则匹配上移 Rust）；`get` 返回 `inline_images:[{cid,path}]`（cid 附件存临时文件），由 Rust 决定上传换链或剔除（§6）——旧版是 Python 内直接上传服务器。

---

## 10. 错误处理与日志
- Rust 侧统一 `log` 插件 + 前端「运行日志」面板（沿用旧 WeLink 面板的黑底日志风格）。
- 单封邮件 / 单条群聊失败不影响整体；记日志、计数、继续。
- COM 资源、子进程超时（30s）、网络下载超时（30~60s）均有兜底。

---

## 11. 打包与分发
- 前端：`pnpm build`（Next 静态导出）。
- `outlook_cli.exe`：`sidecar/outlook_cli/build.py`（PyInstaller，bundle `win32timezone`）。
- Tauri：把 `outlook_cli.exe` 作为 **sidecar 资源**打进安装包；`welink-cli` 默认从 PATH 找、设置里可覆盖。
- 产物：单个 Windows 安装包 / 便携 exe。

---

## 12. 开发里程碑（建议顺序）
1. **脚手架**：Tauri 2 + Next.js + Tailwind/Sass + Zustand 跑起空壳窗口。
2. **设置系统**：`settings.rs` + 设置对话框（输出目录、规则、群、命令）。
3. **outlook_cli.exe**：移植 `outlook.py`，实现 §9 子命令，单独可跑通。
4. **邮件流**：Rust 调 CLI → 规则匹配 → `htmlmd` → 图片本地化 → 落盘。UI 邮件面板（列表 / 刷新 / 导入 .msg/.pst）。
5. **HTML→MD + 图片本地化** 打磨（§5.3 / §6）。
6. **WeLink 流**：移植 `monitor.py` 轮询/命令/按天归档到 Rust + `_msgs_to_html`。UI WeLink 面板。
7. **产物浏览**：UI 列出输出目录、点开预览 HTML/MD。
8. **打包**：sidecar 集成 + 安装包。

---

## 13. 待确认 / 风险
- `welink-cli` 二进制不在本仓库维护，单机版假定其可用且接口不变（`im query-history-message`）。
- `htmd` 与旧 `html2text` 输出排版有差异（已接受）。
- 图片依赖**用户自配的上传接口**（旧 `/api/image/upload` 同款）。未配 → 产物无图；配了但接口/云盘鉴权失败 → 该图降级为无图并告警。
```