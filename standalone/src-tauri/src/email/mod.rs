//! 邮件流：浏览 / 规则匹配 / 导出 HTML+MD / 监听（DESIGN.md §5.1）。
//! 「已导出」绑定本地产物文件是否存在（见 store.rs）；导入的 .msg 作为特殊 PST（见 imported.rs）。

use std::collections::{HashMap, HashSet};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread::JoinHandle;
use std::time::Duration;

use serde::{Deserialize, Serialize};
use serde_json::Value;
use tauri::{AppHandle, Manager};

use crate::events::emit_log;
use crate::images::{process_email_html, InlineImage};
use crate::imported::{self, ImportedMsg, ImportedState};
use crate::settings::{EmailRule, Settings, SettingsState};
use crate::store::{self, is_exported, ExportState};
use crate::{htmlmd, output, sidecar};

/// 左树里「导入的 msg」特殊节点在 scan_folders 中的标记值。
pub const IMPORTED_MSG_SENTINEL: &str = "::imported_msg::";

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EmailSummary {
    pub item_id: String,
    #[serde(default)]
    pub subject: String,
    #[serde(default)]
    pub sender_name: String,
    #[serde(default)]
    pub sender_email: String,
    #[serde(default)]
    pub received_time: String,
    #[serde(default)]
    pub conversation_topic: String,
    /// 是否命中启用规则
    #[serde(default)]
    pub matched: bool,
    /// 是否已导出（本地产物存在）
    #[serde(default)]
    pub processed: bool,
    /// 导入 .msg 的源文件路径；Outlook 邮件为空
    #[serde(default)]
    pub source_path: String,
}

#[derive(Debug, Deserialize)]
struct EmailDetail {
    #[serde(default)]
    subject: String,
    #[serde(default)]
    conversation_topic: String,
    #[serde(default)]
    received_time: String,
    #[serde(default)]
    html_body: String,
    #[serde(default)]
    inline_images: Vec<InlineImage>,
}

#[derive(Debug, Default, Serialize)]
pub struct ScanReport {
    pub scanned: usize,
    pub matched: usize,
    pub saved: usize,
    pub skipped: usize,
    pub failed: usize,
}

// ── 列表 / 浏览 ─────────────────────────────────────────────

fn real_folders(scan_folders: &[String]) -> Vec<String> {
    scan_folders
        .iter()
        .filter(|f| f.as_str() != IMPORTED_MSG_SENTINEL)
        .cloned()
        .collect()
}

fn fetch_list(
    app: &AppHandle,
    settings: &Settings,
    folders: &[String],
    count: u32,
) -> Result<Vec<EmailSummary>, String> {
    let joined = folders.join(",");
    let count_s = count.to_string();
    let mut args = vec!["list", "--count", count_s.as_str()];
    if !joined.is_empty() {
        args.push("--folders");
        args.push(joined.as_str());
    }
    let v = sidecar::run_outlook(app, settings, &args)?;
    serde_json::from_value(v).map_err(|e| format!("解析邮件列表失败: {e}"))
}

/// 浏览单个文件夹（folder 为空 = 默认收件箱），标注 matched / processed。
pub fn browse(
    app: &AppHandle,
    settings: &Settings,
    folder: &str,
    exports: &HashMap<String, String>,
    count: u32,
) -> Result<Vec<EmailSummary>, String> {
    let folders: Vec<String> = if folder.trim().is_empty() {
        vec![]
    } else {
        vec![folder.to_string()]
    };
    let mut emails = fetch_list(app, settings, &folders, count)?;
    let flags = matched_flags(app, settings, &folders, &emails);
    for (e, m) in emails.iter_mut().zip(flags) {
        e.matched = m;
        e.processed = is_exported(exports, &e.item_id);
    }
    Ok(emails)
}

/// 列出「处理范围」内的邮件：勾选的 Outlook 文件夹 +（若勾了）导入的 msg。
/// 范围 = settings.scan_folders（含 IMPORTED_MSG_SENTINEL）。
pub fn list_scope(
    app: &AppHandle,
    settings: &Settings,
    exports: &HashMap<String, String>,
    imported_list: &[ImportedMsg],
) -> Result<Vec<EmailSummary>, String> {
    let real = real_folders(&settings.scan_folders);
    let mut out: Vec<EmailSummary> = Vec::new();

    if !real.is_empty() {
        let mut emails = fetch_list(app, settings, &real, 300)?;
        let flags = matched_flags(app, settings, &real, &emails);
        for (e, m) in emails.iter_mut().zip(flags) {
            e.matched = m;
            e.processed = is_exported(exports, &e.item_id);
        }
        out.extend(emails);
    }

    if settings.scan_folders.iter().any(|f| f == IMPORTED_MSG_SENTINEL) {
        out.extend(list_imported(settings, imported_list, exports));
    }

    Ok(out)
}

