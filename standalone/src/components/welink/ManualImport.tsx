"use client";

import { useState } from "react";
import { open } from "@tauri-apps/plugin-dialog";

import { invoke, isTauri } from "@/lib/tauri";
import { useAppStore } from "@/store/app";
import { useSettings } from "@/store/settings";
import HelpTip from "./HelpTip";
import s from "./WelinkPanel.module.scss";

export default function ManualImport() {
  const [zipPath, setZipPath] = useState("");
  const [busy, setBusy] = useState(false);
  const appendLog = useAppStore((st) => st.appendLog);
  const { settings } = useSettings();

  async function pick() {
    if (!isTauri()) return;
    const p = await open({
      multiple: false,
      filters: [{ name: "聊天记录压缩包", extensions: ["zip"] }],
    });
    if (typeof p === "string") setZipPath(p);
  }

  async function doImport() {
    if (!zipPath) {
      appendLog("请先选择 zip 文件");
      return;
    }
    if (!settings.output_dir) {
      appendLog("请先在「设置」里配置输出目录");
      return;
    }
    setBusy(true);
    try {
      const base = await invoke<string>("import_chatlog", { zipPath, groupName: "" });
      appendLog(base ? `导入完成: ${base}` : "该记录已存在，跳过");
    } catch (e) {
      appendLog(`导入失败: ${e}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={s.config}>
      <div className={s.head}>
        <span className={s.title}>手动导入</span>
        <HelpTip>
          <div style={{ display: "flex", gap: 12 }}>
            <ExportStep />
            <ZipStep />
          </div>
        </HelpTip>
      </div>
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <input
          className={s.input}
          style={{ flex: 1 }}
          value={zipPath}
          readOnly
          placeholder="选择 WeLink 导出聊天记录打成的 zip"
        />
        <button className={s.btn} onClick={pick}>
          选择 zip
        </button>
        <button className={`${s.btn} ${s.btnPrimary}`} onClick={doImport} disabled={busy}>
          {busy ? "导入中…" : "开始导入"}
        </button>
      </div>
    </div>
  );
}

const card: React.CSSProperties = {
  flex: "1 1 260px",
  minWidth: 0,
  display: "flex",
  flexDirection: "column",
  border: "1px solid #e3e5e9",
  borderRadius: 8,
  background: "#fafbfc",
  padding: "12px 14px",
};
const stepTitle: React.CSSProperties = { fontSize: 12.5, fontWeight: 600, color: "#444", marginBottom: 10 };
const note: React.CSSProperties = { fontSize: 11, color: "#888", marginTop: 8, lineHeight: 1.6 };

// ① 在聊天软件里：会话列表 → 右键某个联系人 → 倒数第三个「聊天记录」
function ExportStep() {
  const dimItem = (k: number) => (
    <div key={k} style={{ height: 7, margin: "7px 8px", borderRadius: 4, background: "#e6e9ed" }} />
  );
  const convo = (name: string, active = false) => (
    <div
      style={{
        display: "flex",
        gap: 8,
        alignItems: "center",
        padding: "6px 8px",
        borderRadius: 4,
        background: active ? "#eef7f3" : "transparent",
      }}
    >
      <div style={{ width: 28, height: 28, borderRadius: "50%", background: "#dfe3e8", flexShrink: 0 }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: "#333" }}>{name}</div>
        <div style={{ height: 6, width: 110, borderRadius: 3, background: "#e6e9ed", marginTop: 5 }} />
      </div>
    </div>
  );
  return (
    <div style={card}>
      <div style={stepTitle}>① 在 WeLink 中导出聊天记录</div>
      {/* 会话列表 + 右键菜单浮在其上（容器留够高度，不盖下面的说明） */}
      <div
        style={{
          position: "relative",
          flex: 1,
          minHeight: 148,
          border: "1px solid #eef0f2",
          borderRadius: 6,
          background: "#fff",
          padding: 4,
        }}
      >
        {convo("某群 A", true)}
        {convo("联系人 B")}
        {convo("某群 C")}
        <div
          style={{
            position: "absolute",
            left: 150,
            top: 6,
            width: 104,
            border: "1px solid #e3e5e9",
            borderRadius: 6,
            background: "#fff",
            padding: 4,
            boxShadow: "0 6px 20px rgba(0,0,0,0.16)",
          }}
        >
          {[0, 1, 2].map(dimItem)}
          <div
            style={{
              fontSize: 11,
              color: "#fff",
              background: "#008c64",
              borderRadius: 4,
              padding: "3px 6px",
              textAlign: "center",
            }}
          >
            聊天记录
          </div>
          {[3, 4].map(dimItem)}
        </div>
      </div>
      <div style={note}>
        在<b>某个联系人/会话上右键</b>，选<b>「聊天记录」</b>，导出得到一个 HistoryRecord 文件夹。
      </div>
    </div>
  );
}

// ② 打成 zip 再导入
function ZipStep() {
  return (
    <div style={card}>
      <div style={stepTitle}>② 打包为 zip 包</div>
      <div
        style={{
          flex: 1,
          fontFamily: "Consolas, monospace",
          fontSize: 11,
          color: "#444",
          lineHeight: 1.9,
          background: "#fff",
          border: "1px solid #eef0f2",
          borderRadius: 6,
          padding: "8px 10px",
        }}
      >
        📦 xxx.zip
        <br />
        &nbsp;└ 📁 HistoryRecord
        <br />
        &nbsp;&nbsp;&nbsp;├ 📄 群名.txt&nbsp;&nbsp;<span style={{ color: "#aaa" }}>聊天文本（[图片] 占位）</span>
        <br />
        &nbsp;&nbsp;&nbsp;└ 📁 群名/&nbsp;&nbsp;<span style={{ color: "#aaa" }}>图片文件夹</span>
        <br />
        &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;├ 🖼 img1.png
        <br />
        &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;└ 🖼 img2.png
      </div>
      <div style={note}>
        把导出的 <b>HistoryRecord</b> 文件夹整个打成 zip，选它导入即可。
      </div>
    </div>
  );
}
