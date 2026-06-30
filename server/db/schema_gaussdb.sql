-- ============================================================
-- GaussDB / openGauss 建表脚本（email_forwarder）
-- 用法：
--   1) 先在维护库(postgres)执行：  CREATE DATABASE email_forwarder;
--   2) 再连到 email_forwarder 库，整段粘贴执行下面的建表语句。
-- 说明：SERIAL=自增主键，TEXT=大正文，IF NOT EXISTS 可重复执行。
-- 本脚本由 SQLAlchemy 按模型自动渲染，改了模型请重新生成。
-- ============================================================

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
