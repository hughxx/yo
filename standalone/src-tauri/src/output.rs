//! 落盘：扁平 + 时间戳前缀（DESIGN.md §7）。
//! <输出目录>/YYYYMMDD_HHMM_<安全标题>.html / .md

use std::path::{Path, PathBuf};

use chrono::NaiveDateTime;
use serde::Serialize;

use crate::settings::Settings;

#[derive(Debug, Serialize)]
pub struct OutputEntry {
    pub base_name: String,
    pub html_path: String,
    pub md_path: String,
}

/// 列出输出目录下的产物（按文件名倒序，即时间倒序）。
pub fn list(settings: &Settings) -> Result<Vec<OutputEntry>, String> {
    let dir = settings.output_dir.trim();
    if dir.is_empty() {
        return Ok(vec![]);
    }
    let dir = PathBuf::from(dir);
    if !dir.exists() {
        return Ok(vec![]);
    }
    let mut entries = Vec::new();
    let rd = std::fs::read_dir(&dir).map_err(|e| format!("读取输出目录失败: {e}"))?;
    for ent in rd.flatten() {
        let path = ent.path();
        if path.extension().and_then(|e| e.to_str()) != Some("html") {
            continue;
        }
        let stem = match path.file_stem().and_then(|s| s.to_str()) {
            Some(s) => s.to_string(),
            None => continue,
        };
        let md = dir.join(format!("{stem}.md"));
        entries.push(OutputEntry {
            base_name: stem,
            html_path: path.to_string_lossy().into_owned(),
            md_path: if md.exists() {
                md.to_string_lossy().into_owned()
            } else {
                String::new()
            },
        });
    }
    entries.sort_by(|a, b| b.base_name.cmp(&a.base_name));
    Ok(entries)
}

pub struct Saved {
    #[allow(dead_code)]
    pub html_path: String,
    #[allow(dead_code)]
    pub md_path: String,
    pub base_name: String,
}

/// received_time 形如 "2026-06-15T15:30:00"，转 "20260615_1530"；解析失败回退给定占位。
pub fn prefix_from_time(received_time: &str) -> String {
    for fmt in ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"] {
        if let Ok(dt) = NaiveDateTime::parse_from_str(received_time, fmt) {
            return dt.format("%Y%m%d_%H%M").to_string();
        }
    }
    "00000000_0000".to_string()
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
    received_time: &str,
    title: &str,
    html: &str,
    md: &str,
) -> Result<Option<Saved>, String> {
    let out_dir = settings.output_dir.trim();
    if out_dir.is_empty() {
        return Err("未设置输出目录".to_string());
    }
    let dir = PathBuf::from(out_dir);
    std::fs::create_dir_all(&dir).map_err(|e| format!("创建输出目录失败: {e}"))?;

    let prefix = prefix_from_time(received_time);
    let safe = sanitize_title(title, settings.title_max_len as usize);
    let base = format!("{prefix}_{safe}");

    let (html_path, md_path, base_name) =
        resolve_paths(&dir, &base, &settings.conflict_strategy)?;
    let (html_path, md_path, base_name) = match (html_path, md_path, base_name) {
        (Some(h), Some(m), b) => (h, m, b),
        _ => return Ok(None), // skip
    };

    std::fs::write(&html_path, html).map_err(|e| format!("写 HTML 失败: {e}"))?;
    std::fs::write(&md_path, md).map_err(|e| format!("写 Markdown 失败: {e}"))?;

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
