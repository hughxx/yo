//! WeLink 流：轮询 → 命令录制 / 按天归档 → HTML/MD → 落盘（DESIGN.md §5.2）。
//! 移植自旧 pyqt_client/modules/welink/monitor.py，去掉服务器上传，改为本地落盘。

mod chatlog;
mod cli;
pub mod collect;
mod image;
mod render;

use std::collections::{HashMap, HashSet};
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread::JoinHandle;
use std::time::Duration;

use chrono::{Local, TimeZone};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use tauri::{AppHandle, Manager};

use crate::events::emit_log;
use crate::images::process_email_html;
use crate::settings::{Settings, SettingsState};
use crate::{htmlmd, output};

// ── 消息模型 ────────────────────────────────────────────────

#[derive(Debug, Clone)]
pub struct WlMessage {
    pub msg_id: i64,
    pub sender: String,
    pub content_type: String,
    pub content: String,
    pub server_send_time: i64,
    pub img_url: Option<String>,
    pub img_name: Option<String>,
}

fn as_i64(v: &Value) -> i64 {
    match v {
        Value::Number(n) => n.as_i64().unwrap_or(0),
        Value::String(s) => s.parse().unwrap_or(0),
        _ => 0,
    }
}

fn parse_messages(items: &[Value]) -> Vec<WlMessage> {
    items
        .iter()
        .map(|m| WlMessage {
            msg_id: m.get("msgId").map(as_i64).unwrap_or(0),
            sender: m.get("sender").and_then(|x| x.as_str()).unwrap_or("").to_string(),
            content_type: m.get("contentType").and_then(|x| x.as_str()).unwrap_or("").to_string(),
            content: m.get("content").and_then(|x| x.as_str()).unwrap_or("").to_string(),
            server_send_time: m.get("serverSendTime").map(as_i64).unwrap_or(0),
            img_url: None,
            img_name: None,
        })
        .collect()
}

// ── 命令解析 ────────────────────────────────────────────────

/// 把 WeLink @提及后跟的各种 Unicode 空格归一化为普通空格。
fn normalize(text: &str) -> String {
    let mut s = text.to_string();
    for cp in [
        '\u{2000}', '\u{2001}', '\u{2002}', '\u{2003}', '\u{2004}', '\u{2005}',
        '\u{2006}', '\u{2007}', '\u{2008}', '\u{2009}', '\u{200a}', '\u{202f}',
        '\u{205f}', '\u{00a0}', '\u{3000}',
    ] {
        s = s.replace(cp, " ");
    }
    s
}

enum SummaryMode {
    /// 用法③：不带时间 → 截止 = 这条总结命令自己的时间
    ToNow,
    /// 用法①：一个时间 → 截止 = 指定消息的时间
    ToMessage { id: String, dt_ms: i64 },
    /// 用法②：两个时间 → 显式区间
    Range { start_id: String, start_dt: i64, end_id: String, end_dt: i64 },
}

fn local_ms(date: &str, time: &str) -> Option<i64> {
    let dt = chrono::NaiveDateTime::parse_from_str(&format!("{date} {time}"), "%Y-%m-%d %H:%M").ok()?;
    Local.from_local_datetime(&dt).single().map(|d| d.timestamp_millis())
}

/// 解析总结命令：8 段（区间）/ 4 段（单点）/ 其余（无时间，截止到命令本身）。
fn parse_summary_cmd(prefix: &str, norm: &str) -> SummaryMode {
    let Some(idx) = norm.find(prefix) else {
        return SummaryMode::ToNow;
    };
    let rest = norm[idx + prefix.len()..].trim();
    let parts: Vec<&str> = rest.split_whitespace().collect();

    if parts.len() >= 8 {
        if let (Some(a), Some(b)) = (local_ms(parts[2], parts[3]), local_ms(parts[6], parts[7])) {
            // 自动容错顺序写反
            let (sid, sdt, eid, edt) = if a <= b {
                (parts[1], a, parts[5], b)
            } else {
                (parts[5], b, parts[1], a)
            };
            return SummaryMode::Range {
                start_id: sid.into(),
                start_dt: sdt,
                end_id: eid.into(),
                end_dt: edt,
            };
        }
    }
    if parts.len() >= 4 {
        if let Some(a) = local_ms(parts[2], parts[3]) {
            return SummaryMode::ToMessage { id: parts[1].into(), dt_ms: a };
        }
    }
    SummaryMode::ToNow
}

