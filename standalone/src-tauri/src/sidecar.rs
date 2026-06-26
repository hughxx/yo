//! 调用外置 outlook_cli（dev 用 `python outlook_cli.py`，prod 用随包 exe）。
//! 约定：成功 stdout 输出 JSON、退出码 0；失败 stderr 输出 {"error":...}、退出码非 0。

use std::io::Write;
use std::path::Path;
use std::process::{Command, Stdio};

use serde_json::Value;
use tauri::{AppHandle, Manager};

use crate::settings::Settings;

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

/// 通用解析外置 Python sidecar：返回 (程序, 前置参数)。
/// 查找顺序：配置路径 → 应用 bin/<stem>.exe（D 盘，HTTP 下载落地处）→ 随包资源 → 开发回退(python 脚本)。
fn resolve_sidecar(app: &AppHandle, configured: &str, stem: &str) -> (String, Vec<String>) {
    let configured = configured.trim();
    if !configured.is_empty() {
        return (configured.to_string(), vec![]);
    }
    let exe = format!("{stem}.exe");
    // 应用 bin/（D 盘，后期 HTTP 二次下载放这里）
    if let Some(dir) = crate::settings::sidecar_bin_dir() {
        let p = dir.join(&exe);
        if p.exists() {
            return (p.to_string_lossy().into_owned(), vec![]);
        }
    }
    // 随包资源
    if let Ok(res) = app.path().resource_dir() {
        let p = res.join(&exe);
        if p.exists() {
            return (p.to_string_lossy().into_owned(), vec![]);
        }
    }
    // 开发回退：python <crate>/../sidecar/<stem>/<stem>.py
    let script = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("sidecar")
        .join(stem)
        .join(format!("{stem}.py"));
    ("python".to_string(), vec![script.to_string_lossy().into_owned()])
}

/// 运行一条 outlook_cli 子命令，返回解析后的 JSON。
pub fn run_outlook(app: &AppHandle, settings: &Settings, args: &[&str]) -> Result<Value, String> {
    let (program, prefix) = resolve_sidecar(app, &settings.outlook_cli_path, "outlook_cli");

    let mut cmd = Command::new(&program);
    cmd.args(&prefix).args(args);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }

    let out = cmd
        .output()
        .map_err(|e| format!("启动 outlook_cli 失败（{program}）: {e}"))?;

    if !out.status.success() {
        let err = String::from_utf8_lossy(&out.stderr);
        let msg = serde_json::from_str::<Value>(err.trim())
            .ok()
            .and_then(|v| v.get("error").and_then(|e| e.as_str()).map(String::from))
            .unwrap_or_else(|| err.trim().to_string());
        return Err(if msg.is_empty() {
            "outlook_cli 执行失败".to_string()
        } else {
            msg
        });
    }

    let stdout = String::from_utf8_lossy(&out.stdout);
    serde_json::from_str(stdout.trim())
        .map_err(|e| format!("解析 outlook_cli 输出失败: {e}; 原始: {}", stdout.trim()))
}

// ── html2md sidecar ─────────────────────────────────────────

/// HTML → Markdown：把 HTML 通过 stdin 喂给 html2md sidecar，读回 Markdown。
pub fn run_html2md(app: &AppHandle, settings: &Settings, html: &str) -> Result<String, String> {
    let (program, prefix) = resolve_sidecar(app, &settings.html2md_cli_path, "html2md");

    let mut cmd = Command::new(&program);
    cmd.args(&prefix)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }

    let mut child = cmd.spawn().map_err(|e| format!("启动 html2md 失败（{program}）: {e}"))?;
    if let Some(mut stdin) = child.stdin.take() {
        stdin
            .write_all(html.as_bytes())
            .map_err(|e| format!("写 html2md stdin 失败: {e}"))?;
    }
    let out = child
        .wait_with_output()
        .map_err(|e| format!("等待 html2md 失败: {e}"))?;
    // 有 stdout 就用，不纠结退出码：个别打包形态（windowed）会在读 stdin 后
    // 以非零码退出却已正确输出，只有当真没产出时才算失败。
    let md = String::from_utf8_lossy(&out.stdout).into_owned();
    if md.trim().is_empty() {
        let err = String::from_utf8_lossy(&out.stderr);
        return Err(format!(
            "html2md 无输出 (exit {}): {}",
            out.status.code().unwrap_or(-1),
            err.trim()
        ));
    }
    Ok(md)
}
