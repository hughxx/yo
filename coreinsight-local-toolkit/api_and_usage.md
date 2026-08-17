# CoreInsight LocalToolkit 接口与使用说明

本文档面向正式前端联调，描述 LocalToolkit 当前提供的 HTTP 接口及推荐调用顺序。

## 1. 基本约定

- 本地服务默认地址：`http://127.0.0.1:17831`
- 正式前端必须使用绝对地址访问本地服务，不能使用当前网页域名的相对路径。
- 请求和响应编码均为 UTF-8 JSON。
- 日期时间统一使用 `YYYY-MM-DD HH:mm:ss`，请求也兼容 ISO 8601 的 `T`、毫秒、时区及 `Z`。
- `scheduleTime` 使用 `HH:mm:ss`。
- 浏览器请求来源必须在 LocalToolkit 的 CORS 白名单中。
- 所有成功接口的 HTTP 状态统一为 `200`，信封中的 `code=200`、`msg=ok`、`data=业务数据`。
- 错误接口保留 `409/422/426/502/500` 等 HTTP 状态，信封中的 `code` 与 HTTP 状态相同、`msg` 为错误原因、`data=null`。
- 提取接口成功仅表示任务已经受理，提取结果需要继续查询 `data` 中任务的状态。

## 2. 推荐页面初始化顺序

1. `GET /health`：确认本地服务已启动。
2. `GET /welink/cli/status`：确认 WeLink CLI 已安装并可用。
3. `GET /welink/skill/list`：获取用户可选择的 Skill。
4. `GET /welink/group/list`：获取本地已绑定群组及配置。
5. `GET /welink/extract/tasks`：恢复未结束任务及页面任务状态。

群组列表来自 LocalToolkit 本地配置，不会自动同步平台上的群组。首次使用必须先调用群组添加接口。

## 3. 服务状态

### `GET /health`

成功响应：

```json
{
  "status": "ok",
  "service": "coreinsight-local-toolkit",
  "version": "0.4.0"
}
```

### `GET /capabilities`

返回当前版本支持的能力开关。

### `GET /welink/cli/status`

LocalToolkit 会执行一次只查询一条最近会话的 WeLink CLI 探测命令，但不会把会话内容返回前端。

```json
{
  "installed": true,
  "ready": true,
  "message": "WeLink CLI 已安装且可用",
  "conversationCount": 1
}
```

- `installed=false`：没有找到 `welink-cli` 命令。
- `installed=true, ready=false`：命令存在，但登录状态、权限或执行结果异常。
- `ready=true`：可以继续预览和提取聊天记录。

## 4. Skill

### `GET /welink/skill/list`

返回可用 Skill 数组。保存群组配置、手动提取和设置定时任务时，都应提交所选 Skill 的 `id` 作为 `skillId`。

## 5. 群组管理

### `GET /welink/group/list`

返回本地绑定的群组数组。主要字段：

| 字段 | 含义 |
|---|---|
| `groupId` | WeLink 群组 ID |
| `name` | 用户设置的显示名称 |
| `status` | `idle`、`extracting` 或 `scheduled`；排队中的任务也显示为 `extracting` |
| `extractMode` | `direct` 或 `draft` |
| `skillId` | 当前选择的 Skill |
| `startTime` / `endTime` | 手动提取时间范围 |
| `quickRange` | `all`、`7d`、`3d`、`2d`、`today`、`custom` |
| `scheduleEnabled` | 是否已启用定时提取 |
| `scheduleSince` | 用户设置的首次增量起点 |
| `scheduleCursor` | 当前成功增量游标；正式前端应展示此字段 |
| `scheduleLastRun` | 兼容字段，与 `scheduleCursor` 同步 |
| `scheduleNextRun` | 下次计划执行时间 |

### `POST /welink/group/add`

请求：

```json
{
  "groupId": "986359484802794599",
  "name": "云核小鲁班接口对接"
}
```

成功返回 `201` 和完整群组对象。同一 `groupId` 重复添加返回 `409`。

### `PUT /welink/group/update`

提交完整群组对象。该接口不是局部更新；前端应以 `/welink/group/list` 返回的对象为基础修改后整体提交。

LocalToolkit 会更新用户可编辑配置，不接受前端直接篡改运行状态和定时运行游标。

### `DELETE /welink/group/delete`

请求：

```json
{
  "groupId": "986359484802794599"
}
```

成功返回 `204`。该群组存在未结束提取任务时返回 `409`；应先定向取消任务。

## 6. 消息预览

推荐使用分页接口，不建议正式前端使用一次性全量接口。

### `POST /welink/message/page`

第一次请求：

