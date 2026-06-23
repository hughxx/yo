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

/// app 根目录：优先 D 盘（用户偏好），不存在则回退到用户主目录。
/// 输出件与外置 CLI 下载缓存都挂在它下面：<root>/{邮件,聊天记录,bin}。
fn app_root() -> Option<PathBuf> {
    if PathBuf::from("D:\\").exists() {
        return Some(PathBuf::from("D:\\问题定位助手"));
    }
    std::env::var_os("USERPROFILE").map(|h| PathBuf::from(h).join("问题定位助手"))
}

/// 默认输出目录。目录本身不在此创建——首次落盘时由 output::save 自动建。
pub fn default_output_dir() -> String {
    app_root().map(|p| p.to_string_lossy().into_owned()).unwrap_or_default()
}

/// 外置 CLI 自动查找 / 后期 HTTP 下载落地的 bin 目录（<root>/bin）。
pub fn sidecar_bin_dir() -> Option<PathBuf> {
    app_root().map(|p| p.join("bin"))
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
    // 命令触发（录制 / 归档）
    pub welink_groups: Vec<WelinkGroup>,
    pub welink_start_cmd: String,
    pub welink_end_cmd: String,
    pub welink_summary_cmd: String,
    pub welink_poll_interval: u32,

    // 自动收集（独立后台：周期 / 每日定时 / 时间段限定）
    pub collect_groups: Vec<WelinkGroup>,
    pub collect_poll_interval: u32,
    pub collect_periodic_enabled: bool,
    pub collect_period_hours: u32,
    pub collect_daily_enabled: bool,
    pub collect_daily_times: Vec<String>,
    pub collect_window_enabled: bool,
    pub collect_window_start: String,
    pub collect_window_end: String,

    // 图片
    /// 图片上传接口 URL（multipart: file -> {success,url}）。留空 = 产物不含图片。
    pub image_upload_url: String,
    /// 云盘（clouddrive）地址，用于下载 WeLink um_begin 链接的图片/文件
    pub clouddrive_url: String,
    pub clouddrive_account: String,
    pub clouddrive_password: String,

    // 外置 CLI 路径（留空 = 自动查找：配置路径 → 应用 bin/ → 随包 → 开发回退）
    pub outlook_cli_path: String,
    pub welink_cli_path: String,
    pub html2md_cli_path: String,

    // 云同步：每天定时在 shell 里执行用户命令，把输出目录同步到云端
    pub sync_enabled: bool,
    pub sync_command: String,
    pub sync_daily_time: String,

    // 上次「启动定时」用的配置（供弹窗「复制上次定时配置」恢复）
    pub last_timer_interval: u32,
    pub last_timer_rules: Vec<String>,
}

impl Default for Settings {
    fn default() -> Self {
        Settings {
            output_dir: default_output_dir(),
            title_max_len: 220,
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

            collect_groups: Vec::new(),
            collect_poll_interval: 60,
            collect_periodic_enabled: false,
            collect_period_hours: 6,
            collect_daily_enabled: false,
            collect_daily_times: vec!["01:00".to_string()],
            collect_window_enabled: false,
            collect_window_start: "09:00".to_string(),
            collect_window_end: "18:00".to_string(),

            image_upload_url: String::new(),
            clouddrive_url: "https://clouddrive.huawei.com".to_string(),
            clouddrive_account: String::new(),
            clouddrive_password: String::new(),

            outlook_cli_path: String::new(),
            welink_cli_path: String::new(),
            html2md_cli_path: String::new(),

            sync_enabled: false,
            sync_command: String::new(),
            sync_daily_time: "02:00".to_string(),

            last_timer_interval: 60,
            last_timer_rules: Vec::new(),
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
    let mut s = match settings_path(app).and_then(|p| Ok(std::fs::read_to_string(p)?)) {
        Ok(text) => serde_json::from_str(&text).unwrap_or_default(),
        Err(_) => Settings::default(),
    };
    let mut changed = false;
    // 旧配置 / 未设置时，补一个默认输出目录（优先 D 盘）
    if s.output_dir.trim().is_empty() {
        s.output_dir = default_output_dir();
        changed = true;
    }
    // 旧版默认 60 过短：日期已移出文件名，迁移到当前默认值
    if s.title_max_len == 60 {
        s.title_max_len = 220;
        changed = true;
    }
    // 迁移结果落盘，避免每次启动重复迁移
    if changed {
        let _ = save(app, &s);
    }
    s
}

pub fn save(app: &AppHandle, s: &Settings) -> anyhow::Result<()> {
    let path = settings_path(app)?;
    let text = serde_json::to_string_pretty(s)?;
    std::fs::write(path, text)?;
    Ok(())
}

/// 进程内缓存，供后台调度（邮件扫描 / WeLink 轮询）读取最新设置。
pub struct SettingsState(pub Mutex<Settings>);
