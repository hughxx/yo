# CoreInsight Local Toolkit

CoreInsight Local Toolkit 是运行在用户电脑上的**本地工具服务**（local companion
service）。它不是插件，也不是面向用户操作的 CLI：正式域名上的 CoreInsight 前端通过
HTTP 调用它，由它访问只能在本机使用的 WeLink CLI、Outlook 等能力。最终只有一个常驻
Python exe，不部署本项目自己的云端 Server，也不做完整桌面 UI。

当前第一阶段只包含 WeLink 聊天记录：

- 本地保存群组配置；
- 按时间范围从 `welink-cli` 分页读取群消息；
- 将消息标准化后返回给浏览器预览；
- 按 `msgId` 应用全选排除或明确选择，原始正文不经浏览器传递；
- EXE 下载图片、上传到公开图片服务，并生成 `![OCR结果](公开URL)` Markdown；
- workspace file-server 只传递转换好的 Markdown 和 `SKILL.md`；
- Hermes Remote Agent 通过 Skill 处理超长 Markdown，并保留图片超链接；
- 提供健康检查和能力声明。

提取支持直接写入经验引擎和生成平台待审核草稿。Skill 不感知入库模式，统一负责经验的提取、合并和更新；
Local Toolkit 根据 `extractMode` 与 Skill 返回的 `doc_id` 路由到经验接口或 GaussDB 草稿表。定时任务支持每天、每周、每月
和五字段 Cron，并在本机持久化。只有提取和入库成功后才推进增量起点，失败会在下次重试。

## 为什么叫 Local Toolkit

它是正式域名网页与本机能力之间的长期驻留桥梁，后续还会承载 Outlook、自动更新、托盘和
调度。`coreinsight-local-toolkit` 比 `plugin`、`cli` 或 `desktop-ui` 更准确，也给后续扩展留
出了空间。

## 开发运行

```powershell
cd coreinsight-local-toolkit
python -m pip install -r requirements.txt
python -m coreinsight_local_toolkit
```

默认监听 `http://127.0.0.1:17831`。健康检查：

```text
GET http://127.0.0.1:17831/health
```

本地配置和运行数据默认写入 `D:\CoreInsight\LocalToolkit`，滚动日志位于
`D:\CoreInsight\LocalToolkit\logs\toolkit.log`（单文件 5 MB，保留 5 个备份）。日志不记录
完整聊天正文、密码或 API Key。提取日志包含 taskId、群组、消息计数、Hermes runId、经验
docId、入库结果和异常堆栈。
转换完成的聊天 Markdown 会长期保存在
`D:\CoreInsight\LocalToolkit\markdown\<groupId>\<workspaceId>`。文件内容与上传到远端
workspace 的输入一致，包含 OCR 结果和永久图片链接；本地副本不会随远端 workspace 清理自动删除。

演示前端直接访问 `http://127.0.0.1:17831/demo/`，不需要另外启动 Node 服务。