```json
{
  "groupId": "986359484802794599",
  "startTime": "2026-08-10 00:00:00",
  "endTime": "2026-08-17 23:59:59",
  "cursor": "",
  "limit": 100
}
```

响应：

```json
{
  "items": [
    {
      "id": "89326107894305406",
      "sender": "z30073732",
      "time": "2026-08-12 17:29:17",
      "content": "消息内容",
      "checked": true,
      "contentType": "TEXT_MSG",
      "timestamp": 1786522157886
    }
  ],
  "nextCursor": "89326107894305406",
  "hasMore": true,
  "totalHint": 0
}
```

点击“加载更早消息”时，将上一次响应的 `nextCursor` 原样传入下一次请求。`hasMore=false` 时停止加载。`totalHint` 不表示完整历史总数，不能用于判断是否已经加载全部消息。

### `POST /welink/message/list`

请求字段为 `groupId`、`startTime`、`endTime`，响应直接是消息数组。该接口会遍历指定时间范围内的全部消息，数据量较大时耗时和内存占用更高，仅保留作兼容用途。

## 7. 消息选择规则

提取接口只提交消息 ID 选择条件，不需要把完整消息正文传给后端。

全部提取，仅排除用户取消勾选的消息：

```json
{
  "mode": "all",
  "excludedMessageIds": ["msg-2", "msg-5"],
  "selectedMessageIds": []
}
```

只提取用户明确选择的消息：

```json
{
  "mode": "explicit",
  "excludedMessageIds": [],
  "selectedMessageIds": ["msg-1", "msg-3"]
}
```

`mode=all` 时 LocalToolkit 会在提取阶段重新分页读取完整时间范围，因此即使前端只预览了部分消息，也可以执行全量提取。

## 8. 手动提取与任务队列

### 队列规则

- 同一个群组只能有一个未结束任务；重复提交返回 `409`。
- 不同群组可以连续提交，均返回 `202`。
- LocalToolkit 默认只有一个实际执行 worker，任务按提交顺序执行。
- 等待执行的任务状态为 `queued`，不会因为其他群组正在执行而返回 `409`。
- 每个任务有独立 `taskId`、进度、结果和取消信号。

### `POST /welink/extract`

请求：

```json
{
  "groupId": "986359484802794599",
  "startTime": "2026-08-10 00:00:00",
  "endTime": "2026-08-17 23:59:59",
  "skillId": "welink-experience-extractor",
  "extractMode": "direct",
  "uploadBy": "w00899061",
  "selection": {
    "mode": "all",
    "excludedMessageIds": [],
    "selectedMessageIds": []
  }
}
```

- `uploadBy` 必须由正式前端传入当前登录用户账号；Demo 暂时固定为 `w00899061`。
- `extractMode=direct`：经验直接写入经验中心。
- `extractMode=draft`：写入待审核草稿。
- 已启用定时提取的同一群组，开始手动提取前必须先取消定时任务。

成功返回 HTTP `200`，任务对象位于信封的 `data` 中。前端必须保存其中的 `taskId`。

```json
{
  "running": true,
  "taskId": "9eac...",
  "groupId": "986359484802794599",
  "scheduled": false,
  "status": "queued",
  "scanned": 0,
  "selected": 0,
  "message": "任务已排队",
  "error": "",
  "docId": "",
  "title": ""
}
```

任务状态：

| `status` | 含义 | 是否结束 |
|---|---|---|
| `queued` | 已受理，等待本地 worker | 否 |
| `fetching` | 正在读取和筛选 WeLink 消息 | 否 |
| 其他处理中状态 | 正在生成 Markdown、上传或执行 Skill | 否 |
| `done` | 成功完成 | 是 |
| `failed` | 执行失败，查看 `error` | 是 |
| `cancelled` | 已取消 | 是 |

兼容字段 `running` 表示“任务尚未结束”，所以 `queued` 时也是 `true`。

### `GET /welink/extract/status`

推荐精确查询：

- 按任务：`GET /welink/extract/status?taskId=<taskId>`
- 按群组最近任务：`GET /welink/extract/status?groupId=<groupId>`

任务不存在返回 `404`。

不传查询参数时，为兼容旧 Demo，返回当前正在执行的任务；没有正在执行的任务时返回最近更新的任务或 `idle` 对象。正式前端不应依赖这个无参数查询管理多个群组。

### `GET /welink/extract/tasks`

返回任务对象数组，包括所有未结束任务以及本次 LocalToolkit 进程保留的近期已结束任务。页面初始化时用它恢复各群组任务状态。

### `POST /welink/extract/cancel`

推荐按任务取消：

