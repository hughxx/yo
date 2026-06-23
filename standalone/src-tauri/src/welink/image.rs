//! WeLink 云盘图片本地化 → 转外链（DESIGN.md §6）。
//! 解析 um_content 拿到下载链接，下载字节，再上传到用户配置的图片接口换公网 URL。

use std::time::Duration;

use serde_json::{json, Value};

use crate::images::upload_bytes;
use crate::settings::Settings;

use super::WlMessage;

fn client() -> Option<reqwest::blocking::Client> {
    reqwest::blocking::Client::builder()
        .danger_accept_invalid_certs(true)
        .timeout(Duration::from_secs(120))
        .build()
        .ok()
}

/// 用配置的云盘账号登录换 token（任意账号均可）。
fn clouddrive_token(settings: &Settings) -> Option<String> {
    let base = settings.clouddrive_url.trim().trim_end_matches('/');
    if base.is_empty() || settings.clouddrive_account.trim().is_empty() {
        return None;
    }
    let url = format!("{base}/api/v2/token");
    let body = json!({
        "appId": "espace",
        "domain": "huawei",
        "loginName": settings.clouddrive_account,
        "password": settings.clouddrive_password,
    });
    let resp = client()?
        .post(url)
        .header("Content-Type", "application/json")
        .header("x-device-sn", "device0123456789")
        .header("x-device-type", "web")
        .header("x-device-os", "win10")
        .header("x-device-name", "machinec00100000")
        .header("x-client-version", "10")
        .json(&body)
        .send()
        .ok()?;
    if !resp.status().is_success() {
        return None;
    }
    let v: Value = resp.json().ok()?;
    v.get("token").and_then(|x| x.as_str()).map(String::from)
}

/// 用 token + 整条 um_begin 串（imAuthorization）从云盘下载文件字节。
fn download_um(settings: &Settings, token: &str, um: &str) -> Option<Vec<u8>> {
    let base = settings.clouddrive_url.trim().trim_end_matches('/');
    let url = format!("{base}/imchat/api/v3/links/imdownload");
    let resp = client()?
        .post(url)
        .header("Authorization", token)
        .header("Content-Type", "application/json")
        .json(&json!({ "imAuthorization": um }))
        .send()
        .ok()?;
    if !resp.status().is_success() {
        return None;
    }
    let bytes = resp.bytes().ok()?;
    if bytes.is_empty() {
        None
    } else {
        Some(bytes.to_vec())
    }
}

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

/// 就地处理一组消息的图片：
/// - 配了上传接口 + 云盘账号：登录换 token → 下载云盘图 → 上传换 URL，写入 m.img_url；
/// - 没配上传接口：仅写 img_name，img_url 留空（渲染为占位）。
pub fn localize_messages(settings: &Settings, msgs: &mut [WlMessage]) {
    let upload_url = settings.image_upload_url.trim();
    // token 懒加载、整批复用
    let mut token: Option<String> = None;
    let mut token_tried = false;

    for m in msgs.iter_mut() {
        if m.content_type != "PICTURE_MSG" && m.content_type != "FILE_MSG" {
            continue;
        }
        if let Some((_dl_url, fname, _code)) = parse_um_content(&m.content) {
            m.img_name = Some(fname.clone());
            if upload_url.is_empty() {
                continue;
            }
            if !token_tried {
                token = clouddrive_token(settings);
                token_tried = true;
            }
            let Some(tok) = token.as_deref() else { continue };
            // 用整条 um_begin 串作为 imAuthorization 下载
            if let Some(bytes) = download_um(settings, tok, &m.content) {
                if let Some(url) = upload_bytes(upload_url, &fname, bytes) {
                    m.img_url = Some(url);
                }
            }
        }
    }
}
