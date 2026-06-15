//! WeLink 流：轮询 → 命令录制 / 按天归档 → HTML/MD → 落盘（DESIGN.md §5.2）。
//! 移植自旧 pyqt_client/modules/welink/monitor.py，去掉服务器上传，改为本地落盘。

mod cli;
mod image;
mod render;

use std::collections::{HashMap, HashSet};
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread::JoinHandle;
use std::time::Duration;

use chrono::{Local, NaiveDate, TimeZone, Timelike};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use tauri::{AppHandle, Manager};

use crate::events::emit_log;
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

struct SummaryArgs {
    name1: String,
    id1: String,
    dt1_ms: i64,
    end: Option<(String, String, i64)>,
}

fn local_ms(date: &str, time: &str) -> Option<i64> {
    let dt = chrono::NaiveDateTime::parse_from_str(&format!("{date} {time}"), "%Y-%m-%d %H:%M").ok()?;
    Local.from_local_datetime(&dt).single().map(|d| d.timestamp_millis())
}

/// 解析总结命令：4 段（单点）或 8 段（区间，自动容错顺序）。
fn parse_summary_cmd(prefix: &str, norm: &str) -> Option<SummaryArgs> {
    let idx = norm.find(prefix)?;
    let rest = norm[idx + prefix.len()..].trim();
    let parts: Vec<&str> = rest.split_whitespace().collect();
    if parts.len() >= 8 {
        let a = local_ms(parts[2], parts[3])?;
        let b = local_ms(parts[6], parts[7])?;
        if a <= b {
            Some(SummaryArgs {
                name1: parts[0].into(), id1: parts[1].into(), dt1_ms: a,
                end: Some((parts[4].into(), parts[5].into(), b)),
            })
        } else {
            Some(SummaryArgs {
                name1: parts[4].into(), id1: parts[5].into(), dt1_ms: b,
                end: Some((parts[0].into(), parts[1].into(), a)),
            })
        }
    } else if parts.len() >= 4 {
        let a = local_ms(parts[2], parts[3])?;
        Some(SummaryArgs { name1: parts[0].into(), id1: parts[1].into(), dt1_ms: a, end: None })
    } else {
        None
    }
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
    /// 手动录制的时间区间（毫秒），按天归档时据此剔除已覆盖片段。
    #[serde(default)]
    manual_intervals: HashMap<String, Vec<(i64, i64)>>,
    #[serde(default)]
    saved_chat_ids: HashSet<String>,
    #[serde(default)]
    last_daily_date: String,
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

        // 按天归档触发检查
        if settings.welink_daily_record {
            maybe_run_daily(&app, &settings, &mut st);
        }

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
            match parse_summary_cmd(&settings.welink_summary_cmd, &norm) {
                Some(sa) => {
                    emit_log(app, format!("[{group_name}] 收到总结命令，定位范围…"));
                    finish_summary(app, settings, group_id, group_name, msg_id, m.server_send_time, &sa, st);
                }
                None => emit_log(app, format!("[{group_name}] 总结命令格式错误")),
            }
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
    in_range.sort_by_key(|m| m.server_send_time);

    let chat_id = format!("{group_id}_{}", rec.start_msg_id);
    // 记录手动区间供按天归档剔除
    st.manual_intervals.entry(group_id.to_string()).or_default()
        .push((rec.start_time, end_time));

    save_chatlog(app, settings, group_name, &chat_id, rec.start_time, &mut in_range, st);
}

fn finish_summary(app: &AppHandle, settings: &Settings, group_id: &str, group_name: &str,
                  summary_msg_id: i64, summary_time: i64, sa: &SummaryArgs, st: &mut WelinkState) {
    let all = fetch_100(settings, group_id);
    if all.is_empty() {
        emit_log(app, format!("[{group_name}] 获取消息失败，放弃总结"));
        return;
    }
    let mut sorted = all.clone();
    sorted.sort_by_key(|m| m.server_send_time);

    let find = |name_id: &str, dt_ms: i64| -> Option<&WlMessage> {
        sorted.iter().find(|m| {
            dt_ms <= m.server_send_time && m.server_send_time < dt_ms + 60_000
                && (m.sender.contains(name_id) || name_id.contains(&m.sender))
        })
    };

    let start_msg = match find(&sa.id1, sa.dt1_ms) {
        Some(m) => m.clone(),
        None => {
            emit_log(app, format!("[{group_name}] 未找到起始消息 {}/{}", sa.name1, sa.id1));
            return;
        }
    };

    let (end_msg_id, _end_time) = match &sa.end {
        Some((_n, eid, dt_ms)) => match find(eid, *dt_ms) {
            Some(m) => (m.msg_id, m.server_send_time),
            None => {
                emit_log(app, format!("[{group_name}] 未找到结束消息，截至总结命令前"));
                (summary_msg_id - 1, summary_time)
            }
        },
        None => (summary_msg_id - 1, summary_time),
    };

    let start_msg_id = start_msg.msg_id;
    let mut in_range: Vec<WlMessage> = all.into_iter()
        .filter(|m| start_msg_id <= m.msg_id && m.msg_id <= end_msg_id)
        .collect();
    in_range.sort_by_key(|m| m.server_send_time);

    let chat_id = format!("{group_id}_{start_msg_id}_s");
    save_chatlog(app, settings, group_name, &chat_id, start_msg.server_send_time, &mut in_range, st);
}

