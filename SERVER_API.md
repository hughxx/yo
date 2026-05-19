# 自建服务器接口文档

本文档说明若用户希望自行搭建后端服务，需要实现的所有接口及相关配置。

---

## 一、客户端如何配置服务器地址

客户端在设置界面填写「服务器地址」（对应配置项 `backendUrl`），保存后所有请求均发往该地址。

默认值：`https://coreinsight-beta.rnd.huawei.com/collection`

客户端启动时会调用 `GET /api/config/ping` 检测连通性，返回 `{"Success": true}` 即视为在线。

---

## 二、需要实现的接口一览

### 2.1 全局配置模块 `/api/config`

#### `GET /api/config/ping`
健康检查，客户端用于检测服务器是否在线。

**响应**
```json
{ "Success": true, "Message": "pong" }
```

---

#### `GET /api/config/namespaces`
获取服务器上所有命名空间（知识库分区）列表，客户端在设置页展示供用户选择。

**响应**
```json
[
  { "id": 1, "name": "my-team", "description": "我的团队知识库" }
]
```

---

#### `GET /api/config/userinfo?info=<query>`
搜索用户信息，用于规则编辑时自动补全发件人。各服务器可对接自己的用户目录，也可返回空数组。

**响应**
```json
[
  { "label": "张三", "value": "zhang.san" }
]
```

---

### 2.2 邮件模块 `/api/email`

#### `POST /api/email/receive`
客户端将 Outlook 邮件内容推送到服务器，服务器后台异步解析并存入知识库。

**请求体（JSON）**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `ConversationTopic` | string | 是 | 邮件会话主题，作为去重 key |
| `Subject` | string | 否 | 邮件主题 |
| `SenderName` | string | 否 | 发件人姓名 |
| `ReceivedTime` | string | 否 | 接收时间（ISO 格式） |
| `HtmlBody` | string | 否 | 邮件 HTML 正文 |
| `UploadBy` | string | 否 | 上传者用户 ID |
| `Namespace` | string | 否 | 目标命名空间（知识库分区） |
| `Force` | bool | 否 | 为 true 时强制重新处理已存在的邮件 |

**响应**
```json
{ "Success": true, "Message": "ok" }
```

---

#### `POST /api/email/parse_status`
批量查询若干邮件在指定命名空间下的处理状态，客户端用于在邮件列表中展示「已解析 / 处理中 / 失败」标记。

**请求体（JSON）**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `topics` | string[] | 是 | 邮件会话主题列表 |
| `namespace` | string | 是 | 命名空间名称 |

**响应**（key 为 topic，value 为状态字符串 `pending` / `done` / `failed`）
```json
{
  "主题A": "done",
  "主题B": "pending"
}
```

---

#### `GET /api/email/rules?namespace=<name>`
获取指定命名空间下的过滤规则列表。

**响应**
```json
[
  {
    "id": 1,
    "name": "规则名",
    "keywords": ["关键词1"],
    "body_keywords": ["正文关键词"],
    "senders": ["zhang.san@example.com"],
    "logic": "OR",
    "enabled": true
  }
]
```

---

#### `POST /api/email/rules`
创建过滤规则。

**请求体（JSON）**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `namespace` | string | 是 | 命名空间名称 |
| `name` | string | 是 | 规则名称 |
| `keywords` | string[] | 否 | 主题关键词（默认 `[]`） |
| `body_keywords` | string[] | 否 | 正文关键词（默认 `[]`） |
| `senders` | string[] | 否 | 发件人过滤（默认 `[]`） |
| `logic` | string | 否 | 匹配逻辑 `OR` 或 `AND`（默认 `OR`） |

**响应**：返回创建后的规则对象（同 GET 列表单项格式）。

---

#### `PUT /api/email/rules/{rule_id}`
更新规则（部分字段，只传需要修改的字段）。

**请求体（JSON）**：`name`、`keywords`、`body_keywords`、`senders`、`logic`、`enabled` 均为可选。

**响应**：返回更新后的规则对象。

---

#### `DELETE /api/email/rules/{rule_id}`
删除规则。

**响应**
```json
{ "success": true }
```

---

### 2.3 WeLink 模块 `/api/welink`

#### `GET /api/welink/rules`
获取所有 WeLink 群聊监听规则。

**响应**
```json
[
  { "id": 1, "group_id": "group_xxx", "group_name": "技术支持群", "enabled": true }
]
```

---

#### `POST /api/welink/rules`
添加群聊监听规则。

**请求体（JSON）**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `group_id` | string | 是 | WeLink 群 ID（唯一标识） |
| `group_name` | string | 否 | 群名称（仅用于展示） |

**响应**：返回创建后的规则对象。

---

#### `PUT /api/welink/rules/{rule_id}`
更新群聊规则（启用/禁用或修改群名）。

**请求体（JSON）**：`group_name`、`enabled` 均为可选。

