//! 暴露给前端的 Tauri 命令。

use std::collections::HashSet;

use tauri::{AppHandle, State};

use crate::email::{self, EmailSummary, ScanReport};
use crate::output::{self, OutputEntry};
use crate::settings::{self, Settings, SettingsState};
use crate::sidecar;
use crate::store::{self, ProcessedState};
use crate::welink::{self, MonitorState};

// ── 基础 ────────────────────────────────────────────────────

#[tauri::command]
pub fn app_version() -> String {
    env!("CARGO_PKG_VERSION").to_string()
}

#[tauri::command]
pub fn ping() -> String {
    "pong".to_string()
}

// ── 设置 ────────────────────────────────────────────────────

#[tauri::command]
pub fn get_settings(state: State<'_, SettingsState>) -> Settings {
    state.0.lock().unwrap().clone()
}

#[tauri::command]
pub fn save_settings(
    app: AppHandle,
    state: State<'_, SettingsState>,
    settings: Settings,
) -> Result<(), String> {
    settings::save(&app, &settings).map_err(|e| e.to_string())?;
    *state.0.lock().unwrap() = settings;
    Ok(())
}

// ── 邮件 ────────────────────────────────────────────────────

#[tauri::command]
pub async fn list_folders(
    app: AppHandle,
    sstate: State<'_, SettingsState>,
) -> Result<Vec<String>, String> {
    let settings = sstate.0.lock().unwrap().clone();
    let app2 = app.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let v = sidecar::run_outlook(&app2, &settings, &["folder-list"])?;
        serde_json::from_value::<Vec<String>>(v).map_err(|e| e.to_string())
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
pub async fn email_list(
    app: AppHandle,
    sstate: State<'_, SettingsState>,
) -> Result<Vec<EmailSummary>, String> {
    let settings = sstate.0.lock().unwrap().clone();
    let app2 = app.clone();
    tauri::async_runtime::spawn_blocking(move || email::list(&app2, &settings, 300))
        .await
        .map_err(|e| e.to_string())?
}

#[tauri::command]
pub async fn email_scan(
    app: AppHandle,
    sstate: State<'_, SettingsState>,
    pstate: State<'_, ProcessedState>,
) -> Result<ScanReport, String> {
    let settings = sstate.0.lock().unwrap().clone();
    let proc = pstate.0.clone();
    let app2 = app.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let mut set = proc.lock().unwrap();
        let report = email::run_scan(&app2, &settings, &mut set)?;
        store::persist(&app2, &set);
        Ok::<ScanReport, String>(report)
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
pub async fn import_msg(
    app: AppHandle,
    sstate: State<'_, SettingsState>,
    pstate: State<'_, ProcessedState>,
    paths: Vec<String>,
) -> Result<usize, String> {
    let settings = sstate.0.lock().unwrap().clone();
    let proc = pstate.0.clone();
    let app2 = app.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let mut set = proc.lock().unwrap();
        let saved = email::import_msg(&app2, &settings, &mut set, &paths)?;
        store::persist(&app2, &set);
        Ok::<usize, String>(saved)
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
pub async fn import_pst(
    app: AppHandle,
    sstate: State<'_, SettingsState>,
    path: String,
) -> Result<String, String> {
    let settings = sstate.0.lock().unwrap().clone();
    let app2 = app.clone();
    tauri::async_runtime::spawn_blocking(move || email::import_pst(&app2, &settings, &path))
        .await
        .map_err(|e| e.to_string())?
}

// ── 已处理记录 ──────────────────────────────────────────────

#[tauri::command]
pub fn processed_count(pstate: State<'_, ProcessedState>) -> usize {
    pstate.0.lock().unwrap().len()
}

#[tauri::command]
pub fn clear_processed(app: AppHandle, pstate: State<'_, ProcessedState>) -> Result<(), String> {
    let mut set = pstate.0.lock().unwrap();
    *set = HashSet::new();
    store::persist(&app, &set);
    Ok(())
}

// ── WeLink 监听 ─────────────────────────────────────────────

#[tauri::command]
pub fn welink_start(app: AppHandle, mstate: State<'_, MonitorState>) {
    welink::start(&app, &mstate);
}

#[tauri::command]
pub fn welink_stop(mstate: State<'_, MonitorState>) {
    welink::stop(&mstate);
}

#[tauri::command]
pub fn welink_running(mstate: State<'_, MonitorState>) -> bool {
    welink::is_running(&mstate)
}

// ── 本地产物 ────────────────────────────────────────────────

#[tauri::command]
pub fn list_outputs(sstate: State<'_, SettingsState>) -> Result<Vec<OutputEntry>, String> {
    let settings = sstate.0.lock().unwrap().clone();
    output::list(&settings)
}

#[tauri::command]
pub fn read_text_file(path: String) -> Result<String, String> {
    std::fs::read_to_string(&path).map_err(|e| format!("读取文件失败: {e}"))
}
