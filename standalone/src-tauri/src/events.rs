//! 统一的前端日志事件。前端监听 "log" 事件追加到运行日志面板。

use chrono::Local;
use tauri::{AppHandle, Emitter};

pub fn emit_log(app: &AppHandle, line: impl AsRef<str>) {
    let ts = Local::now().format("%H:%M:%S");
    let _ = app.emit("log", format!("[{ts}] {}", line.as_ref()));
}
