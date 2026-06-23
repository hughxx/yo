//! HTML → Markdown：转发给外置 html2md.exe（Python html2text，DESIGN.md §5.3）。

use tauri::AppHandle;

use crate::events::emit_log;
use crate::settings::Settings;
use crate::sidecar;

pub fn html_to_md(app: &AppHandle, settings: &Settings, html: &str) -> String {
    if html.trim().is_empty() {
        return String::new();
    }
    match sidecar::run_html2md(app, settings, html) {
        Ok(md) => md,
        Err(e) => {
            emit_log(app, format!("HTML→MD 失败: {e}"));
            String::new()
        }
    }
}