// ── 按天归档 ────────────────────────────────────────────────

fn maybe_run_daily(app: &AppHandle, settings: &Settings, st: &mut WelinkState) {
    let now = Local::now();
    let today = now.format("%Y-%m-%d").to_string();
    if st.last_daily_date == today {
        return;
    }
    // 解析触发时间
    let (hh, mm) = parse_hhmm(&settings.welink_daily_time);
    if now.hour() < hh || (now.hour() == hh && now.minute() < mm) {
        return; // 今天还没到触发时间
    }

    // 归档昨天
    let yesterday = (now - chrono::Duration::days(1)).format("%Y-%m-%d").to_string();
    st.last_daily_date = today;
    emit_log(app, format!("按天归档开始: {yesterday}"));

    let groups: Vec<_> = settings.welink_groups.iter().filter(|g| g.enabled).cloned().collect();
    for g in groups {
        let gname = if g.group_name.is_empty() { g.group_id.clone() } else { g.group_name.clone() };
        run_daily_group(app, settings, &g.group_id, &gname, &yesterday, st);
    }
    emit_log(app, format!("按天归档完成: {yesterday}"));
}

fn parse_hhmm(s: &str) -> (u32, u32) {
    let mut it = s.split(':');
    let hh = it.next().and_then(|x| x.parse().ok()).unwrap_or(1);
    let mm = it.next().and_then(|x| x.parse().ok()).unwrap_or(0);
    (hh, mm)
}

fn day_range_ms(date: &str) -> Option<(i64, i64)> {
    let d = NaiveDate::parse_from_str(date, "%Y-%m-%d").ok()?;
    let start = Local.from_local_datetime(&d.and_hms_opt(0, 0, 0)?).single()?.timestamp_millis();
    Some((start, start + 86_400_000))
}

fn run_daily_group(app: &AppHandle, settings: &Settings, group_id: &str, group_name: &str,
                   date: &str, st: &mut WelinkState) {
    let Some((day_start, day_end)) = day_range_ms(date) else { return };
    let all = fetch_100(settings, group_id);
    let mut day_msgs: Vec<WlMessage> = all.into_iter()
        .filter(|m| day_start <= m.server_send_time && m.server_send_time < day_end)
        .collect();
    if day_msgs.is_empty() {
        emit_log(app, format!("[{group_name}] {date} 无消息，跳过"));
        return;
    }
    day_msgs.sort_by_key(|m| m.server_send_time);

    let chat_id = format!("{group_id}_{date}_daily");
    if st.saved_chat_ids.contains(&chat_id) {
        return;
    }

    image::localize_messages(settings, &mut day_msgs);
    let html = render::msgs_to_html(&day_msgs);

    // 剔除已被手动录制覆盖的区间
    let excluded = st.manual_intervals.get(group_id).cloned().unwrap_or_default();
    let filtered = render::filter_daily_html(&html, &excluded);
    if filtered.trim().is_empty() {
        emit_log(app, format!("[{group_name}] {date} 全部已手动覆盖，跳过"));
        st.saved_chat_ids.insert(chat_id);
        return;
    }

    let md = htmlmd::html_to_md(&filtered);
    let title = format!("{group_name}_{date}_全天");
    let received = local_received(day_msgs.first().map(|m| m.server_send_time).unwrap_or(day_start));
    match output::save(settings, &received, &title, &filtered, &md) {
        Ok(Some(saved)) => {
            emit_log(app, format!("[{group_name}] 按天归档已保存: {}", saved.base_name));
            st.saved_chat_ids.insert(chat_id);
        }
        Ok(None) => { st.saved_chat_ids.insert(chat_id); }
        Err(e) => emit_log(app, format!("[{group_name}] 按天归档保存失败: {e}")),
    }
}

// ── 落盘 ────────────────────────────────────────────────────

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
    let md = htmlmd::html_to_md(&html);
    let received = local_received(start_time);

    match output::save(settings, &received, group_name, &html, &md) {
        Ok(Some(saved)) => {
            emit_log(app, format!("[{group_name}] 已保存 ({} 条): {}", msgs.len(), saved.base_name));
            st.saved_chat_ids.insert(chat_id.to_string());
        }
        Ok(None) => { st.saved_chat_ids.insert(chat_id.to_string()); }
        Err(e) => emit_log(app, format!("[{group_name}] 保存失败: {e}")),
    }
}
