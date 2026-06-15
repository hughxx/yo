//! 调用外置 outlook_cli（dev 用 `python outlook_cli.py`，prod 用随包 exe）。
//! 约定：成功 stdout 输出 JSON、退出码 0；失败 stderr 输出 {"error":...}、退出码非 0。

use std::path::Path;
use std::process::Command;

use serde_json::Value;
use tauri::{AppHandle, Manager};

use crate::settings::Settings;

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

/// 解析 outlook_cli 的可执行方式：返回 (程序, 前置参数)。
fn resolve_outlook(app: &AppHandle, settings: &Settings) -> (String, Vec<String>) {
    // 1) 用户显式配置
    let configured = settings.outlook_cli_path.trim();
    if !configured.is_empty() {
        return (configured.to_string(), vec![]);
    }
    // 2) 随包资源
    if let Ok(res) = app.path().resource_dir() {
        let exe = res.join("outlook_cli.exe");
        if exe.exists() {
            return (exe.to_string_lossy().into_owned(), vec![]);
        }
    }
    // 3) 开发回退：python <crate>/../sidecar/outlook_cli/outlook_cli.py
    let script = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("sidecar")
        .join("outlook_cli")
        .join("outlook_cli.py");
    ("python".to_string(), vec![script.to_string_lossy().into_owned()])
}

/// 运行一条 outlook_cli 子命令，返回解析后的 JSON。
pub fn run_outlook(app: &AppHandle, settings: &Settings, args: &[&str]) -> Result<Value, String> {
    let (program, prefix) = resolve_outlook(app, settings);

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
