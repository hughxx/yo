// 与 src-tauri/src/settings.rs 的结构保持一致（serde 字段名为 snake_case）。

export interface EmailSummary {
  item_id: string;
  subject: string;
  sender_name: string;
  sender_email: string;
  received_time: string;
  conversation_topic: string;
  matched: boolean;
  /** 已导出（本地输出件存在）→ 行置灰不可选 */
  processed: boolean;
  /** 导入 .msg 的源路径；Outlook 邮件为空 */
  source_path: string;
}

/** 左树「导入的 msg」节点在 scan_folders 中的标记值，需与 Rust 端 IMPORTED_MSG_SENTINEL 一致 */
export const IMPORTED_MSG_SENTINEL = "::imported_msg::";

export interface OutputEntry {
  source: string;
  base_name: string;
  html_path: string;
  md_path: string;
  /** 文件修改时间 "YYYY-MM-DD HH:MM"（即原始日期，存于 mtime） */
  modified: string;
}

export interface SyncStatus {
  running: boolean;
  last_sync: string;
  last_ok: boolean;
  last_msg: string;
}

export interface ScanReport {
  scanned: number;
  matched: number;
  saved: number;
  skipped: number;
  failed: number;
}


export interface EmailRule {
  id: string;
  name: string;
  keywords: string[];
  body_keywords: string[];
  senders: string[];
  logic: "OR" | "AND";
  enabled: boolean;
}

export interface WelinkGroup {
  id: string;
  group_id: string;
  group_name: string;
  enabled: boolean;
}

export interface Settings {
  // 通用
  output_dir: string;
  title_max_len: number;
  conflict_strategy: "suffix" | "overwrite" | "skip";
  auto_scan: boolean;

  // 邮件
  scan_folders: string[];
  scan_interval_minutes: number;
  email_rules: EmailRule[];

  // WeLink — 命令触发（录制 / 归档）
  welink_groups: WelinkGroup[];
  welink_start_cmd: string;
  welink_end_cmd: string;
  welink_summary_cmd: string;
  welink_poll_interval: number;

  // WeLink — 自动收集（独立后台：周期 / 每日定时 / 时间段限定）
  collect_groups: WelinkGroup[];
  collect_poll_interval: number;
  collect_periodic_enabled: boolean;
  collect_period_hours: number;
  collect_daily_enabled: boolean;
  collect_daily_times: string[];
  collect_window_enabled: boolean;
  collect_window_start: string;
  collect_window_end: string;

  // 图片
  image_upload_url: string;
  clouddrive_url: string;
  clouddrive_account: string;
  clouddrive_password: string;

  // 外置 CLI 路径
  outlook_cli_path: string;
  welink_cli_path: string;
  html2md_cli_path: string;

  // 云同步
  sync_enabled: boolean;
  sync_command: string;
  sync_daily_time: string;

  last_timer_interval: number;
  last_timer_rules: string[];
}

export const DEFAULT_SETTINGS: Settings = {
  output_dir: "",
  title_max_len: 220,
  conflict_strategy: "suffix",
  auto_scan: false,

  scan_folders: [],
  scan_interval_minutes: 60,
  email_rules: [],

  welink_groups: [],
  welink_start_cmd: "@云见 开始定位",
  welink_end_cmd: "@云见 结束定位",
  welink_summary_cmd: "@云见 总结经验",
  welink_poll_interval: 8,

  collect_groups: [],
  collect_poll_interval: 60,
  collect_periodic_enabled: false,
  collect_period_hours: 6,
  collect_daily_enabled: false,
  collect_daily_times: ["01:00"],
  collect_window_enabled: false,
  collect_window_start: "09:00",
  collect_window_end: "18:00",

  image_upload_url: "",
  clouddrive_url: "https://clouddrive.huawei.com",
  clouddrive_account: "",
  clouddrive_password: "",

  outlook_cli_path: "",
  welink_cli_path: "",
  html2md_cli_path: "",

  sync_enabled: false,
  sync_command: "",
  sync_daily_time: "02:00",

  last_timer_interval: 60,
  last_timer_rules: [],
};
