//! WeLink 云盘图片本地化 → 转外链（DESIGN.md §6）。
//! 解析 um_content 拿到下载链接，下载字节，再上传到用户配置的图片接口换公网 URL。

use std::time::Duration;

use crate::images::upload_bytes;
use crate::settings::Settings;

use super::WlMessage;

/// 解析 /:um_begin{URL|Type|Size|FileName|0|W;H;extraction_code|...}/:um_end
/// 返回 (download_url, file_name, extraction_code)。
pub fn parse_um_content(content: &str) -> Option<(String, String, String)> {
    let prefix = "/:um_begin{";
    let suffix = "}/:um_end";
    if !(content.starts_with(prefix) && content.ends_with(suffix)) {
        return None;
    }
    let inner = &content[prefix.len()..content.len() - suffix.len()];
    let parts: Vec<&str> = inner.split('|').collect();
    if parts.len() < 6 {
        return None;
    }
    let download_url = parts[0].to_string();
    let file_name = parts[3].to_string();
    let field5: Vec<&str> = parts[5].split(';').collect();
    let extraction_code = field5.get(2).map(|s| s.to_string()).unwrap_or_default();
    Some((download_url, file_name, extraction_code))
}

fn download(url: &str, extraction_code: &str) -> Option<Vec<u8>> {
    let client = reqwest::blocking::Client::builder()
        .danger_accept_invalid_certs(true)
        .timeout(Duration::from_secs(60))
        .build()
        .ok()?;
    let resp = client
        .get(url)
        .query(&[("extractionCode", extraction_code)])
        .send()
        .ok()?;
    if !resp.status().is_success() {
        return None;
    }
    let bytes = resp.bytes().ok()?;
    if bytes.is_empty() {
        return None;
    }
    Some(bytes.to_vec())
}

/// 就地处理一组消息的图片：
/// - 配了上传接口：下载云盘图 → 上传换 URL，写入 m.img_url；
/// - 没配：仅写 img_name，img_url 留空（渲染为占位）。
pub fn localize_messages(settings: &Settings, msgs: &mut [WlMessage]) {
    let upload_url = settings.image_upload_url.trim();
    for m in msgs.iter_mut() {
        if m.content_type != "PICTURE_MSG" && m.content_type != "FILE_MSG" {
            continue;
        }
        if let Some((dl_url, fname, code)) = parse_um_content(&m.content) {
            m.img_name = Some(fname.clone());
            if upload_url.is_empty() {
                continue;
            }
            if let Some(bytes) = download(&dl_url, &code) {
                if let Some(url) = upload_bytes(upload_url, &fname, bytes) {
                    m.img_url = Some(url);
                }
            }
        }
    }
}
