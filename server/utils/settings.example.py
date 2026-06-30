# 复制本文件为 settings.py 并填写真实配置
# cp server/utils/settings.example.py server/utils/settings.py

# ==================== 数据库配置 ====================
# 方言：postgresql（= GaussDB / openGauss，走 PG 协议）| mysql
DB_DIALECT  = "postgresql"
DB_HOST     = "localhost"
DB_PORT     = 8000                 # GaussDB 端口按实际改（MySQL 一般 3306）
DB_USER     = "your_db_user"
DB_PASSWORD = "your_db_password"
DB_NAME     = "email_forwarder"
# 可选：PG 驱动名（默认 psycopg2；GaussDB 装华为编译版 psycopg2 即可，仍填 psycopg2）
# DB_DRIVER      = "psycopg2"
# 可选：建库时连接的维护库（默认 postgres，建目标库时连它）
# DB_MAINTENANCE = "postgres"
# 是否自动建库建表（默认 False=手动，执行 server/db/schema_gaussdb.md 的 SQL）。
# 想让服务端启动时自动确保库存在并 create_all 建表，置 True。
DB_AUTO_INIT = False

# ==================== 图片服务器配置 ====================
# 邮件内联图片上传目标，留空则跳过图片上传
FILE_SERVER_URL     = "http://your-file-server:port"
RAG_PIC_PUBLIC_BASE = "https://your-public-base-url"

# ==================== LLM 配置 ====================
LLM_BASE_URL = "https://your-llm-endpoint/v1"
LLM_API_KEY  = "sk-your-api-key"
LLM_MODEL_ID = "your-model-id"

# 同时处理（含 LLM 调用）的邮件并发上限。定时一次推大量邮件时靠它限流，避免打爆 LLM。
MAX_CONCURRENT_PROCESS = 3

# ==================== 客户端版本推送 ====================
# 发版流程：把新 exe 传到下载地址 → 改 CLIENT_LATEST_VERSION → 需要逼旧版升级时调 CLIENT_MIN_VERSION
CLIENT_LATEST_VERSION = "1.0.0"          # 最新版本号
CLIENT_MIN_VERSION    = "0.0.0"          # 低于此版本强制更新（设成 latest 即全员强更）
CLIENT_DOWNLOAD_URL   = ""               # 新 exe 的下载地址（放文件服务器/网盘直链）
CLIENT_UPDATE_NOTES   = ""               # 更新说明（弹窗里展示）

# ==================== OCR 配置 ====================
OCR_URL = "http://your-ocr-service/ocr"

# ==================== 经验引擎配置 ====================
EXPERIENCE_ENGINE_URL = "https://your-experience-engine/doc"

# ==================== CloudDrive 下载账号 ====================
CLOUDDRIVE_ACCOUNT  = "your_robot_account"
CLOUDDRIVE_PASSWORD = "your_robot_password"