可通过环境变量配置：

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `COREINSIGHT_AGENT_PORT` | `17831` | 本地端口 |
| `COREINSIGHT_TOOLKIT_DATA_DIR` | `D:\CoreInsight\LocalToolkit` | 配置、定时状态和日志目录；不默认写入 C 盘 |
| `COREINSIGHT_AGENT_DATA_DIR` | 空 | 旧版数据目录环境变量，仅作为兼容回退 |
| `COREINSIGHT_ALLOWED_ORIGINS` | 空 | 追加到默认白名单的网页 Origin，多个值用逗号分隔 |
| `COREINSIGHT_WELINK_CLI` | `welink-cli` | WeLink CLI 可执行文件名或绝对路径 |
| `COREINSIGHT_UPLOAD_BY` | 空 | 兼容旧调用的默认用户工号；正式调用由前端在请求中传 `uploadBy` |
| `COREINSIGHT_HERMES_URL` | `http://7.183.107.92:31454` | Hermes Remote Agent 网关 |
| `COREINSIGHT_HERMES_API_KEY` | 内部开发 Key | Hermes Bearer Token |
| `COREINSIGHT_WORKSPACE_FILE_SERVER_URL` | `http://7.183.107.92:30864` | 共享 workspace 文件服务 |
| `COREINSIGHT_HERMES_TIMEOUT_SECONDS` | `1800` | 单次 Skill 最长等待时间 |
| `COREINSIGHT_PORTAL_URL` | `https://coreinsight.rnd.huawei.com` | 悬浮图标“云见主页”的地址 |
| `COREINSIGHT_EMAIL_URL` | 同云见主页 | “邮件提取”的正式前端地址 |
| `COREINSIGHT_CHAT_URL` | `http://127.0.0.1:17831/demo/` | “聊天记录提取”的前端地址 |
| `COREINSIGHT_TRAY_ENABLED` | `1` | Windows 托盘；设为 `0` 可用于无桌面调试 |
| `COREINSIGHT_UPDATE_CONFIG_URL` | Fuyao `selectConfigByKey` | 配置中心查询接口 |
| `COREINSIGHT_UPDATE_CONFIG_KEY` | `coreinsight_local_toolkit_release` | 版本配置 key；任一项为空时关闭检查 |
| `COREINSIGHT_UPDATE_ENABLED` | `1` | 设为 `0` 时关闭自动更新，用于故障排查 |
| `COREINSIGHT_EXPERIENCE_ENGINE_URL` | `https://fuyao.rnd.huawei.com` | 经验引擎基址，或以 `/memory/experience/doc` 结尾的新建接口地址 |
| `COREINSIGHT_DRAFT_DB_HOST` | `gauss.mlops.rnd.huawei.com` | 平台草稿 GaussDB 地址 |
| `COREINSIGHT_DRAFT_DB_PORT` | `8000` | 平台草稿 GaussDB 端口 |
| `COREINSIGHT_DRAFT_DB_NAME` | `mlops` | 平台草稿数据库名 |
| `COREINSIGHT_DRAFT_DB_SCHEMA` | `coreinsight` | 草稿表 schema |
| `COREINSIGHT_DRAFT_DB_USER` | 无 | 仅在编译机器上使用，打包时嵌入草稿库账号 |
| `COREINSIGHT_DRAFT_DB_PASSWORD` | 无 | 仅在编译机器上使用，打包时嵌入草稿库密码 |
| `COREINSIGHT_OCR_URL` | `http://10.90.113.228:5678/ocr` | OCR 接口完整地址 |
| `COREINSIGHT_FILE_SERVER_URL` | `http://7.224.100.105:32169` | 永久图片上传服务 |
| `COREINSIGHT_RAG_PIC_PUBLIC_BASE` | `https://fuyao-data-server.rnd.huawei.com` | Markdown 图片公开地址 |
| `COREINSIGHT_CLOUDDRIVE_ACCOUNT` | 空 | WeLink 附件下载账号 |
| `COREINSIGHT_CLOUDDRIVE_PASSWORD` | 空 | WeLink 附件下载密码 |

## 浏览器接入

浏览器请求基址为 `http://127.0.0.1:17831`（不要使用 `0.0.0.0`）。服务端仅绑定回环
地址，并严格校验浏览器 `Origin`。旧版 Private Network Access 预检所需响应头也已处理。
较新的浏览器会对公网网页访问本机服务显示 Local Network Access 权限提示，用户需要允
许当前 CoreInsight 域名访问本机网络。

正式前端需为非简单请求使用 `Content-Type: application/json`，并可在支持的浏览器中给
`fetch` 增加 `targetAddressSpace: "loopback"`。生产部署前应确认页面所在域名已加入
`COREINSIGHT_ALLOWED_ORIGINS`；不建议使用 `*`。前端还应区分“未安装/未启动”和“用户
拒绝本地网络权限”两类错误。

