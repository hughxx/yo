//! 产物登记表：item_id → 产物 .html 绝对路径。
//! 「已导出」= 登记表里有该 id 且对应文件仍存在；删掉本地文件即视为未导出（可重导）。
//! 替代旧的 processed.json + 「清空记录」。

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

use tauri::{AppHandle, Manager};

pub struct ExportState(pub Arc<Mutex<HashMap<String, String>>>);

fn path(app: &AppHandle) -> Option<PathBuf> {
    let dir = app.path().app_config_dir().ok()?;
    std::fs::create_dir_all(&dir).ok();
    Some(dir.join("exports.json"))
}

pub fn load(app: &AppHandle) -> HashMap<String, String> {
    path(app)
        .and_then(|p| std::fs::read_to_string(p).ok())
        .and_then(|t| serde_json::from_str(&t).ok())
        .unwrap_or_default()
}

pub fn persist(app: &AppHandle, map: &HashMap<String, String>) {
    if let Some(p) = path(app) {
        if let Ok(t) = serde_json::to_string(map) {
            let _ = std::fs::write(p, t);
        }
    }
}

/// 该 id 是否已导出（登记在册且产物文件仍存在）。
pub fn is_exported(map: &HashMap<String, String>, id: &str) -> bool {
    map.get(id)
        .map(|p| !p.is_empty() && Path::new(p).exists())
        .unwrap_or(false)
}
