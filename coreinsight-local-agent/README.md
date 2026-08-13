# CoreInsight Local Agent

CoreInsight Local Agent 是运行在用户电脑上的**本地伴生服务**（local companion
service）。它不是插件，也不是面向用户操作的 CLI：正式域名上的 CoreInsight 前端通过
HTTP 调用它，由它访问只能在本机使用的 WeLink CLI、Outlook 等能力。最终只有一个常驻
Python exe，不部署本项目自己的云端 Server，也不做完整桌面 UI。

当前第一阶段只包含 WeLink 聊天记录：

- 本地保存群组配置；
- 按时间范围从 `welink-cli` 分页读取群消息；
- 将消息标准化后返回给浏览器预览；
- 按 `msgId` 应用全选排除或明确选择，原始正文不经浏览器传递；
- 在 EXE 内生成 Markdown、处理附件/OCR、调用模型并写入经验引擎；
- 提供健康检查和能力声明。

定时任务和草稿审核尚未接入。前端应先读取 `/capabilities`，不要在能力为 `false` 时
展示可执行状态；当前提取仅支持 `extractMode=direct`。

## 为什么叫 Local Agent

它是正式域名网页与本机能力之间的长期驻留桥梁，后续还会承载 Outlook、自动更新、托盘和
调度。`coreinsight-local-agent` 比 `plugin`、`cli` 或 `desktop-ui` 更准确，也给后续扩展留
出了空间。

## 开发运行

```powershell
cd coreinsight-local-agent
python -m pip install -r requirements.txt
python -m coreinsight_local_agent
```

默认监听 `http://127.0.0.1:17831`。健康检查：

```text
GET http://127.0.0.1:17831/health
```

演示前端直接访问 `http://127.0.0.1:17831/demo/`，不需要另外启动 Node 服务。

可通过环境变量配置：

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `COREINSIGHT_AGENT_PORT` | `17831` | 本地端口 |
| `COREINSIGHT_AGENT_DATA_DIR` | `%LOCALAPPDATA%/CoreInsight/LocalAgent` | 配置目录 |
| `COREINSIGHT_ALLOWED_ORIGINS` | beta/正式 CoreInsight 域名 | 逗号分隔的网页来源白名单 |
| `COREINSIGHT_WELINK_CLI` | `welink-cli` | WeLink CLI 可执行文件名或绝对路径 |
| `COREINSIGHT_UPLOAD_BY` | 空 | 写入经验引擎的默认用户工号 |
| `COREINSIGHT_LLM_BASE_URL` | 空 | OpenAI 兼容模型网关基地址 |
| `COREINSIGHT_LLM_API_KEY` | 空 | 模型网关密钥，仅保存在本机 |
| `COREINSIGHT_LLM_MODEL_ID` | 空 | 模型 ID |
| `COREINSIGHT_EXPERIENCE_ENGINE_URL` | 空 | 经验引擎写入接口完整地址 |
| `COREINSIGHT_OCR_URL` | 空 | OCR 接口完整地址 |
| `COREINSIGHT_FILE_SERVER_URL` | 空 | 图片上传服务基地址 |
| `COREINSIGHT_RAG_PIC_PUBLIC_BASE` | 空 | 图片公开访问基地址 |
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
| GET | `/welink/group/list` | 群组列表 |
| POST | `/welink/group/add` | 添加群组 |
| PUT | `/welink/group/update` | 更新群组配置 |
| DELETE | `/welink/group/delete` | 删除群组 |
| POST | `/welink/message/list` | 获取时间范围内的聊天记录 |
| POST | `/welink/message/page` | 游标分页预览聊天记录（推荐） |
| POST | `/welink/extract` | 本地读取、msgId 过滤、Markdown/OCR、模型提取及入库 |
| GET | `/welink/extract/status` | 查询本地提取任务状态 |
| POST | `/welink/extract/cancel` | 请求取消当前任务 |

日期字段接受带时区的 ISO 8601 字符串；不带时区时按本机时区解释。消息查询是阻塞型
本地操作，FastAPI 会在线程池中执行，不阻塞健康检查。`/welink/message/page` 每页最多
返回 100 条，并返回 `nextCursor` 和 `hasMore`；前端不应把全部聊天正文一次加载进浏览
器。WeLink 返回的 `msgTotalCount` 实际是当前页条数，不是会话历史总数，因此协议中的
`totalHint` 固定为 0，仅为兼容已接入的前端保留。

## 打包方向

最终可用 PyInstaller 打成无控制台窗口的单文件 exe，并由登录启动项或 Windows 服务
负责常驻。首阶段开发时保留控制台，便于定位 `welink-cli` 登录态和跨域问题；无需再做
完整桌面 UI，最多保留托盘菜单（状态、打开网页、退出）。
