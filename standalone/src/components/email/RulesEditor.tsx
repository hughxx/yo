"use client";

import { useSettings } from "@/store/settings";
import type { EmailRule } from "@/lib/types";
import { uid, splitList } from "@/lib/util";
import s from "./RulesEditor.module.scss";

/**
 * 邮件匹配规则编辑器（就近放在邮件页）。
 * 规则属于全局 settings，这里通过 useSettings 编辑并保存；保存后回调 onSaved 触发重新匹配。
 */
export default function RulesEditor({ onSaved }: { onSaved?: () => void }) {
  const { settings, dirty, saving, patch, save } = useSettings();
  const rules = settings.email_rules;

  const setRules = (next: EmailRule[]) => patch({ email_rules: next });

  function addRule() {
    setRules([
      ...rules,
      {
        id: uid(),
        name: "新规则",
        keywords: [],
        body_keywords: [],
        senders: [],
        logic: "OR",
        enabled: true,
      },
    ]);
  }

  async function saveRules() {
    await save();
    onSaved?.();
  }

  return (
    <div className={s.editor}>
      <div className={s.head}>
        <span className={s.title}>匹配规则（{rules.length}）</span>
        <div className={s.spacer} />
        {dirty && <span className={s.dirty}>● 未保存</span>}
        <button className={s.btn} onClick={addRule} style={{ marginRight: 8 }}>
          + 新增规则
        </button>
        <button
          className={`${s.btn} ${s.btnPrimary}`}
          onClick={saveRules}
          disabled={saving || !dirty}
        >
          {saving ? "保存中…" : "保存并重新匹配"}
        </button>
      </div>

      {rules.length === 0 ? (
        <div className={s.empty}>还没有规则。新增一条，命中的邮件会被标记并可自动处理。</div>
      ) : (
        rules.map((rule) => (
          <RuleCard
            key={rule.id}
            rule={rule}
            onChange={(r) => setRules(rules.map((x) => (x.id === r.id ? r : x)))}
            onDelete={() => setRules(rules.filter((x) => x.id !== rule.id))}
          />
        ))
      )}
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
          placeholder="逗号分隔（走正文搜索，较慢）"
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
