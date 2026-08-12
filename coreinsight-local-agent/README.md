# CoreInsight Local Agent

CoreInsight Local Agent 是运行在用户电脑上的**本地伴生服务**（local companion
service）。它不是插件，也不是面向用户操作的 CLI：正式域名上的 CoreInsight 前端通过
HTTP 调用它，由它访问只能在本机使用的 WeLink CLI、Outlook 等能力。

当前第一阶段只包含 WeLink 聊天记录：

- 本地保存群组配置；
- 按时间范围从 `welink-cli` 分页读取群消息；
- 将消息标准化后返回给浏览器预览；
- 提供健康检查和能力声明。

提取入库和定时任务尚未接入。前端应先读取 `/capabilities`，不要在能力为 `false` 时
展示可执行状态。

## 为什么叫 Local Agent

它是云端网页与本机能力之间的长期驻留桥梁，后续还会承载 Outlook、自动更新、托盘和
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

日期字段接受带时区的 ISO 8601 字符串；不带时区时按本机时区解释。消息查询是阻塞型
本地操作，FastAPI 会在线程池中执行，不阻塞健康检查。

## 打包方向

最终可用 PyInstaller 打成无控制台窗口的单文件 exe，并由登录启动项或 Windows 服务
负责常驻。首阶段开发时保留控制台，便于定位 `welink-cli` 登录态和跨域问题；无需再做
完整桌面 UI，最多保留托盘菜单（状态、打开网页、退出）。
