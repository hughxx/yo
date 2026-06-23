//! 落盘：扁平、文件名 = 安全标题；日期不进文件名，而是写入文件「修改时间(mtime)」。
//! <输出目录>/<来源>/<安全标题>.html / .md，mtime = 邮件收件时间 / 聊天起始时间。

use std::path::{Path, PathBuf};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use chrono::{Local, NaiveDateTime, TimeZone};
use serde::Serialize;

use crate::settings::Settings;

/// 产物来源分目录：邮件 / 聊天记录。
pub const SRC_EMAIL: &str = "邮件";
pub const SRC_WELINK: &str = "聊天记录";

#[derive(Debug, Serialize)]
pub struct OutputEntry {
    pub source: String,
    pub base_name: String,
    pub html_path: String,
    pub md_path: String,
    /// 文件修改时间，格式 "YYYY-MM-DD HH:MM"（取自 mtime，即原始日期）。
    pub modified: String,
}

/// 列出输出目录下各来源的产物（按文件修改时间倒序，即原始日期倒序）。
pub fn list(settings: &Settings) -> Result<Vec<OutputEntry>, String> {
    let dir = settings.output_dir.trim();
    if dir.is_empty() {
        return Ok(vec![]);
    }
    let root = PathBuf::from(dir);
    let mut rows: Vec<(SystemTime, OutputEntry)> = Vec::new();
    for src in [SRC_EMAIL, SRC_WELINK] {
        let sub = root.join(src);
        if !sub.exists() {
            continue;
        }
        let Ok(rd) = std::fs::read_dir(&sub) else { continue };
        for ent in rd.flatten() {
            let path = ent.path();
            if path.extension().and_then(|e| e.to_str()) != Some("html") {
                continue;
            }
            let Some(stem) = path.file_stem().and_then(|s| s.to_str()).map(String::from) else {
                continue;
            };
            let mtime = ent.metadata().and_then(|m| m.modified()).unwrap_or(UNIX_EPOCH);
            let md = sub.join(format!("{stem}.md"));
            rows.push((
                mtime,
                OutputEntry {
                    source: src.to_string(),
                    base_name: stem,
                    html_path: path.to_string_lossy().into_owned(),
                    md_path: if md.exists() { md.to_string_lossy().into_owned() } else { String::new() },
                    modified: fmt_mtime(mtime),
                },
            ));
        }
    }
    rows.sort_by(|a, b| b.0.cmp(&a.0));
    Ok(rows.into_iter().map(|(_, e)| e).collect())
}

/// SystemTime → 本地时间 "YYYY-MM-DD HH:MM"。
fn fmt_mtime(t: SystemTime) -> String {
    let dt: chrono::DateTime<Local> = t.into();
    dt.format("%Y-%m-%d %H:%M").to_string()
}

pub struct Saved {
    #[allow(dead_code)]
    pub html_path: String,
    #[allow(dead_code)]
    pub md_path: String,
    pub base_name: String,
}

/// received_time 形如 "2026-06-15T15:30:00"（本地时间）→ SystemTime，用于设置文件 mtime。
/// 解析失败返回 None（保持文件系统默认的写入时间）。
fn mtime_from_time(received_time: &str) -> Option<SystemTime> {
    for fmt in ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"] {
        if let Ok(ndt) = NaiveDateTime::parse_from_str(received_time, fmt) {
            let secs = Local.from_local_datetime(&ndt).single()?.timestamp();
            if secs < 0 {
                return None;
            }
            return Some(UNIX_EPOCH + Duration::from_secs(secs as u64));
        }
    }
    None
}

/// 把文件的修改时间设为给定时刻（Windows/Linux 通用）。
fn set_mtime(path: &Path, t: SystemTime) {
    if let Ok(f) = std::fs::OpenOptions::new().write(true).open(path) {
        let _ = f.set_modified(t);
    }
}

/// 清洗标题：去非法字符与换行、压缩空白、截断。
pub fn sanitize_title(title: &str, max_len: usize) -> String {
    let mut t: String = title
        .chars()
        .map(|c| match c {
            '\\' | '/' | ':' | '*' | '?' | '"' | '<' | '>' | '|' => '_',
            '\r' | '\n' | '\t' => ' ',
            _ => c,
        })
        .collect();
    // 压缩连续空白
    t = t.split_whitespace().collect::<Vec<_>>().join(" ");
    let t = t.trim_matches([' ', '.']).to_string();
    let t = if t.is_empty() { "untitled".to_string() } else { t };

    // 按字符截断（避免切断多字节）
    let truncated: String = t.chars().take(max_len.max(1)).collect();
    truncated
}

/// 落盘 html + md。conflict_strategy: suffix|overwrite|skip。
/// 返回 None 表示按 skip 策略跳过。
pub fn save(
    settings: &Settings,
    source: &str,
    received_time: &str,
    title: &str,
    html: &str,
    md: &str,
) -> Result<Option<Saved>, String> {
    let out_dir = settings.output_dir.trim();
    if out_dir.is_empty() {
        return Err("未设置输出目录".to_string());
    }
    let dir = PathBuf::from(out_dir).join(source);
    std::fs::create_dir_all(&dir).map_err(|e| format!("创建输出目录失败: {e}"))?;

    let base = sanitize_title(title, settings.title_max_len as usize);

    let (html_path, md_path, base_name) =
        resolve_paths(&dir, &base, &settings.conflict_strategy)?;
    let (html_path, md_path, base_name) = match (html_path, md_path, base_name) {
        (Some(h), Some(m), b) => (h, m, b),
        _ => return Ok(None), // skip
    };

    std::fs::write(&html_path, html).map_err(|e| format!("写 HTML 失败: {e}"))?;
    std::fs::write(&md_path, md).map_err(|e| format!("写 Markdown 失败: {e}"))?;

    // 日期写入文件 mtime（而非文件名），Windows/Linux 资源管理器均可按日期排序。
    if let Some(mt) = mtime_from_time(received_time) {
        set_mtime(&html_path, mt);
        set_mtime(&md_path, mt);
    }

    Ok(Some(Saved {
        html_path: html_path.to_string_lossy().into_owned(),
        md_path: md_path.to_string_lossy().into_owned(),
        base_name,
    }))
}

fn resolve_paths(
    dir: &Path,
    base: &str,
    strategy: &str,
) -> Result<(Option<PathBuf>, Option<PathBuf>, String), String> {
    let html = dir.join(format!("{base}.html"));
    let md = dir.join(format!("{base}.md"));

    let exists = html.exists() || md.exists();
    if !exists {
        return Ok((Some(html), Some(md), base.to_string()));
    }

    match strategy {
        "overwrite" => Ok((Some(html), Some(md), base.to_string())),
        "skip" => Ok((None, None, base.to_string())),
        _ => {
            // suffix：找一个不冲突的 _NN
            for n in 1..1000 {
                let b = format!("{base}_{n:02}");
                let h = dir.join(format!("{b}.html"));
                let m = dir.join(format!("{b}.md"));
                if !h.exists() && !m.exists() {
                    return Ok((Some(h), Some(m), b));
                }
            }
            Err("同名文件过多，无法生成唯一文件名".to_string())
        }
    }
}
