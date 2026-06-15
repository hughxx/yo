"use client";

import { useEffect } from "react";

import { useAppStore, type TabKey } from "@/store/app";
import { listen } from "@/lib/tauri";
import EmailPanel from "@/components/email/EmailPanel";
import WelinkPanel from "@/components/welink/WelinkPanel";
import OutputPanel from "@/components/output/OutputPanel";
import SettingsPanel from "@/components/settings/SettingsPanel";
import styles from "./page.module.scss";

const TABS: { key: TabKey; label: string }[] = [
  { key: "email", label: "邮件" },
  { key: "welink", label: "WeLink" },
  { key: "output", label: "本地产物" },
  { key: "settings", label: "设置" },
];

export default function Home() {
  const tab = useAppStore((s) => s.tab);
  const setTab = useAppStore((s) => s.setTab);
  const appendLog = useAppStore((s) => s.appendLog);

  // 全局监听 Rust 端发来的运行日志
  useEffect(() => {
    const unlistenPromise = listen<string>("log", (line) => appendLog(line));
    return () => {
      unlistenPromise.then((un) => un());
    };
  }, [appendLog]);

  return (
    <div className={styles.shell}>
      <nav className={styles.tabbar}>
        {TABS.map((t) => (
          <div
            key={t.key}
            className={`${styles.tab} ${tab === t.key ? styles.active : ""}`}
            onClick={() => setTab(t.key)}
          >
            {t.label}
          </div>
        ))}
        <div className={styles.spacer} />
        <div className={styles.title}>抓取 → HTML + Markdown → 落盘</div>
      </nav>

      <main className={styles.body}>
        {tab === "email" && <EmailPanel />}
        {tab === "welink" && <WelinkPanel />}
        {tab === "output" && <OutputPanel />}
        {tab === "settings" && <SettingsPanel />}
      </main>
    </div>
  );
}
