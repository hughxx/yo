//! WeLink 导出聊天记录（HistoryRecord zip）解析 —— 纯 Rust 实现。
//! 移植自旧 chatlog_import.py：解析 txt + 图片，按时间戳对齐 [图片] 占位，
//! 拼成 HTML（图片用 cid:chatimg_N 占位，写临时文件），交由上层转外链/落盘。

use std::io::Read;
use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

use chrono::{Local, NaiveDateTime, TimeZone};
use regex::Regex;

use crate::images::InlineImage;

const IMG_EXTS: [&str; 6] = [".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"];
const IMG_TOKEN: &str = "[图片]";

pub struct ChatlogParsed {
    pub stem: String,
    pub start_time: i64,
    #[allow(dead_code)]
    pub end_time: i64,
    pub count: usize,
    pub summary: String,
    pub html: String,
    pub images: Vec<InlineImage>,
}

struct Img {
    name: String,
    mtime: i64,
    data: Vec<u8>,
}

#[derive(Clone)]
enum Seg {
    Text(String),
    Image,
}

struct Msg {
    name: String,
    uid: String,
    ts_ms: i64,
    ts_str: String,
    segments: Vec<Seg>,
}

pub fn parse_zip(zip_path: &str) -> Result<ChatlogParsed, String> {
    let (stem, text, images) = read_zip(zip_path)?;
    let messages = parse_chatlog(&text);
    if messages.is_empty() {
        return Err("未解析到任何消息，请确认 txt 格式".to_string());
    }
    let (assign, leftover, hints, summary) = match_images(&messages, &images);

    let tmp_dir = make_tmp_dir();
    std::fs::create_dir_all(&tmp_dir).map_err(|e| format!("创建临时目录失败: {e}"))?;
    let (html, out_imgs) = build_html(&messages, &images, &assign, &leftover, &hints, &summary, &tmp_dir);

    Ok(ChatlogParsed {
        stem,
        start_time: messages.first().map(|m| m.ts_ms).unwrap_or(0),
        end_time: messages.last().map(|m| m.ts_ms).unwrap_or(0),
        count: messages.len(),
        summary,
        html,
        images: out_imgs,
    })
}

// ── 读取 zip ──────────────────────────────────────────────

fn read_zip(path: &str) -> Result<(String, String, Vec<Img>), String> {
    let file = std::fs::File::open(path).map_err(|e| format!("打开 zip 失败: {e}"))?;
    let mut zip = zip::ZipArchive::new(file).map_err(|e| format!("读取 zip 失败: {e}"))?;

    // 第一遍：收集元数据
    struct Meta {
        index: usize,
        name: String,
        is_dir: bool,
        mtime: i64,
    }
    let mut metas = Vec::new();
    for i in 0..zip.len() {
        if let Ok(f) = zip.by_index(i) {
            let mtime = f
                .last_modified()
                .and_then(|d| {
                    NaiveDateTime::parse_from_str(
                        &format!(
                            "{:04}-{:02}-{:02} {:02}:{:02}:{:02}",
                            d.year(), d.month(), d.day(), d.hour(), d.minute(), d.second()
                        ),
                        "%Y-%m-%d %H:%M:%S",
                    )
                    .ok()
                })
                .map(|nd| nd.and_utc().timestamp())
                .unwrap_or(i64::MIN);
            metas.push(Meta {
                index: i,
                name: f.name().replace('\\', "/"),
                is_dir: f.is_dir(),
                mtime,
            });
        }
    }

    // 选 txt：优先 historyrecord 下的，否则任一 txt
    let txt_meta = metas
        .iter()
        .filter(|m| !m.is_dir && m.name.to_lowercase().ends_with(".txt"))
        .min_by_key(|m| if m.name.to_lowercase().contains("historyrecord") { 0 } else { 1 })
        .ok_or("压缩包内未找到聊天记录 txt")?;
    let txt_index = txt_meta.index;
    let txt_name = txt_meta.name.clone();

    let stem = txt_name.rsplit('/').next().unwrap_or(&txt_name)
        .rsplit_once('.').map(|(a, _)| a).unwrap_or(&txt_name).to_string();
    let txt_dir = if txt_name.contains('/') {
        txt_name.rsplit_once('/').map(|(a, _)| a).unwrap_or("")
    } else {
        ""
    };
    let prefix = if txt_dir.is_empty() {
        format!("{stem}/")
    } else {
        format!("{txt_dir}/{stem}/")
    };

    // 图片项：优先 prefix 下，否则归档内所有图片
    let is_img = |n: &str| {
        let l = n.to_lowercase();
        IMG_EXTS.iter().any(|e| l.ends_with(e))
    };
    let mut img_indices: Vec<(usize, String, i64)> = metas
        .iter()
        .filter(|m| !m.is_dir && is_img(&m.name) && m.name.starts_with(&prefix))
        .map(|m| (m.index, m.name.clone(), m.mtime))
        .collect();
    if img_indices.is_empty() {
        img_indices = metas
            .iter()
            .filter(|m| !m.is_dir && is_img(&m.name))
            .map(|m| (m.index, m.name.clone(), m.mtime))
            .collect();
    }

    // 第二遍：读字节
    let txt_text = {
        let mut f = zip.by_index(txt_index).map_err(|e| format!("读取 txt 失败: {e}"))?;
        let mut buf = Vec::new();
        f.read_to_end(&mut buf).map_err(|e| format!("读取 txt 失败: {e}"))?;
        decode(&buf)
    };

    let mut images = Vec::new();
    for (idx, name, mtime) in img_indices {
        if let Ok(mut f) = zip.by_index(idx) {
            let mut buf = Vec::new();
            if f.read_to_end(&mut buf).is_ok() {
                images.push(Img {
                    name: name.rsplit('/').next().unwrap_or(&name).to_string(),
                    mtime,
                    data: buf,
                });
            }
        }
    }

    Ok((stem, txt_text, images))
}

