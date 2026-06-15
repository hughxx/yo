//! WeLink 消息 → HTML（与旧 monitor.py `_msgs_to_html` 保持一致的标记，
//! 以便 `filter_daily_html` 能按相同的 div 结构切分）。

use chrono::{Local, TimeZone};

use super::WlMessage;

/// 与 monitor.py 完全一致的消息块起始标记（daily 过滤按它切分）。
pub const MSG_OPEN: &str =
    r#"<div style="margin:6px 0;padding:6px 10px;background:#f5f5f5;border-radius:4px;">"#;

fn esc(s: &str) -> String {
    s.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
}

fn fmt_ts(ms: i64) -> String {
    if ms <= 0 {
        return String::new();
    }
    match Local.timestamp_millis_opt(ms).single() {
        Some(dt) => dt.format("%Y-%m-%d %H:%M:%S").to_string(),
        None => String::new(),
    }
}

fn msg_body(m: &WlMessage) -> String {
    let ct = m.content_type.as_str();
    match ct {
        "PICTURE_MSG" | "FILE_MSG" => {
            let name = esc(m.img_name.as_deref().unwrap_or(""));
            match (&m.img_url, ct) {
                (Some(url), "PICTURE_MSG") => format!(
                    r#"<img src="{url}" style="max-width:480px;display:block"><small style="color:#888">{name}</small>"#
                ),
                (Some(url), _) => format!(r#"<a href="{url}">[文件] {name}</a>"#),
                (None, "PICTURE_MSG") => format!("<em>[图片] {name}</em>"),
                (None, _) => format!("<em>[文件] {name}</em>"),
            }
        }
        "CARD_MSG" => "<em>[卡片消息]</em>".to_string(),
        "NOTICE_MSG" => format!("<em>[系统通知] {}</em>", esc(&m.content)),
        _ => {
            let raw = &m.content;
            if raw.trim_start().starts_with('<') {
                raw.clone()
            } else {
                esc(raw).replace('\n', "<br>")
            }
        }
    }
}

pub fn msgs_to_html(msgs: &[WlMessage]) -> String {
    let mut rows = String::new();
    for m in msgs {
        let sender = esc(&m.sender);
        let t = fmt_ts(m.server_send_time);
        rows.push_str(&format!(
            r#"{MSG_OPEN}<span style="font-weight:bold;color:#1a73e8">{sender}</span><span style="font-size:11px;color:#aaa;margin-left:8px">{t}</span><div style="margin-top:4px">{body}</div></div>"#,
            body = msg_body(m),
        ));
    }
    format!(
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\">\
<style>body{{font-family:Arial,sans-serif;font-size:13px;color:#222;\
max-width:860px;margin:20px auto;padding:0 16px}}</style></head><body>{rows}</body></html>"
    )
}

/// 从全天 HTML 中剔除落在 excluded 区间（毫秒）内的消息块，返回过滤后的完整 HTML。
/// 与 monitor/_filter_daily_html 等价：按 MSG_OPEN 切分、解析时间戳、命中区间则丢弃。
pub fn filter_daily_html(html: &str, excluded: &[(i64, i64)]) -> String {
    if excluded.is_empty() {
        return html.to_string();
    }
    let (Some(bs), Some(be)) = (html.find("<body>"), html.find("</body>")) else {
        return html.to_string();
    };
    let header = &html[..bs + "<body>".len()];
    let footer = &html[be..];
    let body = &html[bs + "<body>".len()..be];

    let mut kept = String::new();
    for part in body.split(MSG_OPEN).skip(1) {
        let div_html = format!("{MSG_OPEN}{part}");
        let ms = extract_ts_ms(&div_html);
        if let Some(ms) = ms {
            if excluded.iter().any(|&(s, e)| s <= ms && ms <= e) {
                continue;
            }
        }
        kept.push_str(&div_html);
    }
    if kept.is_empty() {
        String::new()
    } else {
        format!("{header}{kept}{footer}")
    }
}

/// 从单个消息块 HTML 中解析时间戳（毫秒）。
fn extract_ts_ms(div_html: &str) -> Option<i64> {
    // 形如 <span style="font-size:11px;color:#aaa;margin-left:8px">2026-06-15 10:00:00</span>
    let marker = r#"margin-left:8px">"#;
    let start = div_html.find(marker)? + marker.len();
    let end = div_html[start..].find("</span>")? + start;
    let ts = div_html[start..end].trim();
    let dt = chrono::NaiveDateTime::parse_from_str(ts, "%Y-%m-%d %H:%M:%S").ok()?;
    Local
        .from_local_datetime(&dt)
        .single()
        .map(|d| d.timestamp_millis())
}
