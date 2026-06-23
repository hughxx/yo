"use client";

// 抽象的骨架屏示意（不绑定用户实际命令文字）+ 用法说明，放进「?」悬浮提示里。

type Row =
  | { type: "dim"; w: number }
  | { type: "cap"; w: number }
  | { type: "cmd"; label: string; tag: string; color: string }
  | { type: "divider"; label: string };

function ChatRows({ rows }: { rows: Row[] }) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 7,
        background: "#fafbfc",
        border: "1px solid #eef0f2",
        borderRadius: 6,
        padding: "10px 12px",
      }}
    >
      {rows.map((r, i) => {
        if (r.type === "divider") {
          return (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 6, margin: "1px 0" }}>
              <div style={{ flex: 1, borderTop: "1px dashed #e0a64d" }} />
              <span style={{ fontSize: 10, color: "#d98300", whiteSpace: "nowrap" }}>{r.label}</span>
              <div style={{ flex: 1, borderTop: "1px dashed #e0a64d" }} />
            </div>
          );
        }
        const avatar = (
          <div style={{ width: 16, height: 16, borderRadius: "50%", background: "#dfe3e8", flexShrink: 0 }} />
        );
        if (r.type === "cmd") {
          return (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 7 }}>
              {avatar}
              <span
                style={{
                  fontSize: 10,
                  color: "#fff",
                  background: r.color,
                  borderRadius: 3,
                  padding: "1px 6px",
                  whiteSpace: "nowrap",
                }}
              >
                {r.tag}
              </span>
              <span style={{ fontSize: 11, color: "#666", fontStyle: "italic" }}>{r.label}</span>
            </div>
          );
        }
        const isCap = r.type === "cap";
        return (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: 7 }}>
            {avatar}
            <div
              style={{
                height: 9,
                width: r.w,
                borderRadius: 4,
                background: isCap ? "#a6dcc6" : "#e6e9ed",
                borderLeft: isCap ? "3px solid #008c64" : "none",
              }}
            />
            {isCap && <span style={{ fontSize: 10, color: "#00714f" }}>抓取</span>}
          </div>
        );
      })}
    </div>
  );
}

const usageText: React.CSSProperties = { fontSize: 11, color: "#555", marginTop: 7, lineHeight: 1.7 };

export function RangeHelp() {
  return (
    <div>
      <ChatRows
        rows={[
          { type: "dim", w: 120 },
          { type: "cmd", label: "开始命令", tag: "起点", color: "#008c64" },
          { type: "cap", w: 170 },
          { type: "cap", w: 120 },
          { type: "cap", w: 150 },
          { type: "cmd", label: "结束命令", tag: "终点", color: "#b71c1c" },
          { type: "dim", w: 100 },
        ]}
      />
      <div style={usageText}>
        在群里发「起点」「终点」两条命令，抓取它们<b>之间</b>的聊天记录。
        <br />
        命令本身不计入记录。
      </div>
    </div>
  );
}

export function SummaryHelp() {
  return (
    <div style={{ display: "flex", gap: 14, alignItems: "flex-start" }}>
      {/* 左：抓取范围示意 + 三种用法 */}
      <div style={{ flex: "1 1 0", minWidth: 0 }}>
        <ChatRows
          rows={[
            { type: "divider", label: "上次归档时间/开始时间" },
            { type: "cap", w: 130 },
            { type: "cap", w: 100 },
            { type: "cap", w: 120 },
            { type: "divider", label: "结束时间" },
            { type: "cmd", label: "归档命令", tag: "命令", color: "#008c64" },
          ]}
        />
        <div style={usageText}>
          ① <b>不带时间</b>：抓「上次归档时间 → 本条归档命令」之间的记录。
          <br />
          ② <b>带一个结束时间</b>：抓「上次归档时间 → 该结束时间」之间的记录。
          <br />
          ③ <b>带开始和结束时间</b>：直接抓「这两个时间之间」的记录。
        </div>
      </div>

      {/* 右：命令时间怎么填 */}
      <div style={{ flex: "1 1 0", minWidth: 0 }}>
        <MsgFormatHint />
      </div>
    </div>
  );
}

// 提示：命令里的时间不用手敲，直接选聊天记录里头像右边那行
function MsgFormatHint() {
  return (
    <div>
      <div style={{ fontSize: 11, color: "#555", marginBottom: 6, lineHeight: 1.7 }}>
        命令里的时间<b>不用手敲</b>：在聊天记录里<b>选中头像右边那行</b>（姓名 工号 日期 时间）粘到归档命令后面即可。
      </div>
      <div
        style={{
          display: "flex",
          gap: 8,
          alignItems: "flex-start",
          background: "#fafbfc",
          border: "1px solid #eef0f2",
          borderRadius: 6,
          padding: "10px 12px",
        }}
      >
        <div style={{ width: 28, height: 28, borderRadius: "50%", background: "#dfe3e8", flexShrink: 0 }} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
            <span
              style={{
                fontSize: 11,
                fontFamily: "Consolas, monospace",
                color: "#333",
                background: "#fff3cd",
                border: "1px solid #ffe69c",
                borderRadius: 3,
                padding: "1px 5px",
              }}
            >
              张三 00123456 2026-01-01 10:00
            </span>
          </div>
          <div style={{ height: 8, width: 150, borderRadius: 4, background: "#e6e9ed", marginTop: 7 }} />
        </div>
      </div>
    </div>
  );
}
