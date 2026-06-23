//! 云同步：每天定时（或手动）在 shell 里执行用户自己写的命令，
//! 把输出目录同步到云端向量库 / 对象存储 / 自建服务器（rclone / scp / robocopy …）。
//! 程序只负责调度与执行 + 收集日志，不内置任何上传逻辑或凭据。
//!
//! 执行契约：
//!   - Windows 用 `cmd /C <命令>`，类 Unix 用 `sh -c <命令>`
//!   - 工作目录 = 输出目录（脚本里可直接用相对路径）
//!   - 注入环境变量 OUTPUT_DIR = 输出目录绝对路径
//!   - 退出码 0 = 成功；非 0 = 失败，stdout/stderr 进运行日志

use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread::JoinHandle;
use std::time::Duration;

use chrono::{Local, Timelike};
use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Manager};

use crate::events::emit_log;
use crate::settings::{Settings, SettingsState};

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

// ── 状态 ────────────────────────────────────────────────────

#[derive(Debug, Default, Clone, Serialize, Deserialize)]
pub struct SyncStatus {
    /// 后台定时线程是否在运行
    #[serde(default, skip_deserializing)]
    pub running: bool,
    /// 上次执行时间 "YYYY-MM-DD HH:MM:SS"（空 = 从未执行）
    #[serde(default)]
    pub last_sync: String,
    #[serde(default)]
    pub last_ok: bool,
    #[serde(default)]
    pub last_msg: String,
    /// 今日已触发定时同步的日期 "YYYY-MM-DD"，避免同一天重复触发（前端忽略此字段）。
    #[serde(default)]
    pub daily_fired_date: String,
}

pub struct SyncState {
    pub stop: Arc<AtomicBool>,
    pub handle: Mutex<Option<JoinHandle<()>>>,
    pub status: Mutex<SyncStatus>,
    /// 防止上一次未跑完就再次触发（定时与手动并发）
    pub busy: Arc<AtomicBool>,
}

impl Default for SyncState {
    fn default() -> Self {
        SyncState {
            stop: Arc::new(AtomicBool::new(false)),
            handle: Mutex::new(None),
            status: Mutex::new(SyncStatus::default()),
            busy: Arc::new(AtomicBool::new(false)),
        }
    }
}

fn status_path(app: &AppHandle) -> Option<PathBuf> {
    let dir = app.path().app_config_dir().ok()?;
    std::fs::create_dir_all(&dir).ok();
    Some(dir.join("sync_state.json"))
}

/// 启动时把上次同步结果读回来（让「上次同步时间」跨重启可见）。
pub fn load_status(app: &AppHandle, state: &SyncState) {
    if let Some(saved) = status_path(app)
        .and_then(|p| std::fs::read_to_string(p).ok())
        .and_then(|t| serde_json::from_str::<SyncStatus>(&t).ok())
    {
        let mut st = state.status.lock().unwrap();
        st.last_sync = saved.last_sync;
        st.last_ok = saved.last_ok;
        st.last_msg = saved.last_msg;
        st.daily_fired_date = saved.daily_fired_date;
    }
}

fn persist_status(app: &AppHandle, st: &SyncStatus) {
    if let Some(p) = status_path(app) {
        if let Ok(t) = serde_json::to_string_pretty(st) {
            let _ = std::fs::write(p, t);
        }
    }
}

pub fn status(state: &SyncState) -> SyncStatus {
    let mut s = state.status.lock().unwrap().clone();
    s.running = is_running(state);
    s
}

// ── 定时线程控制 ────────────────────────────────────────────

pub fn is_running(state: &SyncState) -> bool {
    state
        .handle
        .lock()
        .unwrap()
        .as_ref()
        .map(|h| !h.is_finished())
        .unwrap_or(false)
}

pub fn start(app: &AppHandle, state: &SyncState) {
    if is_running(state) {
        return;
    }
    state.stop.store(false, Ordering::SeqCst);
    let stop = state.stop.clone();
    let app2 = app.clone();
    let handle = std::thread::spawn(move || timer_loop(app2, stop));
    *state.handle.lock().unwrap() = Some(handle);
}

