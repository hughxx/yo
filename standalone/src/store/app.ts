import { create } from "zustand";

export type TabKey = "email" | "welink" | "output" | "settings";

interface AppState {
  tab: TabKey;
  setTab: (t: TabKey) => void;

  // 全局运行日志（邮件/WeLink 共用）
  logs: string[];
  appendLog: (line: string) => void;
  clearLogs: () => void;
}

export const useAppStore = create<AppState>((set) => ({
  tab: "email",
  setTab: (tab) => set({ tab }),

  logs: [],
  appendLog: (line) =>
    set((s) => ({ logs: [...s.logs.slice(-499), line] })),
  clearLogs: () => set({ logs: [] }),
}));
