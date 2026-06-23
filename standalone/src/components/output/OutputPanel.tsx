"use client";

import { useEffect, useState } from "react";

import { invoke } from "@/lib/tauri";
import type { OutputEntry, Settings, SyncStatus } from "@/lib/types";
import { useAppStore } from "@/store/app";
import { useSettings } from "@/store/settings";
import HelpTip from "@/components/welink/HelpTip";

export default function OutputPanel() {
  const [entries, setEntries] = useState<OutputEntry[]>([]);
  const [selected, setSelected] = useState<OutputEntry | null>(null);
  const [view, setView] = useState<"html" | "md">("html");
  const [html, setHtml] = useState("");
  const [md, setMd] = useState("");
  const [sync, setSync] = useState<SyncStatus | null>(null);
  const [syncing, setSyncing] = useState(false);
  const appendLog = useAppStore((s) => s.appendLog);
  const { settings, loaded, load, patch, save } = useSettings();

  useEffect(() => {
    if (!loaded) load();
    refresh();
    refreshSync();
    const t = setInterval(refreshSync, 10000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const setS = <K extends keyof Settings>(k: K, v: Settings[K]) => {
    patch({ [k]: v } as Partial<Settings>);
    save();
  };

  // 启用开关：立即生效（存盘后启停后台定时线程）
  async function toggleSync(on: boolean) {
    patch({ sync_enabled: on });
    try {
      await save();
      await invoke(on ? "sync_start" : "sync_stop");
    } catch {
      /* ignore */
    }
    refreshSync();
  }

  async function refresh() {
    try {
      const list = await invoke<OutputEntry[]>("list_outputs");
      setEntries(list ?? []);
    } catch (e) {
      appendLog(`读取输出件失败: ${e}`);
    }
  }

  async function refreshSync() {
    try {
      setSync(await invoke<SyncStatus>("sync_status"));
    } catch {
      /* ignore */
    }
  }

  async function syncNow() {
    setSyncing(true);
    try {
      await invoke("sync_now");
      appendLog("立即同步完成");
    } catch (e) {
      appendLog(`同步失败: ${e}`);
    } finally {
      setSyncing(false);
      refreshSync();
    }
  }

  async function pick(entry: OutputEntry) {
    setSelected(entry);
    try {
      const h = await invoke<string>("read_text_file", { path: entry.html_path });
      setHtml(h ?? "");
      if (entry.md_path) {
        const m = await invoke<string>("read_text_file", { path: entry.md_path });
        setMd(m ?? "");
      } else {
        setMd("（无 .md 文件）");
      }
    } catch (e) {
      appendLog(`打开失败: ${e}`);
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", gap: 12 }}>
      {/* 云同步 */}
      <div
        style={{
          padding: "10px 14px",
          border: "1px solid #e3e5e9",
          borderRadius: 8,
          background: "#fff",
          flexShrink: 0,
        }}
      >
        {/* 第一行：标题 + 帮助 + 状态 + 立即同步 */}
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: "#008c64" }}>云同步</span>
          <HelpTip>
            <div style={{ fontSize: 12, color: "#444", lineHeight: 1.8, width: "100%" }}>
              <b>定时执行 shell 命令，把本地输出件同步到云端向量库 / 存储引擎。</b>
              <br />
              到每天设定的时刻，程序在 shell 里跑你的命令：工作目录设为输出目录，并注入环境变量{" "}
              <code>OUTPUT_DIR</code>。你可用 <code>rclone</code> / <code>scp</code> / 自定义脚本，把产物推送到
              对象存储、向量数据库或自建服务器。
              <br />
              程序只负责按时调用，<b>不内置任何上传逻辑或凭据</b>。退出码 0 视为成功，命令输出写入运行日志。
            </div>
          </HelpTip>
          <span style={{ fontSize: 12, color: "#888" }}>
            {sync?.last_sync
              ? `上次 ${sync.last_sync} · ${sync.last_ok ? "成功" : `失败：${sync.last_msg}`}`
              : "尚未同步"}
          </span>
          <div style={{ flex: 1 }} />
          <button
            onClick={syncNow}
            disabled={syncing}
            style={{
              fontSize: 12,
              padding: "5px 14px",
              borderRadius: 4,
              border: "1px solid #008c64",
              background: syncing ? "#f0f1f3" : "#008c64",
              color: syncing ? "#888" : "#fff",
              cursor: syncing ? "not-allowed" : "pointer",
            }}
          >
            {syncing ? "同步中…" : "立即同步"}
          </button>
        </div>

        {/* 第二行：启用 + 命令 + 每天时刻 */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 10 }}>
          <label style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12, color: "#555" }}>
            <input
              type="checkbox"
              checked={settings.sync_enabled}
              onChange={(e) => toggleSync(e.target.checked)}
            />
            启用
          </label>
          <input
            value={settings.sync_command}
            placeholder={"同步命令，如  rclone copy . myremote:bucket   或   python D:\\sync.py"}
            onChange={(e) => setS("sync_command", e.target.value)}
            style={{
              flex: 1,
              height: 30,
              padding: "0 8px",
              fontSize: 12,
              border: "1px solid #d4d7dd",
              borderRadius: 4,
            }}
          />
          <span style={{ fontSize: 12, color: "#555" }}>每天</span>
          <input
            type="time"
            value={settings.sync_daily_time}
            onChange={(e) => setS("sync_daily_time", e.target.value)}
            style={{ height: 30, padding: "0 8px", fontSize: 12, border: "1px solid #d4d7dd", borderRadius: 4 }}
          />
        </div>
      </div>

      <div style={{ display: "flex", flex: 1, minHeight: 0, gap: 12 }}>
      {/* 左：列表 */}
      <div
        style={{
          width: 300,
          flexShrink: 0,
          display: "flex",
          flexDirection: "column",
          border: "1px solid #e3e5e9",
          borderRadius: 8,
          background: "#fff",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            padding: "8px 12px",
            borderBottom: "1px solid #eef0f2",
          }}
        >
          <span style={{ fontSize: 12, color: "#666" }}>输出件（{entries.length}）</span>
          <button
            onClick={refresh}
            style={{
              fontSize: 12,
              color: "#008c64",
              background: "none",
              border: "none",
              cursor: "pointer",
            }}
          >
            刷新
          </button>
        </div>
        <div style={{ flex: 1, overflow: "auto" }}>
          {entries.length === 0 ? (
            <div style={{ padding: 20, color: "#aaa", fontSize: 12 }}>
              暂无输出件。去「邮件 / 聊天记录」抓取，或检查设置里的输出目录。
            </div>
          ) : (
            ["邮件", "聊天记录"].map((src) => {
              const items = entries.filter((e) => e.source === src);
              if (items.length === 0) return null;
              return (
                <div key={src}>
                  <div
                    style={{
                      padding: "6px 12px",
                      fontSize: 11,
                      fontWeight: 600,
                      color: "#008c64",
                      background: "#f5f7f6",
                      position: "sticky",
                      top: 0,
                    }}
                  >
                    {src}（{items.length}）
                  </div>
                  {items.map((e) => (
                    <div
                      key={`${e.source}/${e.base_name}`}
                      onClick={() => pick(e)}
                      style={{
                        padding: "8px 12px",
                        cursor: "pointer",
                        borderBottom: "1px solid #f3f4f6",
                        background:
                          selected?.html_path === e.html_path ? "#e9f7f1" : "transparent",
                        wordBreak: "break-all",
                      }}
                    >
                      <div style={{ fontSize: 12, color: "#333" }}>{e.base_name}</div>
                      <div style={{ fontSize: 11, color: "#aaa", marginTop: 2 }}>{e.modified}</div>
                    </div>
                  ))}
                </div>
              );
            })
          )}
        </div>
      </div>

      {/* 右：预览 */}
      <div
        style={{
          flex: 1,
          display: "flex",
          flexDirection: "column",
          border: "1px solid #e3e5e9",
          borderRadius: 8,
          background: "#fff",
          overflow: "hidden",
        }}
      >
        {!selected ? (
          <div style={{ padding: 24, color: "#aaa", fontSize: 13 }}>
            从左侧选择一个输出件查看
          </div>
        ) : (
          <>
            <div
              style={{
                display: "flex",
                gap: 4,
                padding: "8px 12px",
                borderBottom: "1px solid #eef0f2",
              }}
            >
              <Tab on={view === "html"} onClick={() => setView("html")}>
                HTML 预览
              </Tab>
              <Tab on={view === "md"} onClick={() => setView("md")}>
                Markdown
              </Tab>
            </div>
            <div style={{ flex: 1, overflow: "auto" }}>
              {view === "html" ? (
                <iframe
                  title="preview"
                  srcDoc={html}
                  style={{ width: "100%", height: "100%", border: "none" }}
                />
              ) : (
                <pre
                  className="selectable"
                  style={{
                    margin: 0,
                    padding: 16,
                    fontSize: 12,
                    fontFamily: "Consolas, monospace",
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-word",
                    color: "#222",
                  }}
                >
                  {md}
                </pre>
              )}
            </div>
          </>
        )}
      </div>
      </div>
    </div>
  );
}

function Tab({
  on,
  onClick,
  children,
}: {
  on: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        fontSize: 12,
        padding: "4px 12px",
        borderRadius: 4,
        border: "none",
        cursor: "pointer",
        background: on ? "#008c64" : "#f0f1f3",
        color: on ? "#fff" : "#555",
      }}
    >
      {children}
    </button>
  );
}
