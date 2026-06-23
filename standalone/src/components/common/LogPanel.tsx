"use client";

import { useEffect, useRef, useState } from "react";

import { useAppStore } from "@/store/app";

/** 可折叠的运行日志块（邮件 / WeLink 共用），默认收起。 */
export default function LogPanel({
  height = 180,
  defaultOpen = false,
  grow = false,
}: {
  height?: number;
  defaultOpen?: boolean;
  /** grow=true 时日志不带自己的滚动条，随内容增高、跟随外层页面一起滚动 */
  grow?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const logs = useAppStore((s) => s.logs);
  const clearLogs = useAppStore((s) => s.clearLogs);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open || grow) return;
    const el = boxRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [logs, open, grow]);

  return (
    <div
      style={{
        marginTop: 10,
        border: "1px solid #e3e5e9",
        borderRadius: 8,
        background: "#fff",
        overflow: "hidden",
      }}
    >
      <div
        onClick={() => setOpen((v) => !v)}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          padding: "8px 12px",
          cursor: "pointer",
          userSelect: "none",
        }}
      >
        <span style={{ color: "#999", fontSize: 11, width: 12 }}>{open ? "▾" : "▸"}</span>
        <span style={{ fontSize: 12, color: "#555" }}>运行日志</span>
        <span style={{ fontSize: 11, color: "#aaa" }}>（{logs.length}）</span>
        <div style={{ flex: 1 }} />
        <button
          onClick={(e) => {
            e.stopPropagation();
            clearLogs();
          }}
          style={{
            fontSize: 11,
            color: "#888",
            background: "none",
            border: "none",
            cursor: "pointer",
          }}
        >
          清空
        </button>
      </div>

      {open && (
        <div
          ref={boxRef}
          className="selectable"
          style={{
            ...(grow ? { minHeight: height } : { height, overflow: "auto" }),
            background: "#1e1e1e",
            color: "#d4d4d4",
            fontFamily: "Consolas, monospace",
            fontSize: 11,
            lineHeight: 1.6,
            padding: "8px 10px",
            whiteSpace: "pre-wrap",
            wordBreak: "break-all",
          }}
        >
          {logs.length === 0 ? (
            <span style={{ color: "#666" }}>暂无日志</span>
          ) : (
            logs.map((l, i) => <div key={i}>{l}</div>)
          )}
        </div>
      )}
    </div>
  );
}
