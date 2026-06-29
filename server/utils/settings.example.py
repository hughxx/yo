# 复制本文件为 settings.py 并填写真实配置
# cp server/utils/settings.example.py server/utils/settings.py

# ==================== 数据库配置 ====================
DB_HOST     = "localhost"
DB_PORT     = 3306
DB_USER     = "root"
DB_PASSWORD = "your_db_password"
DB_NAME     = "email_forwarder"

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

# ==================== OCR 配置 ====================
OCR_URL = "http://your-ocr-service/ocr"

# ==================== 经验引擎配置 ====================
EXPERIENCE_ENGINE_URL = "https://your-experience-engine/doc"

# ==================== CloudDrive 下载账号 ====================
CLOUDDRIVE_ACCOUNT  = "your_robot_account"
CLOUDDRIVE_PASSWORD = "your_robot_password"
