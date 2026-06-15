"use client";

import { useEffect, useState } from "react";

import { invoke } from "@/lib/tauri";
import { useAppStore } from "@/store/app";
import { useSettings } from "@/store/settings";
import LogPanel from "@/components/common/LogPanel";

export default function WelinkPanel() {
  const [running, setRunning] = useState(false);
  const [busy, setBusy] = useState(false);
  const appendLog = useAppStore((s) => s.appendLog);
  const { settings, loaded, load } = useSettings();

  useEffect(() => {
    if (!loaded) load();
    syncStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function syncStatus() {
    try {
      setRunning(await invoke<boolean>("welink_running"));
    } catch {
      /* ignore */
    }
  }

  async function toggle() {
    setBusy(true);
    try {
      if (running) {
        await invoke("welink_stop");
        setRunning(false);
      } else {
        if (!settings.output_dir) {
          appendLog("请先在「设置」里配置输出目录");
          return;
        }
        if (settings.welink_groups.filter((g) => g.enabled).length === 0) {
          appendLog("没有启用的监听群，请先在「设置」里添加");
          return;
        }
        await invoke("welink_start");
        setRunning(true);
      }
    } catch (e) {
      appendLog(`操作失败: ${e}`);
    } finally {
      setBusy(false);
    }
  }

  const groups = settings.welink_groups.filter((g) => g.enabled);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          marginBottom: 12,
        }}
      >
        <span
          style={{
            color: running ? "#008c64" : "#ccc",
            fontSize: 14,
          }}
        >
          ●
        </span>
        <span
          style={{
            fontSize: 13,
            fontWeight: 600,
            color: running ? "#008c64" : "#888",
          }}
        >
          {running ? "监听中" : "未运行"}
        </span>
        <div style={{ flex: 1 }} />
        <button
          onClick={toggle}
          disabled={busy}
          style={{
            height: 32,
            padding: "0 18px",
            fontSize: 13,
            borderRadius: 4,
            cursor: busy ? "not-allowed" : "pointer",
            color: "#fff",
            border: "none",
            background: running ? "#b71c1c" : "#008c64",
            opacity: busy ? 0.6 : 1,
          }}
        >
          {running ? "停止监听" : "开始监听"}
        </button>
      </div>

      <div
        style={{
          background: "#fff",
          border: "1px solid #e3e5e9",
          borderRadius: 8,
          padding: "12px 16px",
          fontSize: 12,
          color: "#555",
          marginBottom: 10,
        }}
      >
        <div style={{ marginBottom: 8 }}>
          <b>命令</b>　开始：
          <code>{settings.welink_start_cmd}</code>　结束：
          <code>{settings.welink_end_cmd}</code>　总结：
          <code>{settings.welink_summary_cmd}</code>
        </div>
        <div style={{ marginBottom: 8 }}>
          <b>按天归档</b>
          {settings.welink_daily_record
            ? `每日 ${settings.welink_daily_time} 归档前一天`
            : "未启用"}
          　·　轮询 {settings.welink_poll_interval}s
        </div>
        <div>
          <b>监听群（{groups.length}）</b>
          {groups.length === 0 ? (
            <span style={{ color: "#aaa" }}>　未配置，去「设置」添加</span>
          ) : (
            <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
              {groups.map((g) => (
                <li key={g.id}>
                  {g.group_name || g.group_id}
                  <span style={{ color: "#aaa" }}>（{g.group_id}）</span>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div style={{ marginTop: 8, color: "#aaa" }}>
          命令、群、间隔等均在「设置 → WeLink」中配置；改动后请重启监听生效。
        </div>
      </div>

      <LogPanel height={260} />
    </div>
  );
}
