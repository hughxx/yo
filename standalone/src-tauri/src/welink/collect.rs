//! 自动收集：独立后台循环，按「周期收集 / 每日定时 / 时间段限定」自动归档新消息。
//! 与「命令触发」监听完全独立，各自一个开关、一个线程、一份状态文件。
//! 无需任何聊天命令——到点/到周期就把各群「上次收集点 → 现在」的新消息落盘。

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread::JoinHandle;
use std::time::Duration;

use chrono::{Local, TimeZone, Timelike};
use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Manager};

use crate::events::emit_log;
use crate::settings::{Settings, SettingsState};
use crate::{htmlmd, output};

use super::{image, render, WlMessage};

// ── 持久化状态 ──────────────────────────────────────────────

#[derive(Debug, Default, Serialize, Deserialize)]
struct CollectState {
    /// 每群「上次收集截止时间」(ms)。下次只收集晚于它的新消息。
    #[serde(default)]
    collect_last: HashMap<String, i64>,
    /// 上次「周期收集」触发时刻 (ms)。0 = 尚未建立基线。
    #[serde(default)]
    last_period_ms: i64,
    /// 已触发过的每日定时点，元素形如 "2026-06-15 09:00"，仅保留当天。
    #[serde(default)]
    daily_fired: Vec<String>,
}

fn state_path(app: &AppHandle) -> Option<PathBuf> {
    let dir = app.path().app_config_dir().ok()?;
    std::fs::create_dir_all(&dir).ok();
    Some(dir.join("collect_state.json"))
}

fn load_state(app: &AppHandle) -> CollectState {
    state_path(app)
        .and_then(|p| std::fs::read_to_string(p).ok())
        .and_then(|t| serde_json::from_str(&t).ok())
        .unwrap_or_default()
}

fn save_state(app: &AppHandle, st: &CollectState) {
    if let Some(p) = state_path(app) {
        if let Ok(t) = serde_json::to_string_pretty(st) {
            let _ = std::fs::write(p, t);
        }
    }
}

// ── 监听控制状态（managed，与命令监听互不影响） ─────────────

pub struct CollectMonitorState {
    pub stop: Arc<AtomicBool>,
    pub handle: Mutex<Option<JoinHandle<()>>>,
}

impl Default for CollectMonitorState {
    fn default() -> Self {
        CollectMonitorState {
            stop: Arc::new(AtomicBool::new(false)),
            handle: Mutex::new(None),
        }
    }
}

pub fn is_running(state: &CollectMonitorState) -> bool {
    state
        .handle
        .lock()
        .unwrap()
        .as_ref()
        .map(|h| !h.is_finished())
        .unwrap_or(false)
}

pub fn start(app: &AppHandle, state: &CollectMonitorState) {
    if is_running(state) {
        return;
    }
    state.stop.store(false, Ordering::SeqCst);
    let stop = state.stop.clone();
    let app2 = app.clone();
    let handle = std::thread::spawn(move || collect_loop(app2, stop));
    *state.handle.lock().unwrap() = Some(handle);
}

pub fn stop(state: &CollectMonitorState) {
    state.stop.store(true, Ordering::SeqCst);
    if let Some(h) = state.handle.lock().unwrap().take() {
        let _ = h.join();
    }
}

// ── 主循环 ──────────────────────────────────────────────────

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

fn parse_hhmm(s: &str) -> (u32, u32) {
    let mut it = s.split(':');
    let hh = it.next().and_then(|x| x.trim().parse().ok()).unwrap_or(0);
    let mm = it.next().and_then(|x| x.trim().parse().ok()).unwrap_or(0);
    (hh.min(23), mm.min(59))
}

