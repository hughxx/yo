"use client";

import { useEffect, useState } from "react";

import { invoke } from "@/lib/tauri";
import type { WelinkGroup } from "@/lib/types";
import { uid } from "@/lib/util";
import { useAppStore } from "@/store/app";
import { useSettings } from "@/store/settings";
import LogPanel from "@/components/common/LogPanel";
import ManualImport from "./ManualImport";
import HelpTip from "./HelpTip";
import { RangeHelp, SummaryHelp } from "./RecordSchematic";
import s from "./WelinkPanel.module.scss";

type Sub = "command" | "collect" | "manual";

const SUBS: { key: Sub; label: string }[] = [
  { key: "command", label: "命令触发" },
  { key: "collect", label: "自动收集" },
  { key: "manual", label: "手动导入" },
];

export default function WelinkPanel() {
  const [sub, setSub] = useState<Sub>("command");
  const { loaded, load } = useSettings();

  useEffect(() => {
    if (!loaded) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className={s.wrap}>
      <div className={s.tabs}>
        {SUBS.map((t) => (
          <div
            key={t.key}
            className={`${s.tab} ${sub === t.key ? s.active : ""}`}
            onClick={() => setSub(t.key)}
          >
            {t.label}
          </div>
        ))}
      </div>

      <div className={s.tabContent}>
        {sub === "command" && <CommandTab />}
        {sub === "collect" && <CollectTab />}
        {sub === "manual" && <ManualImport />}

        {/* 运行日志：两个后台共用，随整页滚动、默认展开 */}
        <LogPanel defaultOpen grow height={220} />
      </div>
    </div>
  );
}

// ── 群编辑器（命令触发 / 自动收集 共用） ─────────────────────

function GroupEditor({
  title,
  groups,
  onChange,
}: {
  title: string;
  groups: WelinkGroup[];
  onChange: (next: WelinkGroup[]) => void;
}) {
  return (
    <div className={s.config}>
      <div className={s.head}>
        <span className={s.title}>{title}</span>
        <div className={s.spacer} />
        <button
          className={s.btn}
          onClick={() => onChange([...groups, { id: uid(), group_id: "", group_name: "", enabled: true }])}
        >
          + 新增群
        </button>
      </div>
      {groups.length === 0 && <div className={s.usage} style={{ marginLeft: 0 }}>尚未添加群，点右上「+ 新增群」。</div>}
      {groups.map((g) => (
        <div className={s.groupRow} key={g.id} style={{ marginLeft: 0 }}>
          <input
            className={s.input}
            value={g.group_id}
            placeholder="群组 ID"
            onChange={(e) => onChange(groups.map((x) => (x.id === g.id ? { ...x, group_id: e.target.value } : x)))}
          />
          <input
            className={s.input}
            value={g.group_name}
            placeholder="群组名称"
            onChange={(e) => onChange(groups.map((x) => (x.id === g.id ? { ...x, group_name: e.target.value } : x)))}
          />
          <input
            type="checkbox"
            checked={g.enabled}
            title="启用"
            onChange={(e) => onChange(groups.map((x) => (x.id === g.id ? { ...x, enabled: e.target.checked } : x)))}
          />
          <button className={`${s.btn} ${s.btnDanger}`} onClick={() => onChange(groups.filter((x) => x.id !== g.id))}>
            ×
          </button>
        </div>
      ))}
    </div>
  );
}

// ── 后台状态条（开关 + 状态点） ─────────────────────────────

function MonitorHead({
  title,
  hint,
  running,
  busy,
  onToggle,
}: {
  title: string;
  hint: string;
  running: boolean;
  busy: boolean;
  onToggle: () => void;
}) {
  return (
    <div className={s.groupHead}>
      <span className={s.groupTitle}>{title}</span>
      <span className={s.groupHint}>{hint}</span>
      <div className={s.spacer} style={{ flex: 1 }} />
      <span className={s.dot} style={{ color: running ? "#008c64" : "#ccc", fontSize: 14 }}>
        ●
      </span>
      <span className={s.statusText} style={{ color: running ? "#008c64" : "#888", fontSize: 13, fontWeight: 600 }}>
        {running ? "运行中" : "未运行"}
      </span>
      <button
        className={s.btnToggle}
        style={{ background: running ? "#b71c1c" : "#008c64" }}
        onClick={onToggle}
        disabled={busy}
      >
        {running ? "停止" : "启动"}
      </button>
    </div>
  );
}

// ── 命令触发 tab ────────────────────────────────────────────

function CommandTab() {
  const [running, setRunning] = useState(false);
  const [busy, setBusy] = useState(false);
  const [showStart, setShowStart] = useState(false);
  const [pollInput, setPollInput] = useState(8);
  const appendLog = useAppStore((st) => st.appendLog);
  const { settings, patch, save } = useSettings();

  useEffect(() => {
    invoke<boolean>("welink_running").then(setRunning).catch(() => {});
  }, []);

  function onToggle() {
    if (running) {
      void stop();
    } else {
      if (settings.welink_groups.filter((g) => g.enabled).length === 0) {
        appendLog("没有启用的监听群，请先在下方添加");
        return;
      }
      setPollInput(settings.welink_poll_interval || 8);
      setShowStart(true);
    }
  }
  async function stop() {
    setBusy(true);
    try {
      await invoke("welink_stop");
      setRunning(false);
    } catch (e) {
      appendLog(`停止失败: ${e}`);
    } finally {
      setBusy(false);
    }
  }
  async function start() {
    setBusy(true);
    try {
      patch({ welink_poll_interval: Math.max(1, pollInput || 8) });
      await save();
      await invoke("welink_start");
      setRunning(true);
      setShowStart(false);
    } catch (e) {
      appendLog(`启动失败: ${e}`);
    } finally {
      setBusy(false);
    }
  }

  const set = <K extends keyof typeof settings>(k: K, v: (typeof settings)[K]) => {
    patch({ [k]: v } as never);
    save();
  };
  const setGroups = (next: WelinkGroup[]) => {
    patch({ welink_groups: next });
    save();
  };

  return (
    <>
      <MonitorHead
        title="命令触发"
        hint="在群里发命令即时录制 / 归档，需启动监听"
        running={running}
        busy={busy}
        onToggle={onToggle}
      />

      <GroupEditor title="监听群" groups={settings.welink_groups} onChange={setGroups} />

      <div className={s.config}>
        {/* 录制 */}
        <div style={{ marginBottom: 16 }}>
          <div className={s.subTitle}>
            录制
            <HelpTip>
              <RangeHelp />
            </HelpTip>
          </div>
          <div className={s.field}>
            <label>开始命令</label>
            <input className={s.input} value={settings.welink_start_cmd} onChange={(e) => set("welink_start_cmd", e.target.value)} />
          </div>
          <div className={s.field}>
            <label>结束命令</label>
            <input className={s.input} value={settings.welink_end_cmd} onChange={(e) => set("welink_end_cmd", e.target.value)} />
          </div>
        </div>

        {/* 归档 */}
        <div>
          <div className={s.subTitle}>
            归档
            <HelpTip>
              <SummaryHelp />
            </HelpTip>
          </div>
          <div className={s.field}>
            <label>归档命令</label>
            <input className={s.input} value={settings.welink_summary_cmd} onChange={(e) => set("welink_summary_cmd", e.target.value)} />
          </div>
        </div>
      </div>

      {showStart && (
        <StartDialog
          label="秒轮询一次群消息"
          value={pollInput}
          onChange={setPollInput}
          onCancel={() => setShowStart(false)}
          onConfirm={start}
          busy={busy}
        />
      )}
    </>
  );
}

// ── 自动收集 tab ────────────────────────────────────────────

function CollectTab() {
  const [running, setRunning] = useState(false);
  const [busy, setBusy] = useState(false);
  const appendLog = useAppStore((st) => st.appendLog);
  const { settings, patch, save } = useSettings();

  useEffect(() => {
    invoke<boolean>("collect_running").then(setRunning).catch(() => {});
  }, []);

  const set = <K extends keyof typeof settings>(k: K, v: (typeof settings)[K]) => {
    patch({ [k]: v } as never);
    save();
  };
  const setGroups = (next: WelinkGroup[]) => {
    patch({ collect_groups: next });
    save();
  };

  async function onToggle() {
    if (running) {
      setBusy(true);
      try {
        await invoke("collect_stop");
        setRunning(false);
      } catch (e) {
        appendLog(`停止失败: ${e}`);
      } finally {
        setBusy(false);
      }
      return;
    }
    if (settings.collect_groups.filter((g) => g.enabled).length === 0) {
      appendLog("没有启用的收集群，请先在下方添加");
      return;
    }
    if (!settings.collect_periodic_enabled && !settings.collect_daily_enabled) {
      appendLog("请至少开启「周期收集」或「每日定时」之一");
      return;
    }
    setBusy(true);
    try {
      await save();
      await invoke("collect_start");
      setRunning(true);
    } catch (e) {
      appendLog(`启动失败: ${e}`);
    } finally {
      setBusy(false);
    }
  }

  // 多个定时点编辑
  const times = settings.collect_daily_times;
  const setTime = (i: number, v: string) => set("collect_daily_times", times.map((t, k) => (k === i ? v : t)));
  const addTime = () => set("collect_daily_times", [...times, "12:00"]);
  const delTime = (i: number) => set("collect_daily_times", times.filter((_, k) => k !== i));

  return (
    <>
      <MonitorHead
        title="自动收集"
        hint="无需命令，到点/到周期自动归档新消息（独立后台）"
        running={running}
        busy={busy}
        onToggle={onToggle}
      />

      <GroupEditor title="收集群" groups={settings.collect_groups} onChange={setGroups} />

      {/* 周期收集 */}
      <div className={s.config}>
        <div className={s.field} style={{ marginBottom: 0 }}>
          <input
            type="checkbox"
            checked={settings.collect_periodic_enabled}
            onChange={(e) => set("collect_periodic_enabled", e.target.checked)}
          />
          <span className={s.subTitle} style={{ margin: 0 }}>周期收集</span>
          <span className={s.hint}>每隔</span>
          <input
            className={s.num}
            type="number"
            min={1}
            value={settings.collect_period_hours}
            onChange={(e) => set("collect_period_hours", Math.max(1, Number(e.target.value) || 1))}
          />
          <span className={s.hint}>小时，自动收集各群的新消息</span>
        </div>
      </div>

      {/* 每日定时（可多个时间点） */}
      <div className={s.config}>
        <div className={s.field} style={{ marginBottom: times.length ? 12 : 0 }}>
          <input
            type="checkbox"
            checked={settings.collect_daily_enabled}
            onChange={(e) => set("collect_daily_enabled", e.target.checked)}
          />
          <span className={s.subTitle} style={{ margin: 0 }}>每日定时</span>
          <span className={s.hint}>每天到达下列时间点各收集一次</span>
          <div className={s.spacer} style={{ flex: 1 }} />
          <button className={s.btn} onClick={addTime}>+ 时间点</button>
        </div>
        {settings.collect_daily_enabled && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginLeft: 26 }}>
            {times.map((t, i) => (
              <span key={i} style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                <input className={s.num} type="time" value={t} onChange={(e) => setTime(i, e.target.value)} />
                <button className={`${s.btn} ${s.btnDanger}`} style={{ padding: "0 8px" }} onClick={() => delTime(i)}>
                  ×
                </button>
              </span>
            ))}
            {times.length === 0 && <span className={s.hint}>点「+ 时间点」添加，如 09:00。</span>}
          </div>
        )}
      </div>

      {/* 时间段限定 */}
      <div className={s.config}>
        <div className={s.field} style={{ marginBottom: 0 }}>
          <input
            type="checkbox"
            checked={settings.collect_window_enabled}
            onChange={(e) => set("collect_window_enabled", e.target.checked)}
          />
          <span className={s.subTitle} style={{ margin: 0 }}>时间段限定</span>
          <span className={s.hint}>仅收集落在</span>
          <input
            className={s.num}
            type="time"
            value={settings.collect_window_start}
            onChange={(e) => set("collect_window_start", e.target.value)}
          />
          <span className={s.hint}>—</span>
          <input
            className={s.num}
            type="time"
            value={settings.collect_window_end}
            onChange={(e) => set("collect_window_end", e.target.value)}
          />
          <span className={s.hint}>之间的消息（跨午夜亦可）</span>
        </div>
      </div>
    </>
  );
}