/// 该消息是否为系统命令（开始/结束/总结），抓取时应剔除。
fn is_system_cmd(settings: &Settings, content: &str) -> bool {
    let n = normalize(content);
    [
        &settings.welink_start_cmd,
        &settings.welink_end_cmd,
        &settings.welink_summary_cmd,
    ]
    .iter()
    .any(|c| !c.is_empty() && n.contains(c.as_str()))
}

// ── 持久化状态 ──────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
struct Session {
    start_msg_id: i64,
    start_time: i64,
    group_name: String,
}

#[derive(Debug, Default, Serialize, Deserialize)]
struct WelinkState {
    #[serde(default)]
    last_ids: HashMap<String, i64>,
    #[serde(default)]
    sessions: HashMap<String, Session>,
    /// 每群「上次抓取结束点」时间戳（毫秒）。开始/结束、总结(一个时间)、总结(两个时间)三种都更新它。
    #[serde(default)]
    last_captured: HashMap<String, i64>,
    #[serde(default)]
    saved_chat_ids: HashSet<String>,
}

fn state_path(app: &AppHandle) -> Option<PathBuf> {
    let dir = app.path().app_config_dir().ok()?;
    std::fs::create_dir_all(&dir).ok();
    Some(dir.join("welink_state.json"))
}

fn load_state(app: &AppHandle) -> WelinkState {
    state_path(app)
        .and_then(|p| std::fs::read_to_string(p).ok())
        .and_then(|t| serde_json::from_str(&t).ok())
        .unwrap_or_default()
}

fn save_state(app: &AppHandle, st: &WelinkState) {
    if let Some(p) = state_path(app) {
        if let Ok(t) = serde_json::to_string_pretty(st) {
            let _ = std::fs::write(p, t);
        }
    }
}

// ── 监听控制状态（managed） ─────────────────────────────────

pub struct MonitorState {
    pub stop: Arc<AtomicBool>,
    pub handle: Mutex<Option<JoinHandle<()>>>,
}

impl Default for MonitorState {
    fn default() -> Self {
        MonitorState {
            stop: Arc::new(AtomicBool::new(false)),
            handle: Mutex::new(None),
        }
    }
}

pub fn is_running(state: &MonitorState) -> bool {
    state
        .handle
        .lock()
        .unwrap()
        .as_ref()
        .map(|h| !h.is_finished())
        .unwrap_or(false)
}

pub fn start(app: &AppHandle, state: &MonitorState) {
    if is_running(state) {
        return;
    }
    state.stop.store(false, Ordering::SeqCst);
    let stop = state.stop.clone();
    let app2 = app.clone();
    let handle = std::thread::spawn(move || monitor_loop(app2, stop));
    *state.handle.lock().unwrap() = Some(handle);
}

pub fn stop(state: &MonitorState) {
    state.stop.store(true, Ordering::SeqCst);
    if let Some(h) = state.handle.lock().unwrap().take() {
        let _ = h.join();
    }
}

// ── 监听主循环 ──────────────────────────────────────────────

fn current_settings(app: &AppHandle) -> Settings {
    app.state::<SettingsState>().0.lock().unwrap().clone()
}

fn responsive_sleep(stop: &AtomicBool, secs: u64) {
    let mut left = secs * 10;
    while left > 0 && !stop.load(Ordering::SeqCst) {
        std::thread::sleep(Duration::from_millis(100));
        left -= 1;
    }
}

fn monitor_loop(app: AppHandle, stop: Arc<AtomicBool>) {
    emit_log(&app, "WeLink 监听已启动");
    let mut st = load_state(&app);

    while !stop.load(Ordering::SeqCst) {
        let settings = current_settings(&app);

        let groups: Vec<_> = settings.welink_groups.iter().filter(|g| g.enabled).collect();
        for g in &groups {
            if stop.load(Ordering::SeqCst) {
                break;
            }
            poll_group(&app, &settings, g.group_id.as_str(),
                       if g.group_name.is_empty() { &g.group_id } else { &g.group_name },
                       &mut st);
        }
        save_state(&app, &st);

        responsive_sleep(&stop, settings.welink_poll_interval.max(1) as u64);
    }
    emit_log(&app, "WeLink 监听已停止");
}