pub fn stop(state: &SyncState) {
    state.stop.store(true, Ordering::SeqCst);
    if let Some(h) = state.handle.lock().unwrap().take() {
        let _ = h.join();
    }
}

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
    let hh = it.next().and_then(|x| x.trim().parse().ok()).unwrap_or(2);
    let mm = it.next().and_then(|x| x.trim().parse().ok()).unwrap_or(0);
    (hh.min(23), mm.min(59))
}

fn timer_loop(app: AppHandle, stop: Arc<AtomicBool>) {
    emit_log(&app, "云同步定时已启动");
    while !stop.load(Ordering::SeqCst) {
        let settings = current_settings(&app);
        if settings.sync_enabled && !settings.sync_command.trim().is_empty() {
            let now = Local::now();
            let today = now.format("%Y-%m-%d").to_string();
            let (h, m) = parse_hhmm(&settings.sync_daily_time);
            let now_min = now.hour() * 60 + now.minute();

            let state = app.state::<SyncState>();
            let already = state.status.lock().unwrap().daily_fired_date == today;
            if !already && now_min >= h * 60 + m {
                // 先记今日已触发（成功失败都不再重复），再执行
                {
                    let mut st = state.status.lock().unwrap();
                    st.daily_fired_date = today;
                    persist_status(&app, &st);
                }
                let _ = run_once(&app, &settings, &state);
            }
        }
        // 每 30 秒检查一次是否到达每日时刻（非用户可见频率）
        responsive_sleep(&stop, 30);
    }
    emit_log(&app, "云同步定时已停止");
}

// ── 执行 ────────────────────────────────────────────────────

/// 执行一次同步命令（定时与手动共用）。重叠调用直接返回错误。
pub fn run_once(app: &AppHandle, settings: &Settings, state: &SyncState) -> Result<(), String> {
    let cmd_str = settings.sync_command.trim().to_string();
    if cmd_str.is_empty() {
        return Err("未配置同步命令".to_string());
    }
    let out_dir = settings.output_dir.trim().to_string();
    if out_dir.is_empty() {
        return Err("未设置输出目录".to_string());
    }
    // 防重叠
    if state.busy.swap(true, Ordering::SeqCst) {
        return Err("上一次同步尚未结束".to_string());
    }

    emit_log(app, "同步开始…");
    let result = exec(app, &cmd_str, &out_dir);
    state.busy.store(false, Ordering::SeqCst);

    let now = Local::now().format("%Y-%m-%d %H:%M:%S").to_string();
    {
        let mut st = state.status.lock().unwrap();
        st.last_sync = now;
        match &result {
            Ok(()) => {
                st.last_ok = true;
                st.last_msg = "成功".to_string();
            }
            Err(e) => {
                st.last_ok = false;
                st.last_msg = e.clone();
            }
        }
        persist_status(app, &st);
    }
    match &result {
        Ok(()) => emit_log(app, "同步成功"),
        Err(e) => emit_log(app, format!("同步失败: {e}")),
    }
    result
}

fn exec(app: &AppHandle, cmd_str: &str, cwd: &str) -> Result<(), String> {
    #[cfg(windows)]
    let mut cmd = {
        let mut c = Command::new("cmd");
        c.args(["/C", cmd_str]);
        c
    };
    #[cfg(not(windows))]
    let mut cmd = {
        let mut c = Command::new("sh");
        c.args(["-c", cmd_str]);
        c
    };

    cmd.current_dir(cwd)
        .env("OUTPUT_DIR", cwd)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }

    let out = cmd.output().map_err(|e| format!("启动命令失败: {e}"))?;

    let so = String::from_utf8_lossy(&out.stdout);
    if !so.trim().is_empty() {
        emit_log(app, format!("[同步输出] {}", so.trim()));
    }
    let se = String::from_utf8_lossy(&out.stderr);
    if !se.trim().is_empty() {
        emit_log(app, format!("[同步stderr] {}", se.trim()));
    }

    if out.status.success() {
        Ok(())
    } else {
        Err(format!("退出码 {}", out.status.code().unwrap_or(-1)))
    }
}