```json
{
  "taskId": "9eac..."
}
```

也可以按群组取消该群组的未结束任务：

```json
{
  "groupId": "986359484802794599"
}
```

- 取消 `queued` 任务会立即变成 `cancelled`。
- 取消正在执行的任务，会在当前网络请求返回后尽快停止。
- 任务不存在返回 `404`。
- 空对象仅为旧 Demo 兼容，会取消当前实际执行任务；正式前端不要使用空对象。

## 9. 定时提取

### `POST /welink/schedule/set`

```json
{
  "groupId": "986359484802794599",
  "uploadBy": "w00899061",
  "skillId": "welink-experience-extractor",
  "extractMode": "direct",
  "scheduleFreq": "daily",
  "scheduleTime": "09:00:00",
  "scheduleCron": "",
  "since": "2026-08-17 10:00:00"
}
```

- `scheduleFreq` 支持 `daily`、`weekly`、`monthly`、`custom`。
- `custom` 使用 5 段 Cron：`分 时 日 月 星期`。
- 首次设置时提交 `since`；第一次读取 `(since, 本次触发时间]`。
- 后续每次读取 `(scheduleCursor, 本次触发时间]`，固定处理窗口内全部消息，不使用手动预览的 `selection`。
- 成功或窗口内没有新消息时推进 `scheduleCursor`；失败、取消时不推进。
- 修改频率但不重置进度时省略 `since`；重新提交 `since` 会重置游标，可能重复提取。
- 前端建议把“指定时间范围”和“定时增量”作为互斥模式；定时模式只显示 since、频率和执行时间。
- 到期后创建普通队列任务；其他群组正在提取时，该任务进入 `queued`。
- 同一群组已有手动或定时任务未结束时，设置定时配置返回 `409`。

### `POST /welink/schedule/cancel`

```json
{
  "groupId": "986359484802794599"
}
```

取消计划，并取消该群组尚未结束的定时提取任务；不会取消该群组的手动任务。

## 10. 更新接口

- `GET /version`：当前版本和更新配置状态。
- `POST /update/check`：立即检查配置中心版本。
- `GET /update/status`：获取版本检查、下载和安装状态。
- `POST /update/install`：下载并安装当前可用更新，成功受理返回 `202`。

强制更新生效后，`/capabilities` 及所有 `/welink/*`、`/email/*` 业务接口返回 `426`，响应中包含更新状态。

## 11. Outlook 邮件接口

邮件页面初始化依次调用 `GET /email/status`、`GET /email/config`、
`GET /email/skill/list`，用户刷新文件夹时调用 `GET /email/folder/list`。

- `PUT /email/config`：保存文件夹、规则、黑名单、Skill、入库方式和用户工号。
- `POST /email/message/list`：按文件夹、时间、搜索词和规则状态分页读取摘要。
- `POST /email/message/get`：读取单封正文用于预览，不上传附件。
- `POST /email/extract`：只提交 Outlook EntryID 选择条件，启动本地邮件 Skill 提取。
- `GET /email/extract/status`：轮询手动或定时邮件任务。
- `GET /email/extract/tasks`：获取近期邮件任务。
- `POST /email/extract/cancel`：取消当前邮件任务。
- `POST /email/schedule/set`：设置邮件定时增量任务，首次或重置时传 `since`。
- `POST /email/schedule/cancel`：取消邮件定时任务并保留游标。

邮件正式提取由 EXE 重新读取正文和附件。图片执行 OCR 并写成
`![OCR结果](公开URL)`，普通附件写成 `[文件名](公开URL)`；生成的 Markdown
按固定大小分块后进入邮件 Skill。定时窗口为 `(scheduleCursor, 本次触发时间]`，
只有 Outlook 读取、Skill 和最终入库全部成功才推进游标。

完整请求字段和前端调用时机见 `front_api.txt`。

## 12. 常见错误

| HTTP 状态 | 常见原因 |
|---|---|
| `403` | 网页 Origin 不在白名单中 |
| `404` | 群组尚未绑定、任务不存在或请求到了旧版本服务 |
| `409` | 同群组已有未结束任务、定时状态冲突或重复添加群组 |
| `422` | 请求字段缺失、时间格式错误、Skill/账号配置无效 |
| `426` | 当前版本被强制停止，必须升级 |
| `502` | WeLink CLI、Hermes、文件服务或其他下游调用失败 |
| `503` | Outlook 未安装、未登录或 COM 访问组件不可用 |

遇到问题时应同时记录：请求 URL、HTTP 方法、请求体、状态码和响应中的 `detail`。仅凭状态码无法区分具体原因。