fn poll_group(app: &AppHandle, settings: &Settings, group_id: &str, group_name: &str, st: &mut WelinkState) {
    let msgs = match cli::query_history(settings, group_id, 20) {
        Ok(items) => parse_messages(&items),
        Err(e) => {
            if e.contains("429") {
                std::thread::sleep(Duration::from_secs(5));
            } else {
                emit_log(app, format!("[{group_name}] 拉取消息失败: {e}"));
            }
            return;
        }
    };
    if msgs.is_empty() {
        return;
    }

    let last_seen = st.last_ids.get(group_id).copied();
    // 按 msgId 升序处理（最旧在前）
    let mut ordered = msgs.clone();
    ordered.sort_by_key(|m| m.msg_id);

    for m in &ordered {
        let msg_id = m.msg_id;
        match last_seen {
            None => {
                // 首次见到该群：记录基线，不回溯历史
                st.last_ids.insert(group_id.to_string(), msg_id);
                break;
            }
            Some(seen) if msg_id <= seen => continue,
            _ => {}
        }

        let norm = normalize(&m.content);
        if norm.contains(&settings.welink_start_cmd) {
            st.sessions.insert(group_id.to_string(), Session {
                start_msg_id: msg_id,
                start_time: m.server_send_time,
                group_name: group_name.to_string(),
            });
            emit_log(app, format!("[{group_name}] 开始录制 (msgId={msg_id})"));
        } else if norm.contains(&settings.welink_end_cmd) && st.sessions.contains_key(group_id) {
            let rec = st.sessions.remove(group_id).unwrap();
            emit_log(app, format!("[{group_name}] 结束录制，正在导出…"));
            finish(app, settings, group_id, group_name, &rec, msg_id, m.server_send_time, st);
        } else if !settings.welink_summary_cmd.is_empty() && norm.contains(&settings.welink_summary_cmd) {
            let mode = parse_summary_cmd(&settings.welink_summary_cmd, &norm);
            emit_log(app, format!("[{group_name}] 收到总结命令，定位范围…"));
            finish_summary(app, settings, group_id, group_name, msg_id, m.server_send_time, mode, st);
        }

        st.last_ids.insert(group_id.to_string(), msg_id);
    }
}

// ── 结束录制 / 总结 ─────────────────────────────────────────

fn fetch_100(settings: &Settings, group_id: &str) -> Vec<WlMessage> {
    cli::query_history(settings, group_id, 100)
        .map(|items| parse_messages(&items))
        .unwrap_or_default()
}

fn finish(app: &AppHandle, settings: &Settings, group_id: &str, group_name: &str,
          rec: &Session, end_msg_id: i64, end_time: i64, st: &mut WelinkState) {
    let all = fetch_100(settings, group_id);
    if all.is_empty() {
        emit_log(app, format!("[{group_name}] 获取到 0 条消息，放弃"));
        return;
    }
    let mut in_range: Vec<WlMessage> = all.into_iter()
        .filter(|m| rec.start_msg_id <= m.msg_id && m.msg_id <= end_msg_id)
        .collect();
    // ③ 剔除开始/结束/总结等系统命令，只保留核心记录
    in_range.retain(|m| !is_system_cmd(settings, &m.content));
    in_range.sort_by_key(|m| m.server_send_time);

    let chat_id = format!("{group_id}_{}", rec.start_msg_id);
    save_chatlog(app, settings, group_name, &chat_id, rec.start_time, &mut in_range, st);
    // 更新「上次抓取点」
    st.last_captured.insert(group_id.to_string(), end_time);
}

