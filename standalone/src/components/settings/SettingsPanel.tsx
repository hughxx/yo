"use client";

import { useEffect } from "react";
import { open } from "@tauri-apps/plugin-dialog";

import { useSettings } from "@/store/settings";
import type { EmailRule, WelinkGroup, Settings } from "@/lib/types";
import { isTauri } from "@/lib/tauri";
import s from "./SettingsPanel.module.scss";

// 简单唯一 id（避免依赖 crypto / Date.now 之外的库）
function uid(): string {
  return Math.random().toString(36).slice(2, 10);
}

const splitList = (v: string): string[] =>
  v
    .split(/[,，]/)
    .map((x) => x.trim())
    .filter(Boolean);

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

  async function pickExe(k: "outlook_cli_path" | "welink_cli_path") {
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
            max={200}
            onChange={(e) => set("title_max_len", Number(e.target.value) || 60)}
          />
          <span className={s.hint}>用于文件名截断</span>
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
        <div className={s.field}>
          <label>自动扫描</label>
          <input
            type="checkbox"
            checked={settings.auto_scan}
            onChange={(e) => set("auto_scan", e.target.checked)}
          />
          <span className={s.hint}>按下方间隔自动抓取邮件</span>
        </div>
      </section>

      {/* ── 邮件 ── */}
      <section className={s.section}>
        <h3>邮件</h3>
        <div className={s.field}>
          <label>扫描间隔</label>
          <input
            type="number"
            className={s.numInput}
            value={settings.scan_interval_minutes}
            min={1}
            onChange={(e) =>
              set("scan_interval_minutes", Number(e.target.value) || 60)
            }
          />
          <span className={s.hint}>分钟</span>
        </div>

        <div className={s.field}>
          <label>扫描文件夹</label>
          <span className={s.hint}>
            留空 = 默认收件箱；格式 Store\Inbox\子文件夹
          </span>
        </div>
        <StringListEditor
          items={settings.scan_folders}
          placeholder="如：张三\收件箱\项目A"
          onChange={(v) => set("scan_folders", v)}
        />

        <div style={{ height: 8 }} />
        <div className={s.field}>
          <label>匹配规则</label>
          <button
            className={s.btn}
            onClick={() =>
              set("email_rules", [
                ...settings.email_rules,
                {
                  id: uid(),
                  name: "新规则",
                  keywords: [],
                  body_keywords: [],
                  senders: [],
                  logic: "OR",
                  enabled: true,
                },
              ])
            }
          >
            + 新增规则
          </button>
        </div>
        {settings.email_rules.map((rule) => (
          <RuleCard
            key={rule.id}
            rule={rule}
            onChange={(r) =>
              set(
                "email_rules",
                settings.email_rules.map((x) => (x.id === r.id ? r : x))
              )
            }
            onDelete={() =>
              set(
                "email_rules",
                settings.email_rules.filter((x) => x.id !== rule.id)
              )
            }
          />
        ))}
      </section>

      {/* ── WeLink ── */}
      <section className={s.section}>
        <h3>WeLink</h3>
        <div className={s.field}>
          <label>监听群</label>
          <button
            className={s.btn}
            onClick={() =>
              set("welink_groups", [
                ...settings.welink_groups,
                { id: uid(), group_id: "", group_name: "", enabled: true },
              ])
            }
          >
            + 新增群
          </button>
        </div>
        {settings.welink_groups.map((g) => (
          <GroupRow
            key={g.id}
            group={g}
            onChange={(ng) =>
              set(
                "welink_groups",
                settings.welink_groups.map((x) => (x.id === ng.id ? ng : x))
              )
            }
            onDelete={() =>
              set(
                "welink_groups",
                settings.welink_groups.filter((x) => x.id !== g.id)
              )
            }
          />
        ))}

        <div style={{ height: 8 }} />
        <TextField
          label="开始命令"
          value={settings.welink_start_cmd}
          onChange={(v) => set("welink_start_cmd", v)}
        />
        <TextField
          label="结束命令"
          value={settings.welink_end_cmd}
          onChange={(v) => set("welink_end_cmd", v)}
        />
        <TextField
          label="总结命令"
          value={settings.welink_summary_cmd}
          onChange={(v) => set("welink_summary_cmd", v)}
        />
        <div className={s.field}>
          <label>轮询间隔</label>
          <input
            type="number"
            className={s.numInput}
            value={settings.welink_poll_interval}
            min={1}
            onChange={(e) =>
              set("welink_poll_interval", Number(e.target.value) || 8)
            }
          />
          <span className={s.hint}>秒</span>
        </div>
        <div className={s.field}>
          <label>按天归档</label>
          <input
            type="checkbox"
            checked={settings.welink_daily_record}
            onChange={(e) => set("welink_daily_record", e.target.checked)}
          />
          <span className={s.hint}>每日</span>
          <input
            className={s.numInput}
            value={settings.welink_daily_time}
            placeholder="01:00"
            onChange={(e) => set("welink_daily_time", e.target.value)}
          />
          <span className={s.hint}>归档前一天全天记录</span>
        </div>
      </section>

      {/* ── 图片 ── */}
      <section className={s.section}>
        <h3>图片</h3>
        <TextField
          label="上传接口 URL"
          value={settings.image_upload_url}
          placeholder="留空 = 产物不含图片；如 http://host:port/api/image/upload"
          onChange={(v) => set("image_upload_url", v)}
        />
        <TextField
          label="云盘账号"
          value={settings.clouddrive_account}
          placeholder="WeLink 需登录链接时用（可选）"
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
            placeholder="留空 = 用随包 outlook_cli.exe"
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
            placeholder="留空 = 从 PATH 查找 welink-cli"
            onChange={(e) => set("welink_cli_path", e.target.value)}
          />
          <button className={s.btn} onClick={() => pickExe("welink_cli_path")}>
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

function StringListEditor({
  items,
  placeholder,
  onChange,
}: {
  items: string[];
  placeholder?: string;
  onChange: (v: string[]) => void;
}) {
  return (
    <div style={{ marginLeft: 130 }}>
      {items.map((it, i) => (
        <div className={s.listRow} key={i}>
          <input
            className={s.input}
            value={it}
            placeholder={placeholder}
            onChange={(e) => {
              const next = [...items];
              next[i] = e.target.value;
              onChange(next);
            }}
          />
          <button
            className={`${s.btn} ${s.btnDanger}`}
            onClick={() => onChange(items.filter((_, j) => j !== i))}
          >
            ×
          </button>
        </div>
      ))}
      <button className={s.btn} onClick={() => onChange([...items, ""])}>
        + 添加
      </button>
    </div>
  );
}

function RuleCard({
  rule,
  onChange,
  onDelete,
}: {
  rule: EmailRule;
  onChange: (r: EmailRule) => void;
  onDelete: () => void;
}) {
  const upd = (p: Partial<EmailRule>) => onChange({ ...rule, ...p });
  return (
    <div className={s.ruleCard}>
      <div className={s.field}>
        <label>名称</label>
        <input
          className={s.input}
          value={rule.name}
          onChange={(e) => upd({ name: e.target.value })}
        />
        <input
          type="checkbox"
          checked={rule.enabled}
          onChange={(e) => upd({ enabled: e.target.checked })}
          title="启用"
        />
        <button className={`${s.btn} ${s.btnDanger}`} onClick={onDelete}>
          删除
        </button>
      </div>
      <div className={s.field}>
        <label>主题关键词</label>
        <input
          className={s.input}
          value={rule.keywords.join(", ")}
          placeholder="逗号分隔"
          onChange={(e) => upd({ keywords: splitList(e.target.value) })}
        />
      </div>
      <div className={s.field}>
        <label>正文关键词</label>
        <input
          className={s.input}
          value={rule.body_keywords.join(", ")}
          placeholder="逗号分隔（命中走正文搜索，较慢）"
          onChange={(e) => upd({ body_keywords: splitList(e.target.value) })}
        />
      </div>
      <div className={s.field}>
        <label>发件人</label>
        <input
          className={s.input}
          value={rule.senders.join(", ")}
          placeholder="姓名或邮箱，逗号分隔"
          onChange={(e) => upd({ senders: splitList(e.target.value) })}
        />
      </div>
      <div className={s.field}>
        <label>匹配逻辑</label>
        <select
          className={s.select}
          value={rule.logic}
          onChange={(e) => upd({ logic: e.target.value as EmailRule["logic"] })}
        >
          <option value="OR">OR（任一命中）</option>
          <option value="AND">AND（全部命中）</option>
        </select>
      </div>
    </div>
  );
}

function GroupRow({
  group,
  onChange,
  onDelete,
}: {
  group: WelinkGroup;
  onChange: (g: WelinkGroup) => void;
  onDelete: () => void;
}) {
  const upd = (p: Partial<WelinkGroup>) => onChange({ ...group, ...p });
  return (
    <div className={s.listRow} style={{ marginLeft: 130 }}>
      <input
        className={s.input}
        value={group.group_id}
        placeholder="群组 ID"
        onChange={(e) => upd({ group_id: e.target.value })}
      />
      <input
        className={s.input}
        value={group.group_name}
        placeholder="群组名称"
        onChange={(e) => upd({ group_name: e.target.value })}
      />
      <input
        type="checkbox"
        checked={group.enabled}
        onChange={(e) => upd({ enabled: e.target.checked })}
        title="启用"
      />
      <button className={`${s.btn} ${s.btnDanger}`} onClick={onDelete}>
        ×
      </button>
    </div>
  );
}