**响应**：返回更新后的规则对象。

---

#### `DELETE /api/welink/rules/{rule_id}`
删除群聊规则。

**响应**
```json
{ "success": true }
```

---

#### `POST /api/welink/receive`
客户端将 WeLink 群聊记录推送到服务器，服务器后台异步解析并存入知识库。

**请求体（JSON）**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `ChatId` | string | 是 | 聊天记录唯一 ID，去重用（建议格式：`{group_id}_{起始消息id}`） |
| `GroupId` | string | 否 | 群 ID |
| `GroupName` | string | 否 | 群名称 |
| `StartTime` | number | 否 | 记录起始时间（Unix 毫秒时间戳） |
| `EndTime` | number | 否 | 记录结束时间（Unix 毫秒时间戳） |
| `HtmlBody` | string | 否 | 聊天记录 HTML 内容 |
| `UploadBy` | string | 否 | 上传者用户 ID |
| `IsDaily` | bool | 否 | 是否为按天归档模式（`true` 时走 Agent 全天扫描流程） |

**响应**
```json
{ "Success": true, "Message": "Received successfully", "Duplicate": false }
```

> 若 `ChatId` 已存在则返回 `"Duplicate": true`，不重复处理。

---

### 2.4 AI 模块 `/api/ai`

#### `POST /api/ai/chat`
通用 AI 对话接口，供客户端内的 AI 功能调用。

**请求体（JSON）**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `prompt` | string | 是 | 系统提示词（system） |
| `message` | string | 是 | 用户消息（user） |

**响应**
```json
{ "reply": "AI 回复内容" }
```

---

### 2.5 图片模块 `/api/image`

#### `POST /api/image/upload`
上传图片文件，返回公开访问 URL（供邮件/聊天内联图片持久化）。

**请求**：`multipart/form-data`

| 字段 | 类型 | 说明 |
|---|---|---|
| `file` | File | 图片二进制数据 |
| `filename` | string（可选） | 文件名 |

**响应**
```json
{ "success": true, "url": "https://your-file-server/path/to/image.png" }
```

---

#### `POST /api/image/proxy`
通过服务器账号从网盘下载图片后上传，返回公开 URL（用于处理需要登录才能访问的图片链接）。

**请求体（JSON）**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `download_url` | string | 是 | 原始下载链接 |
| `extraction_code` | string | 否 | 提取码 |
| `file_name` | string | 否 | 文件名 |

**响应**
```json
{ "success": true, "url": "https://your-file-server/path/to/image.png" }
```

---

## 三、服务器依赖的外部服务

服务器本身还需对接以下外部服务（在 `server/utils/settings.py` 中配置）：

| 配置项 | 说明 | 是否必须 |
|---|---|---|
| `LLM_BASE_URL` + `LLM_API_KEY` + `LLM_MODEL_ID` | OpenAI 兼容的 LLM 接口，用于邮件/聊天解析 | **必须** |
| `EXPERIENCE_ENGINE_URL` | 知识库写入接口（POST），接收结构化经验文档 | 可选（无则跳过写入知识库） |
| `FILE_SERVER_URL` + `RAG_PIC_PUBLIC_BASE` | 图片文件上传服务 | 可选（无则跳过图片上传） |
| `OCR_URL` | OCR 服务，用于识别图片中的文字 | 可选（无则跳过 OCR） |
| `CLOUDDRIVE_ACCOUNT` + `CLOUDDRIVE_PASSWORD` | 网盘机器人账号，用于 `/api/image/proxy` | 可选 |

---

## 四、服务器配置文件

复制 `server/utils/settings.example.py` 为 `server/utils/settings.py` 并填写真实值：

```python
# 数据库（MySQL）
DB_HOST     = "localhost"
DB_PORT     = 3306
DB_USER     = "root"
DB_PASSWORD = "your_db_password"
DB_NAME     = "email_forwarder"

# 图片服务器
FILE_SERVER_URL     = "http://your-file-server:port"
RAG_PIC_PUBLIC_BASE = "https://your-public-base-url"

# LLM（OpenAI 兼容接口）
LLM_BASE_URL = "https://your-llm-endpoint/v1"
LLM_API_KEY  = "sk-your-api-key"
LLM_MODEL_ID = "your-model-id"

# OCR 服务
OCR_URL = "http://your-ocr-service/ocr"

# 经验引擎
EXPERIENCE_ENGINE_URL = "https://your-experience-engine/doc"

# 网盘机器人账号
CLOUDDRIVE_ACCOUNT  = "your_robot_account"
CLOUDDRIVE_PASSWORD = "your_robot_password"
```

---

## 五、启动服务器

```bash
cd server
pip install -r requirements.txt
python -m server
# 默认监听 0.0.0.0:8023
```

启动后在客户端「设置 → 服务器地址」中填写 `http://<your-ip>:8023`，点击「测试连接」验证。
