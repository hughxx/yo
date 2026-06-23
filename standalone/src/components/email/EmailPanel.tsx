"use client";

import { useEffect, useMemo, useState } from "react";
import { open } from "@tauri-apps/plugin-dialog";

import { invoke, isTauri } from "@/lib/tauri";
import type { EmailSummary } from "@/lib/types";
import { useAppStore } from "@/store/app";
import { useSettings } from "@/store/settings";
import LogPanel from "@/components/common/LogPanel";
import RulesEditor from "./RulesEditor";
import FolderPane from "./FolderPane";
import s from "./EmailPanel.module.scss";

type Filter = "all" | "matched";

export default function EmailPanel() {
  const [emails, setEmails] = useState<EmailSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [monitoring, setMonitoring] = useState(false);
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [showRules, setShowRules] = useState(false);
  const [importedCount, setImportedCount] = useState(0);
  const [folderRefresh, setFolderRefresh] = useState(0);
  const [intervalMin, setIntervalMin] = useState(60);
  const [showTimerDialog, setShowTimerDialog] = useState(false);

  const appendLog = useAppStore((st) => st.appendLog);
  const { settings, loaded, load, patch, save } = useSettings();

  useEffect(() => {
    if (!loaded) load();
    syncMonitor();
    refreshImported();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (loaded) {
      setIntervalMin(settings.scan_interval_minutes || 60);
      loadScope();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loaded, JSON.stringify(settings.scan_folders)]);

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    return emails.filter((e) => {
      if (filter === "matched" && !e.matched) return false;
      if (q) {
        const hay = `${e.subject} ${e.sender_name} ${e.sender_email} ${e.conversation_topic}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [emails, filter, search]);

  const matchedCount = useMemo(() => emails.filter((e) => e.matched).length, [emails]);
  const selectable = useMemo(() => visible.filter((e) => !e.processed), [visible]);
  const allChecked = selectable.length > 0 && selectable.every((e) => checked.has(e.item_id));

  async function syncMonitor() {
    try {
      setMonitoring(await invoke<boolean>("email_monitor_running"));
    } catch {
      /* ignore */
    }
  }
  async function refreshImported() {
    try {
      const list = await invoke<EmailSummary[]>("list_imported_msgs");
      setImportedCount((list ?? []).length);
    } catch {
      /* ignore */
    }
  }

  async function loadScope() {
    setLoading(true);
    setChecked(new Set());
    try {
      setEmails((await invoke<EmailSummary[]>("email_list_scope")) ?? []);
    } catch (e) {
      appendLog(`加载失败: ${e}`);
      setEmails([]);
    } finally {
      setLoading(false);
    }
  }

  function guardOutput(): boolean {
    if (!settings.output_dir) {
      appendLog("请先在「设置」里配置输出目录");
      return false;
    }
    return true;
  }

  // ── 处理选中（= 立即处理）：Outlook 行按 EntryID，msg 行按源路径 ──
  async function processChecked() {
    if (!guardOutput()) return;
    const rows = visible.filter((e) => checked.has(e.item_id));
    if (rows.length === 0) return;
    const ids = rows.filter((r) => !r.source_path).map((r) => r.item_id);
    const paths = rows.filter((r) => r.source_path).map((r) => r.source_path);
    setBusy(true);
    try {
      let saved = 0;
      if (ids.length) saved += await invoke<number>("process_selected", { itemIds: ids });
      if (paths.length) saved += await invoke<number>("reexport_msgs", { paths });
      appendLog(`处理选中完成，导出 ${saved} 封`);
      await loadScope();
    } catch (e) {
      appendLog(`处理选中失败: ${e}`);
    } finally {
      setBusy(false);
    }
  }

  // ── 定时 ──
  async function stopTimer() {
    try {
      await invoke("email_monitor_stop");
      setMonitoring(false);
    } catch (e) {
      appendLog(`停止定时失败: ${e}`);
    }
  }
  function openTimerDialog() {
    if (!guardOutput()) return;
    setIntervalMin(settings.scan_interval_minutes || 60);
    setShowTimerDialog(true);
  }
  async function startTimer() {
    if (settings.scan_folders.length === 0) {
      appendLog("请先在左侧勾选要处理的文件夹");
      return;
    }
    if (settings.email_rules.filter((r) => r.enabled).length === 0) {
      appendLog("没有启用的规则");
      return;
    }
    try {
      const mins = Math.max(1, intervalMin || 60);
      const enabledIds = settings.email_rules.filter((r) => r.enabled).map((r) => r.id);
      patch({
        scan_interval_minutes: mins,
        last_timer_interval: mins,
        last_timer_rules: enabledIds,
      });
      await save();
      await invoke("email_monitor_start");
      setMonitoring(true);
      setShowTimerDialog(false);
    } catch (e) {
      appendLog(`启动定时失败: ${e}`);
    }
  }
  function copyLastTimerConfig() {
    setIntervalMin(settings.last_timer_interval || 60);
    const ids = new Set(settings.last_timer_rules);
    patch({
      email_rules: settings.email_rules.map((r) => ({ ...r, enabled: ids.has(r.id) })),
    });
    save();
  }

  // ── 导入（FolderPane 触发） ──
  async function importMsg() {
    if (!isTauri() || !guardOutput()) return;
    const picked = await open({ multiple: true, filters: [{ name: "Outlook 邮件", extensions: ["msg"] }] });
    const paths = Array.isArray(picked) ? picked : picked ? [picked] : [];
    if (paths.length === 0) return;
    setBusy(true);
    try {
      const saved = await invoke<number>("import_msg", { paths });
      appendLog(`导入 .msg 完成，导出 ${saved} 封`);
      await refreshImported();
      await loadScope();
    } catch (e) {
      appendLog(`导入 .msg 失败: ${e}`);
    } finally {
      setBusy(false);
    }
  }
  async function importPst() {
    if (!isTauri()) return;
    const picked = await open({ multiple: false, filters: [{ name: "PST 文件", extensions: ["pst"] }] });
    if (typeof picked !== "string") return;
    try {
      const name = await invoke<string>("import_pst", { path: picked });
      appendLog(name ? `PST 已挂载：${name}` : "PST 已挂载（或此前已挂载）");
      setFolderRefresh((n) => n + 1);
    } catch (e) {
      appendLog(`挂载 PST 失败: ${e}`);
    }
  }

  function toggleCheck(e: EmailSummary) {
    if (e.processed) return;
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(e.item_id)) next.delete(e.item_id);
      else next.add(e.item_id);
      return next;
    });
  }
  function toggleAll() {
    setChecked(allChecked ? new Set() : new Set(selectable.map((e) => e.item_id)));
  }

  return (
    <div className={s.page}>
      <FolderPane
        importedCount={importedCount}
        refreshSignal={folderRefresh}
        onScopeChange={loadScope}
        onImportMsg={importMsg}
        onImportPst={importPst}
      />

      <div className={s.right}>
        {/* 单行工具栏：筛选 + 规则 + 刷新 + 搜索（左）… 启动定时 + 处理选中（右） */}
        <div className={`${s.toolbar} ${s.tableControls}`}>
          <div className={s.segment}>
            <button className={filter === "all" ? s.on : ""} onClick={() => setFilter("all")}>
              全部 ({emails.length})
            </button>
            <button className={filter === "matched" ? s.on : ""} onClick={() => setFilter("matched")}>
              按规则匹配 ({matchedCount})
            </button>
          </div>
          <button
            className={s.btn}
            onClick={() => setShowRules((v) => !v)}
            style={showRules ? { borderColor: "#008c64", color: "#008c64" } : undefined}
          >
            规则 ({settings.email_rules.length}) {showRules ? "▴" : "▾"}
          </button>
          <button className={s.btn} onClick={loadScope} disabled={loading || busy}>
            {loading ? "读取中…" : "刷新"}
          </button>
          <input
            className={s.search}
            value={search}
            placeholder="🔍 搜索主题/发件人…"
            onChange={(e) => setSearch(e.target.value)}
          />
          <div className={s.spacer} />
          {monitoring ? (
            <button className={s.btnToggle} style={{ background: "#b71c1c" }} onClick={stopTimer}>
              停止定时
            </button>
          ) : (
            <button className={s.btnToggle} style={{ background: "#008c64" }} onClick={openTimerDialog}>
              启动定时
            </button>
          )}
          <button
            className={`${s.btn} ${s.btnPrimary}`}
            onClick={processChecked}
            disabled={busy || checked.size === 0}
          >
            处理选中 ({checked.size})
          </button>
        </div>

        {showRules && <RulesEditor onSaved={() => loadScope()} />}

        {/* 列表：表头常驻 */}
        <div className={s.tableWrap}>
          <table className={s.table}>
            <thead>
              <tr>
                <th className={s.ckcol}>
                  <input type="checkbox" checked={allChecked} onChange={toggleAll} title="全选（仅未导出）" />
                </th>
                <th style={{ width: 140 }}>时间</th>
                <th style={{ width: 120 }}>发件人</th>
                <th>主题</th>
                <th>会话主题</th>
                <th style={{ width: 70 }}>状态</th>
              </tr>
            </thead>
            <tbody>
              {visible.length === 0 ? (
                <tr>
                  <td colSpan={6} className={s.empty}>
                    {loading ? "读取中…" : "左侧勾选文件夹以载入邮件（不选 = 空）。"}
                  </td>
                </tr>
              ) : (
                visible.map((e) => (
                  <tr
                    key={e.item_id}
                    className={`${checked.has(e.item_id) ? s.sel : ""} ${e.processed ? s.done : ""}`}
                  >
                    <td className={s.ckcol}>
                      <input
                        type="checkbox"
                        checked={checked.has(e.item_id)}
                        disabled={e.processed}
                        onChange={() => toggleCheck(e)}
                        title={e.processed ? "已导出（删除本地输出件后可重导）" : ""}
                      />
                    </td>
                    <td>{e.received_time.replace("T", " ")}</td>
                    <td title={e.sender_email}>{e.sender_name}</td>
                    <td title={e.subject}>{e.subject}</td>
                    <td title={e.conversation_topic} style={{ color: "#999" }}>
                      {e.conversation_topic}
                    </td>
                    <td>
                      {e.processed ? (
                        <span className={s.doneTag}>已导出</span>
                      ) : e.matched ? (
                        <span className={s.badge}>匹配</span>
                      ) : (
                        <span className={s.badgeMuted}>—</span>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        <LogPanel height={130} />
      </div>

      {/* 启动定时弹窗：规则 + 间隔 + 复制上次配置 */}
      {showTimerDialog && (
        <div className={s.overlay} onClick={() => setShowTimerDialog(false)}>
          <div
            className={s.dialog}
            style={{ width: 560, maxHeight: "80vh", display: "flex", flexDirection: "column" }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className={s.dialogTitle}>启动定时处理（后台批量）</div>
            <div style={{ fontSize: 12, color: "#666", marginBottom: 10 }}>
              范围 = 左侧勾选的 {settings.scan_folders.length} 个文件夹；按下方启用的规则匹配并导出。
            </div>
            <div className={s.dialogBody} style={{ marginBottom: 10 }}>
              <span>每</span>
              <input
                type="number"
                min={1}
                value={intervalMin}
                onChange={(e) => setIntervalMin(Number(e.target.value) || 1)}
                className={s.dialogInput}
              />
              <span>分钟自动处理一次</span>
              <button className={s.btn} onClick={copyLastTimerConfig} style={{ marginLeft: "auto" }}>
                复制上次定时配置
              </button>
            </div>
            <div style={{ flex: 1, overflow: "auto" }}>
              <RulesEditor onSaved={() => loadScope()} />
            </div>
            <div className={s.dialogActions} style={{ marginTop: 12 }}>
              <button className={s.btn} onClick={() => setShowTimerDialog(false)}>
                取消
              </button>
              <button className={`${s.btn} ${s.btnPrimary}`} onClick={startTimer}>
                启动定时
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
