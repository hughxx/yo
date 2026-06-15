//! 单机版设置：对应 DESIGN.md §8。
//! 持久化为 app config dir 下的 settings.json，所有字段都有默认值（serde default），
//! 旧文件缺字段时自动补默认，不会读崩。

use std::path::PathBuf;
use std::sync::Mutex;

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Manager};

// ── 子结构 ──────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EmailRule {
    pub id: String,
    #[serde(default)]
    pub name: String,
    /// 主题关键词
    #[serde(default)]
    pub keywords: Vec<String>,
    /// 正文关键词（命中需走 outlook_cli search-body）
    #[serde(default)]
    pub body_keywords: Vec<String>,
    /// 发件人（姓名或邮箱包含匹配）
    #[serde(default)]
    pub senders: Vec<String>,
    /// "OR" | "AND"
    #[serde(default = "default_logic")]
    pub logic: String,
    #[serde(default = "default_true")]
    pub enabled: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WelinkGroup {
    pub id: String,
    pub group_id: String,
    #[serde(default)]
    pub group_name: String,
    #[serde(default = "default_true")]
    pub enabled: bool,
}

fn default_logic() -> String {
    "OR".to_string()
}
fn default_true() -> bool {
    true
}

// ── 主设置 ──────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct Settings {
    // 通用
    pub output_dir: String,
    pub title_max_len: u32,
    /// 文件名冲突策略："suffix"（追加 _NN）| "overwrite" | "skip"
    pub conflict_strategy: String,
    pub auto_scan: bool,

    // 邮件
    pub scan_folders: Vec<String>,
    pub scan_interval_minutes: u32,
    pub email_rules: Vec<EmailRule>,

    // WeLink
    pub welink_groups: Vec<WelinkGroup>,
    pub welink_start_cmd: String,
    pub welink_end_cmd: String,
    pub welink_summary_cmd: String,
    pub welink_poll_interval: u32,
    pub welink_daily_record: bool,
    pub welink_daily_time: String,

    // 图片
    /// 图片上传接口 URL（multipart: file -> {success,url}）。留空 = 产物不含图片。
    pub image_upload_url: String,
    pub clouddrive_account: String,
    pub clouddrive_password: String,

    // 外置 CLI 路径（留空 = 用默认：随包 / PATH）
    pub outlook_cli_path: String,
    pub welink_cli_path: String,
}

impl Default for Settings {
    fn default() -> Self {
        Settings {
            output_dir: String::new(),
            title_max_len: 60,
            conflict_strategy: "suffix".to_string(),
            auto_scan: false,

            scan_folders: Vec::new(),
            scan_interval_minutes: 60,
            email_rules: Vec::new(),

            welink_groups: Vec::new(),
            welink_start_cmd: "@云见 开始定位".to_string(),
            welink_end_cmd: "@云见 结束定位".to_string(),
            welink_summary_cmd: "@云见 总结经验".to_string(),
            welink_poll_interval: 8,
            welink_daily_record: false,
            welink_daily_time: "01:00".to_string(),

            image_upload_url: String::new(),
            clouddrive_account: String::new(),
            clouddrive_password: String::new(),

            outlook_cli_path: String::new(),
            welink_cli_path: String::new(),
        }
    }
}

// ── 持久化 ──────────────────────────────────────────────────

fn settings_path(app: &AppHandle) -> anyhow::Result<PathBuf> {
    let dir = app
        .path()
        .app_config_dir()
        .map_err(|e| anyhow::anyhow!("无法获取配置目录: {e}"))?;
    std::fs::create_dir_all(&dir).ok();
    Ok(dir.join("settings.json"))
}

pub fn load(app: &AppHandle) -> Settings {
    match settings_path(app).and_then(|p| Ok(std::fs::read_to_string(p)?)) {
        Ok(text) => serde_json::from_str(&text).unwrap_or_default(),
        Err(_) => Settings::default(),
    }
}

pub fn save(app: &AppHandle, s: &Settings) -> anyhow::Result<()> {
    let path = settings_path(app)?;
    let text = serde_json::to_string_pretty(s)?;
    std::fs::write(path, text)?;
    Ok(())
}

/// 进程内缓存，供后台调度（邮件扫描 / WeLink 轮询）读取最新设置。
pub struct SettingsState(pub Mutex<Settings>);
