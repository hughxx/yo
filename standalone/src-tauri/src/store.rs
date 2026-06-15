//! 已处理条目去重记录（替代旧 .email_assistant_processed.json）。
//! 持久化到 app config dir / processed.json。

use std::collections::HashSet;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use tauri::{AppHandle, Manager};

pub struct ProcessedState(pub Arc<Mutex<HashSet<String>>>);

fn path(app: &AppHandle) -> Option<PathBuf> {
    let dir = app.path().app_config_dir().ok()?;
    std::fs::create_dir_all(&dir).ok();
    Some(dir.join("processed.json"))
}

pub fn load(app: &AppHandle) -> HashSet<String> {
    let Some(p) = path(app) else {
        return HashSet::new();
    };
    match std::fs::read_to_string(p) {
        Ok(text) => serde_json::from_str(&text).unwrap_or_default(),
        Err(_) => HashSet::new(),
    }
}

pub fn persist(app: &AppHandle, set: &HashSet<String>) {
    if let Some(p) = path(app) {
        if let Ok(text) = serde_json::to_string(set) {
            let _ = std::fs::write(p, text);
        }
    }
}
