//! 调用外置 welink-cli（既有二进制）拉取群聊历史。
//! welink-cli im query-history-message --group-id X --query-count N
//! 返回 { resultCode, resultContext, respData: { chatInfo: [...] } }

use std::process::Command;

use serde_json::Value;

use crate::settings::Settings;

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

/// welink-cli 解析顺序：设置里的路径 → 环境变量 WELINK_CLI → PATH 里的 `welink-cli`。
fn program(settings: &Settings) -> String {
    let p = settings.welink_cli_path.trim();
    if !p.is_empty() {
        return p.to_string();
    }
    if let Some(env) = std::env::var_os("WELINK_CLI") {
        let s = env.to_string_lossy().trim().to_string();
        if !s.is_empty() {
            return s;
        }
    }
    "welink-cli".to_string()
}

/// 拉取某群最近 count 条消息，返回 (messages_json, error)。
pub fn query_history(settings: &Settings, group_id: &str, count: u32) -> Result<Vec<Value>, String> {
    let count_s = count.to_string();
    let args = [
        "im",
        "query-history-message",
        "--group-id",
        group_id,
        "--query-count",
        count_s.as_str(),
    ];

    let mut cmd = Command::new(program(settings));
    cmd.args(args);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }

    let out = cmd
        .output()
        .map_err(|e| format!("启动 welink-cli 失败: {e}"))?;
    let stdout = String::from_utf8_lossy(&out.stdout);
    let trimmed = stdout.trim();
    if trimmed.is_empty() {
        let err = String::from_utf8_lossy(&out.stderr);
        return Err(format!("welink-cli 无输出 (stderr: {})", err.trim()));
    }

    let v: Value = serde_json::from_str(trimmed).map_err(|e| format!("JSON 解析失败: {e}"))?;
    let code = v.get("resultCode").and_then(|x| x.as_str()).unwrap_or("");
    if code != "0" {
        let ctx = v.get("resultContext").and_then(|x| x.as_str()).unwrap_or("");
        return Err(format!("resultCode={code} context={ctx}"));
    }
    let chat = v
        .get("respData")
        .and_then(|d| d.get("chatInfo"))
        .and_then(|c| c.as_array())
        .cloned()
        .unwrap_or_default();
    Ok(chat)
}
