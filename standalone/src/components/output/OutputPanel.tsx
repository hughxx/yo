"use client";

import { useEffect, useState } from "react";

import { invoke } from "@/lib/tauri";
import type { OutputEntry } from "@/lib/types";
import { useAppStore } from "@/store/app";

export default function OutputPanel() {
  const [entries, setEntries] = useState<OutputEntry[]>([]);
  const [selected, setSelected] = useState<OutputEntry | null>(null);
  const [view, setView] = useState<"html" | "md">("html");
  const [html, setHtml] = useState("");
  const [md, setMd] = useState("");
  const appendLog = useAppStore((s) => s.appendLog);

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function refresh() {
    try {
      const list = await invoke<OutputEntry[]>("list_outputs");
      setEntries(list ?? []);
    } catch (e) {
      appendLog(`读取产物失败: ${e}`);
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
    <div style={{ display: "flex", height: "100%", gap: 12 }}>
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
          <span style={{ fontSize: 12, color: "#666" }}>
            产物（{entries.length}）
          </span>
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
              暂无产物。去「邮件 / WeLink」抓取，或检查设置里的输出目录。
            </div>
          ) : (
            entries.map((e) => (
              <div
                key={e.base_name}
                onClick={() => pick(e)}
                style={{
                  padding: "8px 12px",
                  fontSize: 12,
                  cursor: "pointer",
                  borderBottom: "1px solid #f3f4f6",
                  background:
                    selected?.base_name === e.base_name ? "#e9f7f1" : "transparent",
                  color: "#333",
                  wordBreak: "break-all",
                }}
              >
                {e.base_name}
              </div>
            ))
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
            从左侧选择一个产物查看
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
