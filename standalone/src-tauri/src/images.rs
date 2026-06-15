//! 图片处理：转外链（DESIGN.md §6）。
//! 配了 image_upload_url → 上传换公网 URL 写回 HTML；没配 → 从 HTML 剔除图片。

use std::time::Duration;

use regex::Regex;
use serde::Deserialize;

use crate::settings::Settings;

#[derive(Debug, Clone, Deserialize)]
pub struct InlineImage {
    pub cid: String,
    pub path: String,
}

/// 上传单个文件到图片接口，返回公网 URL（失败返回 None）。
pub fn upload_file(upload_url: &str, file_path: &str) -> Option<String> {
    let bytes = std::fs::read(file_path).ok()?;
    let filename = std::path::Path::new(file_path)
        .file_name()
        .map(|n| n.to_string_lossy().into_owned())
        .unwrap_or_else(|| "image.png".to_string());
    upload_bytes(upload_url, &filename, bytes)
}

/// 上传字节流到图片接口，返回公网 URL（失败返回 None）。
pub fn upload_bytes(upload_url: &str, filename: &str, bytes: Vec<u8>) -> Option<String> {
    let client = reqwest::blocking::Client::builder()
        .danger_accept_invalid_certs(true)
        .timeout(Duration::from_secs(60))
        .build()
        .ok()?;

    let part = reqwest::blocking::multipart::Part::bytes(bytes).file_name(filename.to_string());
    let form = reqwest::blocking::multipart::Form::new()
        .part("file", part)
        .text("filename", filename.to_string());

    let resp = client.post(upload_url).multipart(form).send().ok()?;
    if !resp.status().is_success() {
        return None;
    }
    let v: serde_json::Value = resp.json().ok()?;
    // 兼容 {url} / {Url}
    extract_url(&v)
}

fn extract_url(v: &serde_json::Value) -> Option<String> {
    for key in ["url", "Url", "URL"] {
        if let Some(u) = v.get(key).and_then(|x| x.as_str()) {
            if !u.is_empty() {
                return Some(u.to_string());
            }
        }
    }
    None
}

/// 处理邮件 HTML 的内联图：
/// - 配了上传接口：每张 cid 图上传换 URL，替换 `cid:CID` → URL；未上传成功的 cid 引用置空。
/// - 没配接口：所有 cid 引用置空（产物不含图片）。
/// 处理完清理临时文件。
pub fn process_email_html(settings: &Settings, html: &str, inline: &[InlineImage]) -> String {
    let upload_url = settings.image_upload_url.trim();
    let mut out = html.to_string();

    if !upload_url.is_empty() {
        for img in inline {
            if let Some(url) = upload_file(upload_url, &img.path) {
                out = out.replace(&format!("cid:{}", img.cid), &url);
            }
        }
    }

    // 清理临时文件（无论成功与否）
    for img in inline {
        let _ = std::fs::remove_file(&img.path);
    }

    // 去除剩余 cid: 引用，避免裂图
    let cid_ref = Regex::new(r#"(?i)src\s*=\s*["']cid:[^"']*["']"#).unwrap();
    out = cid_ref.replace_all(&out, r#"src="""#).into_owned();
    out
}