fn collect_loop(app: AppHandle, stop: Arc<AtomicBool>) {
    emit_log(&app, "自动收集已启动");
    let mut st = load_state(&app);

    while !stop.load(Ordering::SeqCst) {
        let settings = current_settings(&app);
        let now = Local::now();
        let now_ms = now.timestamp_millis();

        // 时间段限定：仅收集落在 [start, end] 时段内的消息（按消息自身时刻判断）
        let window = if settings.collect_window_enabled {
            let (sh, sm) = parse_hhmm(&settings.collect_window_start);
            let (eh, em) = parse_hhmm(&settings.collect_window_end);
            Some((sh * 60 + sm, eh * 60 + em))
        } else {
            None
        };

        // ① 周期收集：每 N 小时自动收集一次
        if settings.collect_periodic_enabled {
            let period_ms = (settings.collect_period_hours.max(1) as i64) * 3_600_000;
            if st.last_period_ms == 0 {
                st.last_period_ms = now_ms; // 首次仅建立基线，不立刻收集
            } else if now_ms - st.last_period_ms >= period_ms {
                emit_log(&app, "周期收集触发".to_string());
                collect_all_groups(&app, &settings, &mut st, now_ms, window);
                st.last_period_ms = now_ms;
            }
        }

        // ② 每日定时：到达任一定时点（当天仅触发一次）
        if settings.collect_daily_enabled {
            let today = now.format("%Y-%m-%d").to_string();
            let now_min = now.hour() * 60 + now.minute();
            // 跨天清理：仅保留当天已触发记录
            st.daily_fired.retain(|k| k.starts_with(&today));
            for t in &settings.collect_daily_times {
                let key = format!("{today} {t}");
                if st.daily_fired.contains(&key) {
                    continue;
                }
                let (h, m) = parse_hhmm(t);
                if now_min >= h * 60 + m {
                    emit_log(&app, format!("每日定时收集触发: {t}"));
                    collect_all_groups(&app, &settings, &mut st, now_ms, window);
                    st.daily_fired.push(key);
                }
            }
        }

        save_state(&app, &st);
        responsive_sleep(&stop, settings.collect_poll_interval.max(10) as u64);
    }
    emit_log(&app, "自动收集已停止");
}

fn collect_all_groups(
    app: &AppHandle,
    settings: &Settings,
    st: &mut CollectState,
    now_ms: i64,
    window: Option<(u32, u32)>,
) {
    let groups: Vec<_> = settings.collect_groups.iter().filter(|g| g.enabled).cloned().collect();
    if groups.is_empty() {
        emit_log(app, "未配置收集群，跳过".to_string());
        return;
    }
    for g in groups {
        if g.group_id.trim().is_empty() {
            continue;
        }
        let gname = if g.group_name.is_empty() { g.group_id.clone() } else { g.group_name.clone() };
        collect_group(app, settings, &g.group_id, &gname, st, now_ms, window);
    }
}

/// 判断消息时刻是否落在时段窗口内（支持跨午夜，如 22:00–06:00）。
fn in_window(ms: i64, win: (u32, u32)) -> bool {
    let (start, end) = win;
    let Some(dt) = Local.timestamp_millis_opt(ms).single() else { return true };
    let t = dt.hour() * 60 + dt.minute();
    if start <= end {
        t >= start && t < end
    } else {
        t >= start || t < end
    }
}

fn collect_group(
    app: &AppHandle,
    settings: &Settings,
    group_id: &str,
    group_name: &str,
    st: &mut CollectState,
    now_ms: i64,
    window: Option<(u32, u32)>,
) {
    let all = super::fetch_100(settings, group_id);
    if all.is_empty() {
        return;
    }

    // 首次收集：建立基线（取最新消息时刻），不回溯历史
    let Some(last) = st.collect_last.get(group_id).copied() else {
        let newest = all.iter().map(|m| m.server_send_time).max().unwrap_or(now_ms);
        st.collect_last.insert(group_id.to_string(), newest);
        emit_log(app, format!("[{group_name}] 已建立收集基线，下次起收集新消息"));
        return;
    };

    let mut msgs: Vec<WlMessage> = all
        .into_iter()
        .filter(|m| m.server_send_time > last)
        .filter(|m| !super::is_system_cmd(settings, &m.content))
        .filter(|m| window.map(|w| in_window(m.server_send_time, w)).unwrap_or(true))
        .collect();
    msgs.sort_by_key(|m| m.server_send_time);

    if msgs.is_empty() {
        st.collect_last.insert(group_id.to_string(), now_ms);
        return;
    }

    let start_time = msgs.first().map(|m| m.server_send_time).unwrap_or(now_ms);
    save_collected(app, settings, group_name, start_time, &mut msgs);
    st.collect_last.insert(group_id.to_string(), now_ms);
}

fn save_collected(
    app: &AppHandle,
    settings: &Settings,
    group_name: &str,
    start_time: i64,
    msgs: &mut [WlMessage],
) {
    image::localize_messages(settings, msgs);
    let html = render::msgs_to_html(msgs);
    let md = htmlmd::html_to_md(app, settings, &html);
    let received = super::local_received(start_time);

    match output::save(settings, output::SRC_WELINK, &received, group_name, &html, &md) {
        Ok(Some(saved)) => emit_log(
            app,
            format!("[{group_name}] 自动收集已保存 ({} 条): {}", msgs.len(), saved.base_name),
        ),
        Ok(None) => emit_log(app, format!("[{group_name}] 已存在，跳过")),
        Err(e) => emit_log(app, format!("[{group_name}] 自动收集保存失败: {e}")),
    }
}
