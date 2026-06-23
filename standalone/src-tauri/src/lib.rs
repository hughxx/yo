mod commands;
mod email;
mod events;
mod htmlmd;
mod images;
mod imported;
mod output;
mod settings;
mod sidecar;
mod store;
mod sync;
mod welink;

use std::sync::{Arc, Mutex};

use tauri::Manager;

use email::EmailMonitorState;
use imported::ImportedState;
use settings::SettingsState;
use store::ExportState;
use sync::SyncState;
use welink::collect::CollectMonitorState;
use welink::MonitorState;

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_log::Builder::new().build())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_os::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_clipboard_manager::init())
        .setup(|app| {
            let loaded = settings::load(app.handle());
            let sync_on = loaded.sync_enabled;
            app.manage(SettingsState(Mutex::new(loaded)));

            let exports = store::load(app.handle());
            app.manage(ExportState(Arc::new(Mutex::new(exports))));

            let imported_list = imported::load(app.handle());
            app.manage(ImportedState(Arc::new(Mutex::new(imported_list))));

            app.manage(MonitorState::default());
            app.manage(CollectMonitorState::default());
            app.manage(EmailMonitorState::default());

            let sync_state = SyncState::default();
            sync::load_status(app.handle(), &sync_state);
            app.manage(sync_state);
            // 上次开着同步钩子 → 重启后自动恢复定时
            if sync_on {
                sync::start(app.handle(), &app.state::<SyncState>());
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::app_version,
            commands::ping,
            commands::get_settings,
            commands::save_settings,
            commands::list_folders,
            commands::browse_folder,
            commands::email_list_scope,
            commands::list_imported_msgs,
            commands::email_scan,
            commands::process_selected,
            commands::reexport_msgs,
            commands::import_msg,
            commands::import_pst,
            commands::email_monitor_start,
            commands::email_monitor_stop,
            commands::email_monitor_running,
            commands::welink_start,
            commands::welink_stop,
            commands::welink_running,
            commands::collect_start,
            commands::collect_stop,
            commands::collect_running,
            commands::import_chatlog,
            commands::sync_status,
            commands::sync_start,
            commands::sync_stop,
            commands::sync_now,
            commands::list_outputs,
            commands::read_text_file,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