## 当前 API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 存活状态 |
| GET | `/capabilities` | 当前可用能力 |
| GET | `/version` | 当前版本与版本检查配置状态 |
| POST | `/update/check` | 按 HTTPS 清单检查新版本，不自动下载安装 |
| GET | `/welink/cli/status` | 探测 `welink-cli` 是否安装且当前登录可正常查询 |
| GET | `/welink/skill/list` | 用户可选择的提取 Skill |
| GET | `/welink/group/list` | 群组列表 |
| POST | `/welink/group/add` | 添加群组 |
| PUT | `/welink/group/update` | 更新群组配置 |
| DELETE | `/welink/group/delete` | 删除群组 |
| POST | `/welink/message/list` | 获取时间范围内的聊天记录 |
| POST | `/welink/message/page` | 游标分页预览聊天记录（推荐） |
| POST | `/welink/extract` | 本地读取和 msgId 过滤，提交 workspace Skill 并入库 |
| GET | `/welink/extract/status` | 按 `taskId` 或 `groupId` 查询任务状态 |
| GET | `/welink/extract/tasks` | 查询本进程的提取任务列表 |
| POST | `/welink/extract/cancel` | 按 `taskId` 或 `groupId` 取消任务 |
| POST | `/welink/schedule/set` | 新增或修改本地定时提取 |
| POST | `/welink/schedule/cancel` | 取消本地定时提取 |

日期时间字段统一返回 `YYYY-MM-DD HH:mm:ss`。请求兼容空格或 `T` 分隔的 ISO 8601 字符串及可选时区；不带时区时按本机时区解释。消息查询是阻塞型
本地操作，FastAPI 会在线程池中执行，不阻塞健康检查。`/welink/message/page` 每页最多
返回 100 条，并返回 `nextCursor` 和 `hasMore`；前端不应把全部聊天正文一次加载进浏览
器。WeLink 返回的 `msgTotalCount` 实际是当前页条数，不是会话历史总数，因此协议中的
`totalHint` 固定为 0，仅为兼容已接入的前端保留。

提取任务按群组防重复：同群组已有未结束任务时返回 409，不同群组的任务均可提交。
LocalToolkit 使用单 worker 按提交顺序执行，尚未执行的任务状态为 `queued`。

提取请求只携带 `skillId`，不再向用户暴露 Prompt 或 CodeAgent。聊天 Markdown 以约
40,000 字符为目标自动分片，但只在完整消息边界切分；文件名使用
`input/000001_<起止时间>.md` 形式保证顺序。单条消息超过目标大小时单独占一个文件。

手动提取每次创建新的临时 workspace，成功或失败后删除；同一个定时任务使用由
`用户 + 群组 + Skill + 入库模式` 确定的固定 workspace 和 Hermes session，只追加本轮增量输入。
workspace 里只有一个结果文件 `output/experiences.jsonl`，每行是一条完整经验版本。新经验
不带 `doc_id`，Local Toolkit 通过 POST 新建并将接口返回的真实 `doc_id` 写回该行；后续聊天
补充同一经验时，Skill 使用原 `doc_id` 追加合并后的新版本，Local Toolkit 通过 PUT 部分更新。
每个定时 workspace 的下一个分片序号和已入库行号仅在本机持久化，失败不会越过未成功的
输入或输出。定时批次成功后会删除本轮输入 Markdown，并把 `experiences.jsonl` 压缩为每个
`doc_id` 的最新完整版本；失败时保留输入供重试。该清理依赖 file-server 的
`DELETE /api/workspaces/{workspace_id}/path` 接口。

图片在进入 workspace 前已经上传到永久图片服务，Markdown 中是
`![OCR结果](公开URL)`，Skill 必须在最终经验中原样保留 OCR alt 文本和 URL。删除手动
workspace 不会删除已经进入经验正文的永久图片。