/// 列出导入的 msg（特殊 PST 视角）。matched 仅按主题/发件人（msg 不在 store，无法正文搜索）。
pub fn list_imported(
    settings: &Settings,
    list: &[ImportedMsg],
    exports: &HashMap<String, String>,
) -> Vec<EmailSummary> {
    let rules: Vec<&EmailRule> = settings.email_rules.iter().filter(|r| r.enabled).collect();
    list.iter()
        .map(|m| {
            let mut e = EmailSummary {
                item_id: m.item_id.clone(),
                subject: m.subject.clone(),
                sender_name: m.sender_name.clone(),
                sender_email: m.sender_email.clone(),
                received_time: m.received_time.clone(),
                conversation_topic: m.conversation_topic.clone(),
                matched: false,
                processed: is_exported(exports, &m.item_id),
                source_path: m.path.clone(),
            };
            e.matched = rules.iter().any(|r| rule_matches(&e, r, None));
            e
        })
        .collect()
}

// ── 规则匹配 ────────────────────────────────────────────────

fn contains_ci(haystack: &str, needle: &str) -> bool {
    haystack.to_lowercase().contains(&needle.to_lowercase())
}
fn subject_hit(subject: &str, keywords: &[String]) -> bool {
    keywords.iter().any(|k| !k.is_empty() && contains_ci(subject, k))
}
fn sender_hit(email: &EmailSummary, senders: &[String]) -> bool {
    senders.iter().any(|sn| {
        !sn.is_empty()
            && (contains_ci(&email.sender_name, sn) || contains_ci(&email.sender_email, sn))
    })
}

/// body_hits 为 None 时跳过正文条件（用于 msg）。
fn rule_matches(email: &EmailSummary, rule: &EmailRule, body_hits: Option<&HashSet<String>>) -> bool {
    let mut groups: Vec<bool> = Vec::new();
    if !rule.keywords.is_empty() {
        groups.push(subject_hit(&email.subject, &rule.keywords));
    }
    if !rule.senders.is_empty() {
        groups.push(sender_hit(email, &rule.senders));
    }
    if !rule.body_keywords.is_empty() {
        if let Some(bh) = body_hits {
            groups.push(bh.contains(&email.item_id));
        }
    }
    if groups.is_empty() {
        return false;
    }
    if rule.logic.eq_ignore_ascii_case("AND") {
        groups.iter().all(|&b| b)
    } else {
        groups.iter().any(|&b| b)
    }
}

fn matched_flags(
    app: &AppHandle,
    settings: &Settings,
    folders: &[String],
    emails: &[EmailSummary],
) -> Vec<bool> {
    let rules: Vec<&EmailRule> = settings.email_rules.iter().filter(|r| r.enabled).collect();
    if rules.is_empty() {
        return vec![false; emails.len()];
    }
    let body_hits: Vec<HashSet<String>> = rules
        .iter()
        .map(|r| body_hits_for_rule(app, settings, folders, r))
        .collect();
    emails
        .iter()
        .map(|e| {
            rules
                .iter()
                .zip(body_hits.iter())
                .any(|(rule, bh)| rule_matches(e, rule, Some(bh)))
        })
        .collect()
}

fn body_hits_for_rule(
    app: &AppHandle,
    settings: &Settings,
    folders: &[String],
    rule: &EmailRule,
) -> HashSet<String> {
    if rule.body_keywords.is_empty() {
        return HashSet::new();
    }
    let joined = folders.join(",");
    let kw = rule.body_keywords.join(",");
    let mut args = vec!["search-body", "--keywords", kw.as_str()];
    if !joined.is_empty() {
        args.push("--folders");
        args.push(joined.as_str());
    }
    match sidecar::run_outlook(app, settings, &args) {
        Ok(v) => serde_json::from_value::<Vec<String>>(v)
            .unwrap_or_default()
            .into_iter()
            .collect(),
        Err(e) => {
            emit_log(app, format!("规则[{}] 正文搜索失败: {e}", rule.name));
            HashSet::new()
        }
    }
}

// ── 单封处理 ────────────────────────────────────────────────

/// 取详情 → 图片转外链 → MD → 落盘。返回 Some(产物html路径) 表示已落盘，None 表示按冲突策略跳过。
fn process_detail(app: &AppHandle, settings: &Settings, v: Value) -> Result<Option<String>, String> {
    let detail: EmailDetail =
        serde_json::from_value(v).map_err(|e| format!("解析邮件详情失败: {e}"))?;

    let html = process_email_html(settings, &detail.html_body, &detail.inline_images);
    let md = htmlmd::html_to_md(app, settings, &html);

    let title = if !detail.subject.trim().is_empty() {
        detail.subject.clone()
    } else if !detail.conversation_topic.trim().is_empty() {
        detail.conversation_topic.clone()
    } else {
        "untitled".to_string()
    };

    match output::save(settings, output::SRC_EMAIL, &detail.received_time, &title, &html, &md)? {
        Some(saved) => {
            emit_log(app, format!("已导出: {}", saved.base_name));
            Ok(Some(saved.html_path))
        }
        None => {
            emit_log(app, format!("已存在跳过: {title}"));
            Ok(None)
        }
    }
}