fn decode(raw: &[u8]) -> String {
    let raw = raw.strip_prefix(&[0xEF, 0xBB, 0xBF]).unwrap_or(raw);
    match std::str::from_utf8(raw) {
        Ok(s) => s.to_string(),
        Err(_) => {
            let (cow, _, _) = encoding_rs::GB18030.decode(raw);
            cow.into_owned()
        }
    }
}

// ── 解析 txt ──────────────────────────────────────────────

fn parse_chatlog(text: &str) -> Vec<Msg> {
    let re = Regex::new(r"([^\n(]+?)\((\w+)\)\s+(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})").unwrap();
    // 收集所有匹配（含位置）用于切分正文
    let spans: Vec<(usize, usize, String, String, String)> = re
        .captures_iter(text)
        .map(|c| {
            let m = c.get(0).unwrap();
            (
                m.start(),
                m.end(),
                c.get(1).unwrap().as_str().trim().to_string(),
                c.get(2).unwrap().as_str().to_string(),
                c.get(3).unwrap().as_str().to_string(),
            )
        })
        .collect();

    let mut out = Vec::new();
    for i in 0..spans.len() {
        let (_, end, name, uid, ts_str) = &spans[i];
        let next_start = spans.get(i + 1).map(|s| s.0).unwrap_or(text.len());
        let raw = &text[*end..next_start];
        let Some(ts_ms) = parse_ts(ts_str) else { continue };
        out.push(Msg {
            name: name.clone(),
            uid: uid.clone(),
            ts_ms,
            ts_str: ts_str.clone(),
            segments: split_segments(raw),
        });
    }
    out
}

fn parse_ts(s: &str) -> Option<i64> {
    let nd = NaiveDateTime::parse_from_str(s, "%Y-%m-%d %H:%M:%S").ok()?;
    Local.from_local_datetime(&nd).single().map(|d| d.timestamp_millis())
}

fn split_segments(raw: &str) -> Vec<Seg> {
    let content = raw.trim();
    if content.is_empty() {
        return vec![];
    }
    let parts: Vec<&str> = content.split(IMG_TOKEN).collect();
    let mut segs = Vec::new();
    for (j, part) in parts.iter().enumerate() {
        let p = part.trim();
        if !p.is_empty() {
            segs.push(Seg::Text(p.to_string()));
        }
        if j < parts.len() - 1 {
            segs.push(Seg::Image);
        }
    }
    segs
}

// ── 图片对齐 ──────────────────────────────────────────────

#[allow(clippy::type_complexity)]
fn match_images(
    messages: &[Msg],
    images: &[Img],
) -> (Vec<Option<usize>>, Vec<usize>, std::collections::HashMap<usize, String>, String) {
    // 文档顺序的占位符 (msg_idx, seg_idx)
    let mut placeholders: Vec<(usize, usize)> = Vec::new();
    for (mi, msg) in messages.iter().enumerate() {
        for (si, seg) in msg.segments.iter().enumerate() {
            if matches!(seg, Seg::Image) {
                placeholders.push((mi, si));
            }
        }
    }
    let n = placeholders.len();

    // 占位符按所属消息时间排序（带文档序保证稳定）
    let mut order: Vec<usize> = (0..n).collect();
    order.sort_by_key(|&k| (messages[placeholders[k].0].ts_ms, k));
    // 图片按 mtime + name 排序
    let mut imgs_sorted: Vec<usize> = (0..images.len()).collect();
    imgs_sorted.sort_by(|&a, &b| {
        (images[a].mtime, &images[a].name).cmp(&(images[b].mtime, &images[b].name))
    });

    let mut assign = vec![None; n];
    for (rank, &k) in order.iter().enumerate() {
        assign[k] = imgs_sorted.get(rank).copied();
    }
    let leftover: Vec<usize> = imgs_sorted.iter().skip(n).copied().collect();

    // 同 mtime 多图歧义提示
    let mut hints = std::collections::HashMap::new();
    let mut groups: std::collections::HashMap<i64, Vec<usize>> = std::collections::HashMap::new();
    for rank in 0..n.min(imgs_sorted.len()) {
        groups.entry(images[imgs_sorted[rank]].mtime).or_default().push(order[rank]);
    }
    for (_mtime, ks) in groups {
        if ks.len() > 1 {
            let min_k = *ks.iter().min().unwrap();
            hints.insert(min_k, format!("⚠ 下面 {} 张图片修改时间相同，自动排序可能与实际不符，请自行核对", ks.len()));
        }
    }

    let mut summary = String::new();
    if n != images.len() {
        summary = format!("共 {} 个 [图片] 占位符，{} 张图片，已按时间顺序对应。", n, images.len());
        if !leftover.is_empty() {
            summary.push_str(&format!("多出的 {} 张未能在文本中定位，已附在末尾。", leftover.len()));
        }
    }

    (assign, leftover, hints, summary)
}

