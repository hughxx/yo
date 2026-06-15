//! 邮件流：扫描 → 规则匹配 → HTML/MD → 落盘（DESIGN.md §5.1）。

use std::collections::HashSet;

use serde::{Deserialize, Serialize};
use tauri::AppHandle;

use crate::events::emit_log;
use crate::images::{process_email_html, InlineImage};
use crate::settings::{EmailRule, Settings};
use crate::{htmlmd, output, sidecar};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EmailSummary {
    pub item_id: String,
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

#[derive(Debug, Deserialize)]
struct EmailDetail {
    #[serde(default)]
    subject: String,
    #[serde(default)]
    conversation_topic: String,
    #[serde(default)]
    received_time: String,
    #[serde(default)]
    html_body: String,
    #[serde(default)]
    inline_images: Vec<InlineImage>,
}

#[derive(Debug, Default, Serialize)]
pub struct ScanReport {
    pub scanned: usize,
    pub matched: usize,
    pub saved: usize,
    pub skipped: usize,
    pub failed: usize,
}

// ── 列表（供 UI 预览） ──────────────────────────────────────

pub fn list(app: &AppHandle, settings: &Settings, count: u32) -> Result<Vec<EmailSummary>, String> {
    let folders = settings.scan_folders.join(",");
    let count_s = count.to_string();
    let mut args = vec!["list", "--count", count_s.as_str()];
    if !folders.is_empty() {
        args.push("--folders");
        args.push(folders.as_str());
    }
    let v = sidecar::run_outlook(app, settings, &args)?;
    serde_json::from_value(v).map_err(|e| format!("解析邮件列表失败: {e}"))
}

// ── 规则匹配 ────────────────────────────────────────────────

fn contains_ci(haystack: &str, needle: &str) -> bool {
    haystack.to_lowercase().contains(&needle.to_lowercase())
}

fn subject_hit(subject: &str, keywords: &[String]) -> bool {
    keywords.iter().any(|k| !k.is_empty() && contains_ci(subject, k))
}

fn sender_hit(email: &EmailSummary, senders: &[String]) -> bool {
    senders.iter().any(|s| {
        !s.is_empty() && (contains_ci(&email.sender_name, s) || contains_ci(&email.sender_email, s))
    })
}

/// 单条规则是否命中。body_hits 是该规则正文关键词预先搜出的 item_id 集合。
fn rule_matches(email: &EmailSummary, rule: &EmailRule, body_hits: &HashSet<String>) -> bool {
    let mut groups: Vec<bool> = Vec::new();
    if !rule.keywords.is_empty() {
        groups.push(subject_hit(&email.subject, &rule.keywords));
    }
    if !rule.senders.is_empty() {
        groups.push(sender_hit(email, &rule.senders));
    }
    if !rule.body_keywords.is_empty() {
        groups.push(body_hits.contains(&email.item_id));
    }
    if groups.is_empty() {
        return false; // 空规则不匹配任何邮件
    }
    if rule.logic.eq_ignore_ascii_case("AND") {
        groups.iter().all(|&b| b)
    } else {
        groups.iter().any(|&b| b)
    }
}

/// 预取每条启用规则的正文命中集合（仅对有 body_keywords 的规则发起 search-body）。
fn body_hits_for_rule(
    app: &AppHandle,
    settings: &Settings,
    rule: &EmailRule,
) -> HashSet<String> {
    if rule.body_keywords.is_empty() {
        return HashSet::new();
    }
    let folders = settings.scan_folders.join(",");
    let kw = rule.body_keywords.join(",");
    let mut args = vec!["search-body", "--keywords", kw.as_str()];
    if !folders.is_empty() {
        args.push("--folders");
        args.push(folders.as_str());
    }
    match sidecar::run_outlook(app, settings, &args) {
        Ok(v) => serde_json::from_value::<Vec<String>>(v).unwrap_or_default().into_iter().collect(),
        Err(e) => {
            emit_log(app, format!("规则[{}] 正文搜索失败: {e}", rule.name));
            HashSet::new()
        }
    }
}

// ── 单封处理 ────────────────────────────────────────────────

/// 取详情 → 图片转外链 → 转 MD → 落盘。返回是否真正落盘（skip 策略下可能为 false）。
fn process_one(
    app: &AppHandle,
    settings: &Settings,
    item_id: &str,
) -> Result<bool, String> {
    let v = sidecar::run_outlook(app, settings, &["get", "--entry-id", item_id])?;
    process_detail(app, settings, v)
}

fn process_detail(app: &AppHandle, settings: &Settings, v: serde_json::Value) -> Result<bool, String> {
    let detail: EmailDetail =
        serde_json::from_value(v).map_err(|e| format!("解析邮件详情失败: {e}"))?;

    let html = process_email_html(settings, &detail.html_body, &detail.inline_images);
    let md = htmlmd::html_to_md(&html);

    let title = if !detail.subject.trim().is_empty() {
        detail.subject.clone()
    } else if !detail.conversation_topic.trim().is_empty() {
        detail.conversation_topic.clone()
    } else {
        "untitled".to_string()
    };

    match output::save(settings, &detail.received_time, &title, &html, &md)? {
        Some(saved) => {
            emit_log(app, format!("已保存: {}", saved.base_name));
            Ok(true)
        }
        None => {
            emit_log(app, format!("已存在跳过: {title}"));
            Ok(false)
        }
    }
}

// ── 扫描主流程 ──────────────────────────────────────────────

pub fn run_scan(
    app: &AppHandle,
    settings: &Settings,
    processed: &mut HashSet<String>,
) -> Result<ScanReport, String> {
    emit_log(app, "开始扫描邮件…");
    let mut report = ScanReport::default();

    let emails = list(app, settings, 9999)?;
    report.scanned = emails.len();
    emit_log(app, format!("读取到 {} 封邮件", emails.len()));

    let rules: Vec<&EmailRule> = settings.email_rules.iter().filter(|r| r.enabled).collect();
    if rules.is_empty() {
        emit_log(app, "没有启用的规则，未匹配任何邮件");
        return Ok(report);
    }

    // 预取每条规则的正文命中集合
    let body_hits: Vec<HashSet<String>> =
        rules.iter().map(|r| body_hits_for_rule(app, settings, r)).collect();

    // 匹配
    let mut matched_ids: Vec<String> = Vec::new();
    let mut seen: HashSet<String> = HashSet::new();
    for email in &emails {
        let hit = rules
            .iter()
            .zip(body_hits.iter())
            .any(|(rule, bh)| rule_matches(email, rule, bh));
        if hit && seen.insert(email.item_id.clone()) {
            matched_ids.push(email.item_id.clone());
        }
    }
    report.matched = matched_ids.len();
    emit_log(app, format!("规则匹配 {} 封", matched_ids.len()));

    // 处理未处理过的
    for id in matched_ids {
        if processed.contains(&id) {
            report.skipped += 1;
            continue;
        }
        match process_one(app, settings, &id) {
            Ok(true) => {
                report.saved += 1;
                processed.insert(id);
            }
            Ok(false) => {
                // skip 策略未落盘，但仍视为已处理避免反复尝试
                processed.insert(id);
            }
            Err(e) => {
                report.failed += 1;
                emit_log(app, format!("处理失败 {id}: {e}"));
            }
        }
    }

    emit_log(
        app,
        format!(
            "扫描完成：匹配 {} / 保存 {} / 跳过 {} / 失败 {}",
            report.matched, report.saved, report.skipped, report.failed
        ),
    );
    Ok(report)
}

// ── 导入 .msg / .pst ────────────────────────────────────────

/// 批量导入 .msg：每个文件 msg-get → 处理 → 落盘。返回保存数量。
pub fn import_msg(
    app: &AppHandle,
    settings: &Settings,
    processed: &mut HashSet<String>,
    paths: &[String],
) -> Result<usize, String> {
    let mut saved = 0usize;
    for path in paths {
        emit_log(app, format!("导入 .msg: {path}"));
        match sidecar::run_outlook(app, settings, &["msg-get", "--path", path]) {
            Ok(v) => {
                // 去重键用 item_id
                let id = v
                    .get("item_id")
                    .and_then(|x| x.as_str())
                    .unwrap_or("")
                    .to_string();
                if !id.is_empty() && processed.contains(&id) {
                    emit_log(app, "已处理过，跳过");
                    continue;
                }
                match process_detail(app, settings, v) {
                    Ok(true) => {
                        saved += 1;
                        if !id.is_empty() {
                            processed.insert(id);
                        }
                    }
                    Ok(false) => {
                        if !id.is_empty() {
                            processed.insert(id);
                        }
                    }
                    Err(e) => emit_log(app, format!("处理失败: {e}")),
                }
            }
            Err(e) => emit_log(app, format!("读取 .msg 失败: {e}")),
        }
    }
    Ok(saved)
}

/// 挂载 .pst，返回新 store 显示名（空串表示已挂载过）。
pub fn import_pst(app: &AppHandle, settings: &Settings, path: &str) -> Result<String, String> {
    let v = sidecar::run_outlook(app, settings, &["add-pst", "--path", path])?;
    Ok(v.get("display_name")
        .and_then(|x| x.as_str())
        .unwrap_or("")
        .to_string())
}