/// 处理一封 Outlook 邮件（按 EntryID）。
fn process_entry(app: &AppHandle, settings: &Settings, item_id: &str) -> Result<Option<String>, String> {
    let v = sidecar::run_outlook(app, settings, &["get", "--entry-id", item_id])?;
    process_detail(app, settings, v)
}

// ── 扫描（立即处理 / 监听一轮） ─────────────────────────────

pub fn run_scan(
    app: &AppHandle,
    settings: &Settings,
    exports: &mut HashMap<String, String>,
    imported_list: &[ImportedMsg],
) -> Result<ScanReport, String> {
    emit_log(app, "开始处理…");
    let mut report = ScanReport::default();

    let folders = real_folders(&settings.scan_folders);

    // 1) Outlook 文件夹：规则匹配 → 导出未导出的
    if settings.email_rules.iter().any(|r| r.enabled) {
        let emails = fetch_list(app, settings, &folders, 9999)?;
        report.scanned += emails.len();
        let flags = matched_flags(app, settings, &folders, &emails);
        let mut seen: HashSet<String> = HashSet::new();
        for (email, hit) in emails.iter().zip(flags) {
            if !hit || !seen.insert(email.item_id.clone()) {
                continue;
            }
            report.matched += 1;
            if is_exported(exports, &email.item_id) {
                report.skipped += 1;
                continue;
            }
            match process_entry(app, settings, &email.item_id) {
                Ok(Some(path)) => {
                    report.saved += 1;
                    exports.insert(email.item_id.clone(), path);
                }
                Ok(None) => {}
                Err(e) => {
                    report.failed += 1;
                    emit_log(app, format!("处理失败 {}: {e}", email.item_id));
                }
            }
        }
    } else {
        emit_log(app, "没有启用的规则，跳过 Outlook 文件夹");
    }

    // 2) 若勾选了「导入的 msg」范围：导出未导出的 msg（用户已显式导入，不再按规则过滤）
    if settings.scan_folders.iter().any(|f| f == IMPORTED_MSG_SENTINEL) {
        for m in imported_list {
            if is_exported(exports, &m.item_id) {
                continue;
            }
            match process_msg_path(app, settings, exports, &m.path) {
                Ok(true) => report.saved += 1,
                Ok(false) => {}
                Err(e) => {
                    report.failed += 1;
                    emit_log(app, format!("处理 msg 失败 {}: {e}", m.path));
                }
            }
        }
    }

    emit_log(
        app,
        format!(
            "处理完成：匹配 {} / 导出 {} / 跳过 {} / 失败 {}",
            report.matched, report.saved, report.skipped, report.failed
        ),
    );
    Ok(report)
}

/// 处理用户在 Outlook 视图里选中的邮件（按 EntryID）。
pub fn process_selected(
    app: &AppHandle,
    settings: &Settings,
    exports: &mut HashMap<String, String>,
    item_ids: &[String],
) -> Result<usize, String> {
    if settings.output_dir.trim().is_empty() {
        return Err("未设置输出目录".to_string());
    }
    let mut saved = 0usize;
    emit_log(app, format!("处理选中的 {} 封…", item_ids.len()));
    for id in item_ids {
        match process_entry(app, settings, id) {
            Ok(Some(path)) => {
                saved += 1;
                exports.insert(id.clone(), path);
            }
            Ok(None) => {}
            Err(e) => emit_log(app, format!("处理失败 {id}: {e}")),
        }
    }
    Ok(saved)
}

// ── 导入 .msg / .pst ────────────────────────────────────────

fn msg_summary(v: &Value, path: &str) -> ImportedMsg {
    let g = |k: &str| v.get(k).and_then(|x| x.as_str()).unwrap_or("").to_string();
    ImportedMsg {
        item_id: g("item_id"),
        path: path.to_string(),
        subject: g("subject"),
        sender_name: g("sender_name"),
        sender_email: g("sender_email"),
        received_time: g("received_time"),
        conversation_topic: g("conversation_topic"),
    }
}

fn process_msg_path(
    app: &AppHandle,
    settings: &Settings,
    exports: &mut HashMap<String, String>,
    path: &str,
) -> Result<bool, String> {
    let v = sidecar::run_outlook(app, settings, &["msg-get", "--path", path])?;
    let id = v.get("item_id").and_then(|x| x.as_str()).unwrap_or("").to_string();
    if !id.is_empty() && is_exported(exports, &id) {
        return Ok(false);
    }
    match process_detail(app, settings, v)? {
        Some(html) => {
            if !id.is_empty() {
                exports.insert(id, html);
            }
            Ok(true)
        }
        None => Ok(false),
    }
}