// ── 渲染 HTML（cid 占位 + 写临时图片） ────────────────────

fn esc(s: &str) -> String {
    s.replace('&', "&amp;").replace('<', "&lt;").replace('>', "&gt;").replace('"', "&quot;")
}

fn warn_div(text: &str) -> String {
    format!(
        "<div style=\"margin:4px 0;padding:4px 8px;font-size:12px;color:#b71c1c;background:#fff8e1;border:1px solid #ffe082;border-radius:4px\">{}</div>",
        esc(text)
    )
}

fn build_html(
    messages: &[Msg],
    images: &[Img],
    assign: &[Option<usize>],
    leftover: &[usize],
    hints: &std::collections::HashMap<usize, String>,
    summary: &str,
    tmp_dir: &PathBuf,
) -> (String, Vec<InlineImage>) {
    // 占位符 doc 顺序索引
    let mut placeholders: Vec<(usize, usize)> = Vec::new();
    for (mi, msg) in messages.iter().enumerate() {
        for (si, seg) in msg.segments.iter().enumerate() {
            if matches!(seg, Seg::Image) {
                placeholders.push((mi, si));
            }
        }
    }
    let ph_index: std::collections::HashMap<(usize, usize), usize> =
        placeholders.iter().enumerate().map(|(k, &p)| (p, k)).collect();

    let mut out_imgs: Vec<InlineImage> = Vec::new();
    let mut cid_for_img: std::collections::HashMap<usize, String> = std::collections::HashMap::new();
    let mut ensure_cid = |img_idx: usize| -> Option<String> {
        if let Some(c) = cid_for_img.get(&img_idx) {
            return Some(c.clone());
        }
        let cid = format!("chatimg_{}", out_imgs.len());
        let ext = std::path::Path::new(&images[img_idx].name)
            .extension()
            .and_then(|e| e.to_str())
            .map(|e| format!(".{e}"))
            .unwrap_or_else(|| ".png".to_string());
        let path = tmp_dir.join(format!("{cid}{ext}"));
        if std::fs::write(&path, &images[img_idx].data).is_ok() {
            out_imgs.push(InlineImage { cid: cid.clone(), path: path.to_string_lossy().into_owned() });
            cid_for_img.insert(img_idx, cid.clone());
            Some(cid)
        } else {
            None
        }
    };

    let msg_open = super::render::MSG_OPEN;
    let mut rows = String::new();
    if !summary.is_empty() {
        rows.push_str(&warn_div(summary));
    }

    for (mi, msg) in messages.iter().enumerate() {
        let mut body = String::new();
        for (si, seg) in msg.segments.iter().enumerate() {
            match seg {
                Seg::Text(t) => body.push_str(&esc(t).replace('\n', "<br>")),
                Seg::Image => {
                    let k = ph_index.get(&(mi, si)).copied();
                    if let Some(k) = k {
                        if let Some(h) = hints.get(&k) {
                            body.push_str(&warn_div(h));
                        }
                    }
                    let img = k.and_then(|k| assign.get(k).copied().flatten());
                    let cid = img.and_then(|i| ensure_cid(i));
                    if let Some(cid) = cid {
                        body.push_str(&format!(
                            "<img src=\"cid:{cid}\" style=\"max-width:480px;display:block\">"
                        ));
                    } else {
                        body.push_str("<em style=\"color:#c00\">[图片]（未找到对应图片）</em>");
                    }
                }
            }
        }
        rows.push_str(&format!(
            "{msg_open}<span style=\"font-weight:bold;color:#1a73e8\">{}({})</span><span style=\"font-size:11px;color:#aaa;margin-left:8px\">{}</span><div style=\"margin-top:4px\">{body}</div></div>",
            esc(&msg.name), esc(&msg.uid), esc(&msg.ts_str)
        ));
    }

    for &im in leftover {
        if let Some(cid) = ensure_cid(im) {
            rows.push_str(&format!(
                "{msg_open}<div><img src=\"cid:{cid}\" style=\"max-width:480px;display:block\"><small style=\"color:#888\">{}</small></div></div>",
                esc(&images[im].name)
            ));
        }
    }

    let html = format!(
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\"><style>body{{font-family:Arial,sans-serif;font-size:13px;color:#222;max-width:860px;margin:20px auto;padding:0 16px}}</style></head><body>{rows}</body></html>"
    );
    (html, out_imgs)
}

fn make_tmp_dir() -> PathBuf {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    std::env::temp_dir().join(format!("chatlog_img_{nanos}"))
}
