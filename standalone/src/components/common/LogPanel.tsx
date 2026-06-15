"use client";

import { useEffect, useRef } from "react";

import { useAppStore } from "@/store/app";

/** 黑底运行日志面板（邮件 / WeLink 共用）。 */
export default function LogPanel({ height = 180 }: { height?: number }) {
  const logs = useAppStore((s) => s.logs);
  const clearLogs = useAppStore((s) => s.clearLogs);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = boxRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [logs]);

  return (
    <div style={{ marginTop: 10 }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 4,
        }}
      >
        <span style={{ fontSize: 12, color: "#555" }}>运行日志</span>
        <button
          onClick={clearLogs}
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
      <div
        ref={boxRef}
        className="selectable"
        style={{
          height,
          overflow: "auto",
          background: "#1e1e1e",
          color: "#d4d4d4",
          fontFamily: "Consolas, monospace",
          fontSize: 11,
          lineHeight: 1.6,
          padding: "8px 10px",
          borderRadius: 6,
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
    </div>
  );
}
