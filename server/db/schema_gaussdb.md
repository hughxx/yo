# GaussDB 建库建表脚本

GaussDB Kernel（openGauss/PostgreSQL 协议兼容）。手动执行本脚本即可，无需服务端自动建库
（已默认关闭自动建库；如需自动建表可在 settings.py 设 `DB_AUTO_INIT = True`）。

## 0. 前提

- 驱动：服务端用 **GaussDB 客户端自带的 psycopg2** 替换标准 psycopg2（代码仍走 `postgresql+psycopg2`，
  GaussDB 默认 SHA256 口令认证，标准 psycopg2-binary 可能认证失败）。
- `server/utils/settings.py` 里 `DB_DIALECT="postgresql"`（默认即此），`DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME` 填 GaussDB 实例信息。

## 1. 建库（用管理员连到维护库 postgres 执行）

```sql
-- 库名与 settings.DB_NAME 一致
CREATE DATABASE email_forwarder;
-- 可选：建业务用户并授权
-- CREATE USER email_app WITH PASSWORD 'YourStrongPwd';
-- GRANT ALL PRIVILEGES ON DATABASE email_forwarder TO email_app;
```

> 注：GaussDB/PG 的 `CREATE DATABASE` 不能在事务块里执行，也不支持 `IF NOT EXISTS`；库若已存在跳过本步。

## 2. 建表（连到上面的 email_forwarder 库执行）

> 8 张表，`IF NOT EXISTS` 可重复执行。`SERIAL` 自增主键、`TEXT` 大正文均为 GaussDB 原生支持。

```sql
CREATE TABLE IF NOT EXISTS t_collection_namespaces (
	id SERIAL NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	description VARCHAR(500), 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id)
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_t_collection_namespaces_name ON t_collection_namespaces (name);

CREATE TABLE IF NOT EXISTS t_collection_emails (
	id SERIAL NOT NULL, 
	conversation_topic VARCHAR(500) NOT NULL, 
	subject TEXT, 
	sender_name VARCHAR(500), 
	received_time TIMESTAMP WITHOUT TIME ZONE, 
	html_body TEXT, 
	markdown_body TEXT, 
	upload_by VARCHAR(100), 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	updated_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id)
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_t_collection_emails_conversation_topic ON t_collection_emails (conversation_topic);

CREATE TABLE IF NOT EXISTS t_collection_email_namespaces (
	id SERIAL NOT NULL, 
	email_id INTEGER NOT NULL, 
	namespace_id INTEGER NOT NULL, 
	status VARCHAR(20), 
	PRIMARY KEY (id), 
	CONSTRAINT uq_email_namespace UNIQUE (email_id, namespace_id)
);

CREATE INDEX IF NOT EXISTS ix_t_collection_email_namespaces_namespace_id ON t_collection_email_namespaces (namespace_id);

CREATE INDEX IF NOT EXISTS ix_t_collection_email_namespaces_email_id ON t_collection_email_namespaces (email_id);

CREATE TABLE IF NOT EXISTS t_collection_email_rules (
	id SERIAL NOT NULL, 
	namespace_id INTEGER NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	keywords TEXT, 
	body_keywords TEXT, 
	senders TEXT, 
	logic VARCHAR(10), 
	enabled INTEGER, 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ix_t_collection_email_rules_namespace_id ON t_collection_email_rules (namespace_id);

CREATE TABLE IF NOT EXISTS t_collection_image_cache (
	id SERIAL NOT NULL, 
	hash VARCHAR(64) NOT NULL, 
	url TEXT NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id)
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_t_collection_image_cache_hash ON t_collection_image_cache (hash);

CREATE TABLE IF NOT EXISTS t_collection_welink_rules (
	id SERIAL NOT NULL, 
	group_id VARCHAR(100) NOT NULL, 
	group_name VARCHAR(200), 
	enabled INTEGER, 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id)
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_t_collection_welink_rules_group_id ON t_collection_welink_rules (group_id);

CREATE TABLE IF NOT EXISTS t_collection_welink_chatlogs (
	id SERIAL NOT NULL, 
	chat_id VARCHAR(200) NOT NULL, 
	group_id VARCHAR(100) NOT NULL, 
	group_name VARCHAR(200), 
	start_time TIMESTAMP WITHOUT TIME ZONE, 
	end_time TIMESTAMP WITHOUT TIME ZONE, 
	html_body TEXT, 
	upload_by VARCHAR(100), 
	process_status VARCHAR(20), 
	is_daily INTEGER, 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	updated_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ix_t_collection_welink_chatlogs_group_id ON t_collection_welink_chatlogs (group_id);

CREATE UNIQUE INDEX IF NOT EXISTS ix_t_collection_welink_chatlogs_chat_id ON t_collection_welink_chatlogs (chat_id);

CREATE TABLE IF NOT EXISTS t_process_logs (
	id SERIAL NOT NULL, 
	source VARCHAR(20) NOT NULL, 
	ref_key VARCHAR(500) NOT NULL, 
	scope VARCHAR(200) NOT NULL, 
	error_type VARCHAR(100) NOT NULL, 
	error_detail TEXT, 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ix_t_process_logs_created_at ON t_process_logs (created_at);

CREATE INDEX IF NOT EXISTS ix_t_process_logs_error_type ON t_process_logs (error_type);

CREATE INDEX IF NOT EXISTS ix_t_process_logs_source ON t_process_logs (source);
```

## 3. 校验

```sql
-- 应看到 8 张 t_collection_* / t_process_logs 表
SELECT tablename FROM pg_tables WHERE tablename LIKE 't_%' ORDER BY tablename;
```

表清单：t_collection_namespaces、t_collection_emails、t_collection_email_namespaces、
t_collection_email_rules、t_collection_image_cache、t_collection_welink_rules、
t_collection_welink_chatlogs、t_process_logs。
