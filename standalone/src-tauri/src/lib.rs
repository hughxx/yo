mod commands;
mod email;
mod events;
mod htmlmd;
mod images;
mod output;
mod settings;
mod sidecar;
mod store;
mod welink;

use std::sync::{Arc, Mutex};

use tauri::Manager;

use settings::SettingsState;
use store::ProcessedState;
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
            app.manage(SettingsState(Mutex::new(loaded)));

            let processed = store::load(app.handle());
            app.manage(ProcessedState(Arc::new(Mutex::new(processed))));

            app.manage(MonitorState::default());
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::app_version,
            commands::ping,
            commands::get_settings,
            commands::save_settings,
            commands::list_folders,
            commands::email_list,
            commands::email_scan,
            commands::import_msg,
            commands::import_pst,
            commands::processed_count,
            commands::clear_processed,
            commands::welink_start,
            commands::welink_stop,
            commands::welink_running,
            commands::list_outputs,
            commands::read_text_file,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
