//! 导入的 .msg 登记表（用户视角的「特殊 PST」）。
//! 持久化到 app config dir / imported_msgs.json；按源文件路径去重。

use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Manager};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ImportedMsg {
    pub item_id: String,
    pub path: String,
    #[serde(default)]
    pub subject: String,
    #[serde(default)]
    pub sender_name: String,
    #[serde(default)]
    pub sender_email: String,
    #[serde(default)]
    pub received_time: String,
    #[serde(default)]
    pub conversation_topic: String,
}

pub struct ImportedState(pub Arc<Mutex<Vec<ImportedMsg>>>);

fn file(app: &AppHandle) -> Option<PathBuf> {
    let dir = app.path().app_config_dir().ok()?;
    std::fs::create_dir_all(&dir).ok();
    Some(dir.join("imported_msgs.json"))
}

pub fn load(app: &AppHandle) -> Vec<ImportedMsg> {
    file(app)
        .and_then(|p| std::fs::read_to_string(p).ok())
        .and_then(|t| serde_json::from_str(&t).ok())
        .unwrap_or_default()
}

pub fn persist(app: &AppHandle, list: &[ImportedMsg]) {
    if let Some(p) = file(app) {
        if let Ok(t) = serde_json::to_string_pretty(list) {
            let _ = std::fs::write(p, t);
        }
    }
}

/// 按 path 去重 upsert（同路径覆盖元数据）。
pub fn upsert(list: &mut Vec<ImportedMsg>, msg: ImportedMsg) {
    if let Some(slot) = list.iter_mut().find(|m| m.path == msg.path) {
        *slot = msg;
    } else {
        list.push(msg);
    }
}
