"use client";

import { useEffect } from "react";
import { open } from "@tauri-apps/plugin-dialog";

import { useSettings } from "@/store/settings";
import type { Settings } from "@/lib/types";
import { isTauri } from "@/lib/tauri";
import s from "./SettingsPanel.module.scss";

export default function SettingsPanel() {
  const { settings, loaded, dirty, saving, load, patch, save } = useSettings();

  useEffect(() => {
    if (!loaded) load();
  }, [loaded, load]);

  const set = <K extends keyof Settings>(k: K, v: Settings[K]) =>
    patch({ [k]: v } as Partial<Settings>);

  async function pickDir(k: "output_dir") {
    if (!isTauri()) return;
    const picked = await open({ directory: true, multiple: false });
    if (typeof picked === "string") set(k, picked);
  }

  async function pickExe(
    k: "outlook_cli_path" | "welink_cli_path" | "html2md_cli_path"
  ) {
    if (!isTauri()) return;
    const picked = await open({
      multiple: false,
      filters: [{ name: "可执行文件", extensions: ["exe"] }],
    });
    if (typeof picked === "string") set(k, picked);
  }

  return (
    <div className={s.panel}>
      {/* ── 通用 ── */}
      <section className={s.section}>
        <h3>通用</h3>
        <div className={s.field}>
          <label>输出目录</label>
          <input
            className={s.input}
            value={settings.output_dir}
            placeholder="HTML / Markdown 落盘位置"
            onChange={(e) => set("output_dir", e.target.value)}
          />
          <button className={s.btn} onClick={() => pickDir("output_dir")}>
            选择…
          </button>
        </div>
        <div className={s.field}>
          <label>标题最大长度</label>
          <input
            type="number"
            className={s.numInput}
            value={settings.title_max_len}
            min={10}
            max={240}
            onChange={(e) => set("title_max_len", Math.min(240, Number(e.target.value) || 220))}
          />
          <span className={s.hint}>文件名截断长度</span>
        </div>
        <div className={s.field}>
          <label>同名冲突</label>
          <select
            className={s.select}
            value={settings.conflict_strategy}
            onChange={(e) =>
              set("conflict_strategy", e.target.value as Settings["conflict_strategy"])
            }
          >
            <option value="suffix">追加序号 _NN</option>
            <option value="overwrite">覆盖</option>
            <option value="skip">跳过</option>
          </select>
        </div>
      </section>

      {/* ── 图片 ── */}
      <section className={s.section}>
        <h3>图片</h3>
        <TextField
          label="上传接口 URL"
          value={settings.image_upload_url}
          placeholder="留空 = 输出件不含图片；如 http://host:port/api/image/upload"
          onChange={(v) => set("image_upload_url", v)}
        />
        <TextField
          label="云盘地址"
          value={settings.clouddrive_url}
          placeholder="如 https://clouddrive.huawei.com（下载 WeLink 云盘图片用）"
          onChange={(v) => set("clouddrive_url", v)}
        />
        <TextField
          label="云盘账号"
          value={settings.clouddrive_account}
          placeholder="任意有效账号即可（登录换 token 下载）"
          onChange={(v) => set("clouddrive_account", v)}
        />
        <div className={s.field}>
          <label>云盘密码</label>
          <input
            type="password"
            className={s.input}
            value={settings.clouddrive_password}
            onChange={(e) => set("clouddrive_password", e.target.value)}
          />
        </div>
      </section>

      {/* ── 外置 CLI ── */}
      <section className={s.section}>
        <h3>外置 CLI 路径</h3>
        <div className={s.field}>
          <label>outlook_cli</label>
          <input
            className={s.input}
            value={settings.outlook_cli_path}
            placeholder="留空 = 自动查找（应用 bin/ → 随包）"
            onChange={(e) => set("outlook_cli_path", e.target.value)}
          />
          <button className={s.btn} onClick={() => pickExe("outlook_cli_path")}>
            选择…
          </button>
        </div>
        <div className={s.field}>
          <label>welink-cli</label>
          <input
            className={s.input}
            value={settings.welink_cli_path}
            placeholder="留空 = 读环境变量 WELINK_CLI，否则从 PATH 查找 welink-cli"
            onChange={(e) => set("welink_cli_path", e.target.value)}
          />
          <button className={s.btn} onClick={() => pickExe("welink_cli_path")}>
            选择…
          </button>
        </div>
        <div className={s.field}>
          <label>html2md</label>
          <input
            className={s.input}
            value={settings.html2md_cli_path}
            placeholder="留空 = 自动查找（应用 bin/ → 随包）"
            onChange={(e) => set("html2md_cli_path", e.target.value)}
          />
          <button className={s.btn} onClick={() => pickExe("html2md_cli_path")}>
            选择…
          </button>
        </div>
      </section>

      {/* ── 保存条 ── */}
      <div className={s.saveBar}>
        {dirty && <span className={s.dirty}>● 有未保存的更改</span>}
        <button
          className={`${s.btn} ${s.btnPrimary}`}
          disabled={saving || !dirty}
          onClick={() => save()}
        >
          {saving ? "保存中…" : "保存设置"}
        </button>
      </div>
    </div>
  );
}

// ── 子组件 ──────────────────────────────────────────────────

function TextField({
  label,
  value,
  placeholder,
  onChange,
}: {
  label: string;
  value: string;
  placeholder?: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className={s.field}>
      <label>{label}</label>
      <input
        className={s.input}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}
