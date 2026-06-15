// 与 src-tauri/src/settings.rs 的结构保持一致（serde 字段名为 snake_case）。

export interface EmailSummary {
  item_id: string;
  subject: string;
  sender_name: string;
  sender_email: string;
  received_time: string;
  conversation_topic: string;
}

export interface OutputEntry {
  base_name: string;
  html_path: string;
  md_path: string;
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

  // WeLink
  welink_groups: WelinkGroup[];
  welink_start_cmd: string;
  welink_end_cmd: string;
  welink_summary_cmd: string;
  welink_poll_interval: number;
  welink_daily_record: boolean;
  welink_daily_time: string;

  // 图片
  image_upload_url: string;
  clouddrive_account: string;
  clouddrive_password: string;

  // 外置 CLI 路径
  outlook_cli_path: string;
  welink_cli_path: string;
}

export const DEFAULT_SETTINGS: Settings = {
  output_dir: "",
  title_max_len: 60,
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
  welink_daily_record: false,
  welink_daily_time: "01:00",

  image_upload_url: "",
  clouddrive_account: "",
  clouddrive_password: "",

  outlook_cli_path: "",
  welink_cli_path: "",
};
