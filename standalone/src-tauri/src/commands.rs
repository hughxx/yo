//! 暴露给前端的 Tauri 命令。

use tauri::{AppHandle, Manager, State};

use crate::email::{self, EmailMonitorState, EmailSummary, ScanReport};
use crate::imported::{self, ImportedState};
use crate::output::{self, OutputEntry};
use crate::settings::{self, Settings, SettingsState};
use crate::sidecar;
use crate::store::{self, ExportState};
use crate::sync::{self, SyncState, SyncStatus};
use crate::welink::collect::{self, CollectMonitorState};
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

// ── 邮件浏览 ────────────────────────────────────────────────

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

/// 浏览某个 Outlook 文件夹（folder 为空 = 默认收件箱）。
#[tauri::command]
pub async fn browse_folder(
    app: AppHandle,
    sstate: State<'_, SettingsState>,
    estate: State<'_, ExportState>,
    folder: String,
) -> Result<Vec<EmailSummary>, String> {
    let settings = sstate.0.lock().unwrap().clone();
    let exports = estate.0.lock().unwrap().clone();
    let app2 = app.clone();
    tauri::async_runtime::spawn_blocking(move || {
        email::browse(&app2, &settings, &folder, &exports, 300)
    })
    .await
    .map_err(|e| e.to_string())?
}

/// 列出「处理范围」内的邮件（勾选的文件夹 + 导入的 msg）。
#[tauri::command]
pub async fn email_list_scope(
    app: AppHandle,
    sstate: State<'_, SettingsState>,
    estate: State<'_, ExportState>,
    istate: State<'_, ImportedState>,
) -> Result<Vec<EmailSummary>, String> {
    let settings = sstate.0.lock().unwrap().clone();
    let exports = estate.0.lock().unwrap().clone();
    let imported = istate.0.lock().unwrap().clone();
    let app2 = app.clone();
    tauri::async_runtime::spawn_blocking(move || {
        email::list_scope(&app2, &settings, &exports, &imported)
    })
    .await
    .map_err(|e| e.to_string())?
}

/// 列出导入的 msg（特殊 PST 视角）。
#[tauri::command]
pub fn list_imported_msgs(
    sstate: State<'_, SettingsState>,
    estate: State<'_, ExportState>,
    istate: State<'_, ImportedState>,
) -> Vec<EmailSummary> {
    let settings = sstate.0.lock().unwrap().clone();
    let exports = estate.0.lock().unwrap();
    let list = istate.0.lock().unwrap();
    email::list_imported(&settings, &list, &exports)
}

// ── 处理 / 导出 ─────────────────────────────────────────────

#[tauri::command]
pub async fn email_scan(
    app: AppHandle,
    sstate: State<'_, SettingsState>,
    estate: State<'_, ExportState>,
    istate: State<'_, ImportedState>,
) -> Result<ScanReport, String> {
    let settings = sstate.0.lock().unwrap().clone();
    let exp = estate.0.clone();
    let imp = istate.0.clone();
    let app2 = app.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let mut exports = exp.lock().unwrap();
        let imported_list = imp.lock().unwrap().clone();
        let report = email::run_scan(&app2, &settings, &mut exports, &imported_list)?;
        store::persist(&app2, &exports);
        Ok::<ScanReport, String>(report)
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
pub async fn process_selected(
    app: AppHandle,
    sstate: State<'_, SettingsState>,
    estate: State<'_, ExportState>,
    item_ids: Vec<String>,
) -> Result<usize, String> {
    let settings = sstate.0.lock().unwrap().clone();
    let exp = estate.0.clone();
    let app2 = app.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let mut exports = exp.lock().unwrap();
        let saved = email::process_selected(&app2, &settings, &mut exports, &item_ids)?;
        store::persist(&app2, &exports);
        Ok::<usize, String>(saved)
    })
    .await
    .map_err(|e| e.to_string())?
}