// ── 启动弹窗（命令触发用） ──────────────────────────────────

function StartDialog({
  label,
  value,
  onChange,
  onCancel,
  onConfirm,
  busy,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  onCancel: () => void;
  onConfirm: () => void;
  busy: boolean;
}) {
  return (
    <div
      onClick={onCancel}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 100,
        background: "rgba(0,0,0,0.28)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{ width: 380, background: "#fff", borderRadius: 10, boxShadow: "0 12px 40px rgba(0,0,0,0.25)", padding: "18px 20px" }}
      >
        <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 14 }}>启动监听</div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "#555", marginBottom: 18 }}>
          <span>每</span>
          <input
            type="number"
            min={1}
            autoFocus
            value={value}
            onChange={(e) => onChange(Number(e.target.value) || 1)}
            onKeyDown={(e) => {
              if (e.key === "Enter") onConfirm();
            }}
            style={{ width: 72, height: 32, padding: "0 8px", border: "1px solid #d4d7dd", borderRadius: 4, fontSize: 14 }}
          />
          <span>{label}</span>
        </div>
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
          <button className={s.btn} onClick={onCancel}>
            取消
          </button>
          <button className={`${s.btn} ${s.btnPrimary}`} onClick={onConfirm} disabled={busy}>
            启动
          </button>
        </div>
      </div>
    </div>
  );
}
