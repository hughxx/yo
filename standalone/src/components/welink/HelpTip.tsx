"use client";

import s from "./WelinkPanel.module.scss";

/** 「?」悬浮提示，鼠标停留弹出内容。 */
export default function HelpTip({ children }: { children: React.ReactNode }) {
  return (
    <span className={s.help}>
      <span className={s.helpIcon}>?</span>
      <div className={s.helpPop}>{children}</div>
    </span>
  );
}
