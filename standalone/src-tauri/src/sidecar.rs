//! 调用外置 outlook_cli（dev 用 `python outlook_cli.py`，prod 用随包 exe）。
//! 约定：成功 stdout 输出 JSON、退出码 0；失败 stderr 输出 {"error":...}、退出码非 0。

use std::io::{Read, Write};
use std::path::Path;
use std::process::{Child, Command, Output, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use serde_json::Value;
use tauri::{AppHandle, Manager};

use crate::settings::Settings;

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

/// outlook_cli 串行执行：Outlook 自动化本质上是单实例，并发 Dispatch 会互相
/// 抢占 / 卡死。所有 outlook_cli 调用经此锁排队。
static OUTLOOK_LOCK: Mutex<()> = Mutex::new(());

/// 单次 outlook_cli 上限。超时通常意味着弹出了不可见的 Outlook 安全/登录/
/// 配置文件对话框（CREATE_NO_WINDOW 下无法看到或应答），到点强杀进程树，
/// 避免像历史上那样留下长期僵尸进程。
const OUTLOOK_TIMEOUT: Duration = Duration::from_secs(120);

/// 等待子进程结束，超时则强杀其进程树。stdout/stderr 用独立线程读取，避免
/// 管道写满导致的死锁。
fn wait_with_timeout(mut child: Child, timeout: Duration) -> Result<Output, String> {
    let mut so = child.stdout.take();
    let mut se = child.stderr.take();
    let h_so = std::thread::spawn(move || {
        let mut buf = Vec::new();
        if let Some(s) = so.as_mut() {
            let _ = s.read_to_end(&mut buf);
        }
        buf
    });
    let h_se = std::thread::spawn(move || {
        let mut buf = Vec::new();
        if let Some(s) = se.as_mut() {
            let _ = s.read_to_end(&mut buf);
        }
        buf
    });

    let start = Instant::now();
    let status = loop {
        match child.try_wait() {
            Ok(Some(s)) => break Some(s),
            Ok(None) => {
                if start.elapsed() >= timeout {
                    let pid = child.id();
                    let _ = child.kill();
                    // PyInstaller onefile 会再起一个子进程，单 kill 杀不净，taskkill /T 清整棵树。
                    #[cfg(windows)]
                    {
                        use std::os::windows::process::CommandExt;
                        let _ = Command::new("taskkill")
                            .args(["/F", "/T", "/PID", &pid.to_string()])
                            .creation_flags(CREATE_NO_WINDOW)
                            .output();
                    }
                    let _ = child.wait();
                    break None;
                }
                std::thread::sleep(Duration::from_millis(50));
            }
            Err(e) => return Err(format!("等待 outlook_cli 失败: {e}")),
        }
    };
    let stdout = h_so.join().unwrap_or_default();
    let stderr = h_se.join().unwrap_or_default();
    match status {
        Some(status) => Ok(Output { status, stdout, stderr }),
        None => Err("outlook_cli 超时（疑似弹出了 Outlook 安全/登录/配置文件对话框，已强制结束）".to_string()),
    }
}

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
    // 串行：避免并发 Dispatch 抢占同一个 Outlook 实例而互相卡死。
    let _guard = OUTLOOK_LOCK.lock().unwrap_or_else(|e| e.into_inner());

    let (program, prefix) = resolve_sidecar(app, &settings.outlook_cli_path, "outlook_cli");

    let mut cmd = Command::new(&program);
    cmd.args(&prefix)
        .args(args)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }

    let child = cmd
        .spawn()
        .map_err(|e| format!("启动 outlook_cli 失败（{program}）: {e}"))?;
    let out = wait_with_timeout(child, OUTLOOK_TIMEOUT)?;

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