/// 导入 .msg：登记到「导入的 msg」并导出（未导出的）。返回导出数量。
pub fn import_msg(
    app: &AppHandle,
    settings: &Settings,
    exports: &mut HashMap<String, String>,
    imported_list: &mut Vec<ImportedMsg>,
    paths: &[String],
) -> Result<usize, String> {
    if settings.output_dir.trim().is_empty() {
        return Err("未设置输出目录".to_string());
    }
    let mut saved = 0usize;
    for path in paths {
        emit_log(app, format!("导入 .msg: {path}"));
        let v = match sidecar::run_outlook(app, settings, &["msg-get", "--path", path]) {
            Ok(v) => v,
            Err(e) => {
                emit_log(app, format!("读取 .msg 失败: {e}"));
                continue;
            }
        };
        // 登记（去重 by path）
        imported::upsert(imported_list, msg_summary(&v, path));

        let id = v.get("item_id").and_then(|x| x.as_str()).unwrap_or("").to_string();
        if !id.is_empty() && is_exported(exports, &id) {
            continue;
        }
        match process_detail(app, settings, v) {
            Ok(Some(html)) => {
                saved += 1;
                if !id.is_empty() {
                    exports.insert(id, html);
                }
            }
            Ok(None) => {}
            Err(e) => emit_log(app, format!("处理失败: {e}")),
        }
    }
    Ok(saved)
}

/// 重新导出选中的 msg（按源路径）。用于「导入的 msg」视图里的「处理选中」。
pub fn reexport_msgs(
    app: &AppHandle,
    settings: &Settings,
    exports: &mut HashMap<String, String>,
    paths: &[String],
) -> Result<usize, String> {
    let mut saved = 0usize;
    for path in paths {
        match process_msg_path(app, settings, exports, path) {
            Ok(true) => saved += 1,
            Ok(false) => {}
            Err(e) => emit_log(app, format!("处理 msg 失败 {path}: {e}")),
        }
    }
    Ok(saved)
}

/// 挂载 .pst，返回新 store 显示名（空串表示已挂载过）。
pub fn import_pst(app: &AppHandle, settings: &Settings, path: &str) -> Result<String, String> {
    let v = sidecar::run_outlook(app, settings, &["add-pst", "--path", path])?;
    Ok(v.get("display_name").and_then(|x| x.as_str()).unwrap_or("").to_string())
}

// ── 邮件监听（定时自动处理） ────────────────────────────────

pub struct EmailMonitorState {
    pub stop: Arc<AtomicBool>,
    pub handle: Mutex<Option<JoinHandle<()>>>,
}

impl Default for EmailMonitorState {
    fn default() -> Self {
        EmailMonitorState {
            stop: Arc::new(AtomicBool::new(false)),
            handle: Mutex::new(None),
        }
    }
}

pub fn monitor_running(state: &EmailMonitorState) -> bool {
    state
        .handle
        .lock()
        .unwrap()
        .as_ref()
        .map(|h| !h.is_finished())
        .unwrap_or(false)
}

pub fn monitor_start(app: &AppHandle, state: &EmailMonitorState) {
    if monitor_running(state) {
        return;
    }
    state.stop.store(false, Ordering::SeqCst);
    let stop = state.stop.clone();
    let app2 = app.clone();
    let handle = std::thread::spawn(move || monitor_loop(app2, stop));
    *state.handle.lock().unwrap() = Some(handle);
}

pub fn monitor_stop(state: &EmailMonitorState) {
    state.stop.store(true, Ordering::SeqCst);
    if let Some(h) = state.handle.lock().unwrap().take() {
        let _ = h.join();
    }
}

fn monitor_loop(app: AppHandle, stop: Arc<AtomicBool>) {
    emit_log(&app, "邮件监听已启动");
    while !stop.load(Ordering::SeqCst) {
        let settings = app.state::<SettingsState>().0.lock().unwrap().clone();

        {
            let estate = app.state::<ExportState>();
            let istate = app.state::<ImportedState>();
            let mut exports = estate.0.lock().unwrap();
            let imported_list = istate.0.lock().unwrap().clone();
            if let Err(e) = run_scan(&app, &settings, &mut exports, &imported_list) {
                emit_log(&app, format!("自动处理失败: {e}"));
            }
            store::persist(&app, &exports);
        }

        let secs = settings.scan_interval_minutes.max(1) as u64 * 60;
        let mut left = secs * 10;
        while left > 0 && !stop.load(Ordering::SeqCst) {
            std::thread::sleep(Duration::from_millis(100));
            left -= 1;
        }
    }
    emit_log(&app, "邮件监听已停止");
}
