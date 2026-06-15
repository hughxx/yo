"use client";

import { useEffect, useState } from "react";
import { open } from "@tauri-apps/plugin-dialog";

import { invoke, isTauri } from "@/lib/tauri";
import type { EmailSummary, ScanReport } from "@/lib/types";
import { useAppStore } from "@/store/app";
import { useSettings } from "@/store/settings";
import LogPanel from "@/components/common/LogPanel";
import s from "./EmailPanel.module.scss";

export default function EmailPanel() {
  const [emails, setEmails] = useState<EmailSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [report, setReport] = useState<ScanReport | null>(null);
  const [processed, setProcessed] = useState(0);

  const appendLog = useAppStore((s) => s.appendLog);
  const { settings, loaded, load } = useSettings();

  useEffect(() => {
    if (!loaded) load();
    refreshProcessed();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function refreshProcessed() {
    try {
      setProcessed(await invoke<number>("processed_count"));
    } catch {
      /* ignore */
    }
  }

  async function refreshList() {
    setLoading(true);
    try {
      const list = await invoke<EmailSummary[]>("email_list");
      setEmails(list ?? []);
    } catch (e) {
      appendLog(`刷新列表失败: ${e}`);
    } finally {
      setLoading(false);
    }
  }

  async function scanNow() {
    if (!settings.output_dir) {
      appendLog("请先在「设置」里配置输出目录");
      return;
    }
    if (settings.email_rules.filter((r) => r.enabled).length === 0) {
      appendLog("没有启用的规则，请先在「设置」里添加规则");
      return;
    }
    setScanning(true);
    setReport(null);
    try {
      const r = await invoke<ScanReport>("email_scan");
      setReport(r);
      await refreshProcessed();
    } catch (e) {
      appendLog(`抓取失败: ${e}`);
    } finally {
      setScanning(false);
    }
  }

  async function importMsg() {
    if (!isTauri()) return;
    const picked = await open({
      multiple: true,
      filters: [{ name: "Outlook 邮件", extensions: ["msg"] }],
    });
    const paths = Array.isArray(picked) ? picked : picked ? [picked] : [];
    if (paths.length === 0) return;
    if (!settings.output_dir) {
      appendLog("请先在「设置」里配置输出目录");
      return;
    }
    setScanning(true);
    try {
      const saved = await invoke<number>("import_msg", { paths });
      appendLog(`导入 .msg 完成，保存 ${saved} 封`);
      await refreshProcessed();
    } catch (e) {
      appendLog(`导入 .msg 失败: ${e}`);
    } finally {
      setScanning(false);
    }
  }

  async function importPst() {
    if (!isTauri()) return;
    const picked = await open({
      multiple: false,
      filters: [{ name: "PST 文件", extensions: ["pst"] }],
    });
    if (typeof picked !== "string") return;
    try {
      const name = await invoke<string>("import_pst", { path: picked });
      appendLog(
        name
          ? `PST 已挂载为 store：${name}（可在设置里将其文件夹加入扫描范围）`
          : "PST 已挂载（或此前已挂载）"
      );
      await refreshList();
    } catch (e) {
      appendLog(`挂载 PST 失败: ${e}`);
    }
  }

  async function clearProcessed() {
    try {
      await invoke("clear_processed");
      await refreshProcessed();
      appendLog("已清空「已处理」记录，下次抓取将重新导出");
    } catch (e) {
      appendLog(`清空失败: ${e}`);
    }
  }

  const busy = loading || scanning;

  return (
    <div className={s.wrap}>
      <div className={s.toolbar}>
        <button className={s.btn} onClick={refreshList} disabled={busy}>
          {loading ? "读取中…" : "刷新列表"}
        </button>
        <button
          className={`${s.btn} ${s.btnPrimary}`}
          onClick={scanNow}
          disabled={busy}
        >
          {scanning ? "抓取中…" : "立即抓取"}
        </button>
        <button className={s.btn} onClick={importMsg} disabled={busy}>
          导入 .msg
        </button>
        <button className={s.btn} onClick={importPst} disabled={busy}>
          导入 .pst
        </button>
        <div className={s.spacer} />
        <span className={s.meta}>已处理 {processed} 条</span>
        <button className={s.linkBtn} onClick={clearProcessed}>
          清空记录
        </button>
      </div>

      {report && (
        <div className={s.report}>
          扫描 {report.scanned} · 匹配 {report.matched} · 保存 {report.saved} ·
          跳过 {report.skipped} · 失败 {report.failed}
        </div>
      )}

      <div className={s.tableWrap}>
        {emails.length === 0 ? (
          <div className={s.empty}>
            {loading ? "读取中…" : "点击「刷新列表」读取本地 Outlook 邮件"}
          </div>
        ) : (
          <table className={s.table}>
            <thead>
              <tr>
                <th style={{ width: 150 }}>时间</th>
                <th style={{ width: 160 }}>发件人</th>
                <th>主题</th>
              </tr>
            </thead>
            <tbody>
              {emails.map((e) => (
                <tr key={e.item_id}>
                  <td>{e.received_time.replace("T", " ")}</td>
                  <td title={e.sender_email}>{e.sender_name}</td>
                  <td title={e.subject}>{e.subject}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <LogPanel />
    </div>
  );
}