取消任务时 EXE 会调用 Hermes stop 接口，并保证不会继续写入经验引擎。

草稿模式下，新经验使用本地生成的 32 位 UUID 作为 `t_experience_draft.id`，并回写为 Skill 后续可见的
`doc_id`。同一定时 workspace 后续产生同一 `doc_id` 时，Skill 给出合并后的字段，Toolkit 只更新明确返回的
`title/summary/experience/scene/scene_id`，同时把状态重置为 `pending`；若草稿已被审核流程移走，则用相同 ID
重新建立待审核草稿。`title` 与 `llm_title` 始终同步，`summary` 写入 `llm_description`，`experience` 写入
`llm_content`，`rag_search_text` 在草稿模式下直接丢弃。

打包前在编译机器的系统环境变量中设置 `COREINSIGHT_DRAFT_DB_USER` 和
`COREINSIGHT_DRAFT_DB_PASSWORD`。`build.ps1` 缺少任一变量都会停止构建；构建时会生成被 Git 忽略的临时
`_build_secrets.py` 并将值嵌入 EXE，构建结束后立即删除临时文件。最终用户电脑不需要配置这两个环境变量。

## 桌面悬浮图标、托盘与版本检查

Windows 用户双击 EXE 后，桌面右侧会显示旧版 CoreInsight 蓝紫色悬浮图标。图标可拖动，
左键打开云见主页；右键菜单包含云见主页、邮件提取、聊天记录提取、关于、隐藏和退出。
隐藏只收起悬浮图标，本地服务继续运行，可从系统托盘的“显示悬浮图标”恢复。系统托盘还
提供日志目录和版本检查入口。

启动后会自动检查一次版本。Toolkit 调用配置中心
`selectConfigByKey?key=coreinsight_local_toolkit_release`，并将返回的 `data.configVal` 解析为：

```json
{
  "enabled": true,
  "latestVersion": "0.3.0",
  "minimumSupportedVersion": "0.2.0",
  "forceUpdate": false,
  "downloadUrl": "https://example.com/coreinsight-local-toolkit.exe",
  "sha256": "64位十六进制SHA-256",
  "releaseNotes": ["更新说明第一条", "更新说明第二条"]
}
```

当前版本低于 `minimumSupportedVersion` 时强制更新；或者 `forceUpdate=true` 且当前版本低于
`latestVersion` 时强制更新。其余版本差异仅提示普通更新。仅当发现新版本时才要求 HTTPS
下载地址及合法 SHA-256。普通更新由用户在“检查更新”中确认；强制更新会暂停 WeLink 业务
接口并自动下载。安装包下载到 `D:\CoreInsight\LocalToolkit\updates`，SHA-256 校验通过后由
外部更新脚本等待旧进程退出、覆盖原 EXE 并自动重启。升级日志写入
`D:\CoreInsight\LocalToolkit\logs\updater.log`。

版本接口包括 `POST /update/check`、`GET /update/status` 和 `POST /update/install`。SHA-256
可以防止下载损坏或被替换；正式发布仍建议再对 EXE 添加企业代码签名。
可直接复制 `release-config.example.json` 到配置中心，发布时只需替换其中的 HTTPS 直链。
直链必须允许 Toolkit 不依赖浏览器 Cookie 直接下载。`0.3.0` 是首个具备自动替换能力的版本，
从更旧版本迁入时仍需手动安装一次；之后的版本即可自动升级。

## 打包

在 PowerShell 中执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build.ps1
```

也可以直接双击项目根目录的 `build.bat`。

脚本在项目 D 盘目录创建隔离的 `.build-venv` 和 `.pyinstaller-cache`，产物为
`dist\coreinsight-local-toolkit.exe`。这是无控制台、带桌面悬浮图标和托盘的单文件 exe；
运行时解压目录固定
为 `D:\CoreInsight\LocalToolkit\runtime`，不会使用用户 C 盘 `%TEMP%`。