fn finish_summary(app: &AppHandle, settings: &Settings, group_id: &str, group_name: &str,
                  _summary_msg_id: i64, summary_time: i64, mode: SummaryMode, st: &mut WelinkState) {
    let all = fetch_100(settings, group_id);
    if all.is_empty() {
        emit_log(app, format!("[{group_name}] 获取消息失败，放弃总结"));
        return;
    }
    let mut sorted = all.clone();
    sorted.sort_by_key(|m| m.server_send_time);

    let find = |id: &str, dt_ms: i64| -> Option<&WlMessage> {
        sorted.iter().find(|m| {
            dt_ms <= m.server_send_time && m.server_send_time < dt_ms + 60_000
                && (m.sender.contains(id) || id.contains(&m.sender))
        })
    };
    let last = st.last_captured.get(group_id).copied().unwrap_or(0);
    // 抓「上次抓取点 → 截止」之间、未抓过的（用法① / ③ 共用）
    let to_cutoff = |all: &[WlMessage], end_t: i64| -> (Vec<WlMessage>, i64) {
        let r: Vec<WlMessage> = all
            .iter()
            .filter(|m| m.server_send_time > last && m.server_send_time <= end_t)
            .cloned()
            .collect();
        let start_t = if last > 0 { last } else { r.first().map(|m| m.server_send_time).unwrap_or(end_t) };
        (r, start_t)
    };

    let (mut in_range, start_time, end_boundary): (Vec<WlMessage>, i64, i64) = match mode {
        // 用法②（两个时间）：显式 起点消息 → 结束消息
        SummaryMode::Range { start_id, start_dt, end_id, end_dt } => {
            let Some(start_msg) = find(&start_id, start_dt).cloned() else {
                emit_log(app, format!("[{group_name}] 未找到起始消息 {start_id}"));
                return;
            };
            let (end_msg_id, end_t) = match find(&end_id, end_dt) {
                Some(m) => (m.msg_id, m.server_send_time),
                None => {
                    emit_log(app, format!("[{group_name}] 未找到结束消息，截至总结命令"));
                    (i64::MAX, summary_time)
                }
            };
            let r: Vec<WlMessage> = all
                .iter()
                .filter(|m| start_msg.msg_id <= m.msg_id && m.msg_id <= end_msg_id)
                .cloned()
                .collect();
            (r, start_msg.server_send_time, end_t)
        }
        // 用法①（一个时间）：截止 = 指定消息的时间
        SummaryMode::ToMessage { id, dt_ms } => {
            let Some(end_msg) = find(&id, dt_ms).cloned() else {
                emit_log(app, format!("[{group_name}] 未找到消息 {id}"));
                return;
            };
            let end_t = end_msg.server_send_time;
            let (r, start_t) = to_cutoff(&all, end_t);
            (r, start_t, end_t)
        }
        // 用法③（不带时间）：截止 = 这条总结命令自己的时间
        SummaryMode::ToNow => {
            let (r, start_t) = to_cutoff(&all, summary_time);
            (r, start_t, summary_time)
        }
    };

    // ③ 剔除系统命令消息，只保留核心记录
    in_range.retain(|m| !is_system_cmd(settings, &m.content));
    in_range.sort_by_key(|m| m.server_send_time);
    let chat_id = format!("{group_id}_{end_boundary}_s");
    save_chatlog(app, settings, group_name, &chat_id, start_time, &mut in_range, st);
    st.last_captured.insert(group_id.to_string(), end_boundary);
}

// ── 手动导入聊天记录（zip） ─────────────────────────────────

pub fn import_chatlog(
    app: &AppHandle,
    settings: &Settings,
    zip_path: &str,
    group_name: &str,
) -> Result<String, String> {
    if settings.output_dir.trim().is_empty() {
        return Err("未设置输出目录".to_string());
    }
    emit_log(app, format!("解析聊天记录: {zip_path}"));
    let parsed = chatlog::parse_zip(zip_path)?;
    if !parsed.summary.is_empty() {
        emit_log(app, parsed.summary.clone());
    }
    let count = parsed.count;

    let html2 = process_email_html(settings, &parsed.html, &parsed.images);
    let md = htmlmd::html_to_md(app, settings, &html2);
    let title = if group_name.trim().is_empty() {
        parsed.stem.clone()
    } else {
        group_name.to_string()
    };
    let received = local_received(parsed.start_time);

    match output::save(settings, output::SRC_WELINK, &received, &title, &html2, &md)? {
        Some(saved) => {
            emit_log(app, format!("聊天记录已保存（{count} 条）: {}", saved.base_name));
            Ok(saved.base_name)
        }
        None => {
            emit_log(app, "已存在，跳过".to_string());
            Ok(String::new())
        }
    }
}

fn local_received(ms: i64) -> String {
    Local
        .timestamp_millis_opt(ms)
        .single()
        .map(|dt| dt.format("%Y-%m-%dT%H:%M:%S").to_string())
        .unwrap_or_else(|| "1970-01-01T00:00:00".to_string())
}

fn save_chatlog(app: &AppHandle, settings: &Settings, group_name: &str, chat_id: &str,
                start_time: i64, msgs: &mut [WlMessage], st: &mut WelinkState) {
    if st.saved_chat_ids.contains(chat_id) {
        emit_log(app, format!("[{group_name}] 已导出过，跳过"));
        return;
    }
    if msgs.is_empty() {
        emit_log(app, format!("[{group_name}] 范围内 0 条，跳过"));
        return;
    }
    image::localize_messages(settings, msgs);
    let html = render::msgs_to_html(msgs);
    let md = htmlmd::html_to_md(app, settings, &html);
    let received = local_received(start_time);

    match output::save(settings, output::SRC_WELINK, &received, group_name, &html, &md) {
        Ok(Some(saved)) => {
            emit_log(app, format!("[{group_name}] 已保存 ({} 条): {}", msgs.len(), saved.base_name));
            st.saved_chat_ids.insert(chat_id.to_string());
        }
        Ok(None) => { st.saved_chat_ids.insert(chat_id.to_string()); }
        Err(e) => emit_log(app, format!("[{group_name}] 保存失败: {e}")),
    }
}