/// 重新导出选中的 msg（按源路径）。
#[tauri::command]
pub async fn reexport_msgs(
    app: AppHandle,
    sstate: State<'_, SettingsState>,
    estate: State<'_, ExportState>,
    paths: Vec<String>,
) -> Result<usize, String> {
    let settings = sstate.0.lock().unwrap().clone();
    let exp = estate.0.clone();
    let app2 = app.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let mut exports = exp.lock().unwrap();
        let saved = email::reexport_msgs(&app2, &settings, &mut exports, &paths)?;
        store::persist(&app2, &exports);
        Ok::<usize, String>(saved)
    })
    .await
    .map_err(|e| e.to_string())?
}

// ── 导入 ────────────────────────────────────────────────────

#[tauri::command]
pub async fn import_msg(
    app: AppHandle,
    sstate: State<'_, SettingsState>,
    estate: State<'_, ExportState>,
    istate: State<'_, ImportedState>,
    paths: Vec<String>,
) -> Result<usize, String> {
    let settings = sstate.0.lock().unwrap().clone();
    let exp = estate.0.clone();
    let imp = istate.0.clone();
    let app2 = app.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let mut exports = exp.lock().unwrap();
        let mut list = imp.lock().unwrap();
        let saved = email::import_msg(&app2, &settings, &mut exports, &mut list, &paths)?;
        store::persist(&app2, &exports);
        imported::persist(&app2, &list);
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

// ── 邮件监听 ────────────────────────────────────────────────

#[tauri::command]
pub fn email_monitor_start(app: AppHandle, estate: State<'_, EmailMonitorState>) {
    email::monitor_start(&app, &estate);
}

#[tauri::command]
pub fn email_monitor_stop(estate: State<'_, EmailMonitorState>) {
    email::monitor_stop(&estate);
}

#[tauri::command]
pub fn email_monitor_running(estate: State<'_, EmailMonitorState>) -> bool {
    email::monitor_running(&estate)
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

// ── 自动收集（独立后台） ────────────────────────────────────

#[tauri::command]
pub fn collect_start(app: AppHandle, cstate: State<'_, CollectMonitorState>) {
    collect::start(&app, &cstate);
}

#[tauri::command]
pub fn collect_stop(cstate: State<'_, CollectMonitorState>) {
    collect::stop(&cstate);
}

#[tauri::command]
pub fn collect_running(cstate: State<'_, CollectMonitorState>) -> bool {
    collect::is_running(&cstate)
}

/// 手动导入 WeLink 导出聊天记录 zip。
#[tauri::command]
pub async fn import_chatlog(
    app: AppHandle,
    sstate: State<'_, SettingsState>,
    zip_path: String,
    group_name: String,
) -> Result<String, String> {
    let settings = sstate.0.lock().unwrap().clone();
    let app2 = app.clone();
    tauri::async_runtime::spawn_blocking(move || {
        welink::import_chatlog(&app2, &settings, &zip_path, &group_name)
    })
    .await
    .map_err(|e| e.to_string())?
}

// ── 同步钩子 ────────────────────────────────────────────────

#[tauri::command]
pub fn sync_status(state: State<'_, SyncState>) -> SyncStatus {
    sync::status(&state)
}

#[tauri::command]
pub fn sync_start(app: AppHandle, state: State<'_, SyncState>) {
    sync::start(&app, &state);
}

#[tauri::command]
pub fn sync_stop(state: State<'_, SyncState>) {
    sync::stop(&state);
}

/// 手动「立即同步」：在后台线程执行一次用户命令。
#[tauri::command]
pub async fn sync_now(
    app: AppHandle,
    sstate: State<'_, SettingsState>,
) -> Result<(), String> {
    let settings = sstate.0.lock().unwrap().clone();
    let app2 = app.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let st = app2.state::<SyncState>();
        sync::run_once(&app2, &settings, &st)
    })
    .await
    .map_err(|e| e.to_string())?
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
