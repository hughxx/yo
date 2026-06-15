import { create } from "zustand";

import { invoke } from "@/lib/tauri";
import { DEFAULT_SETTINGS, type Settings } from "@/lib/types";

interface SettingsState {
  settings: Settings;
  loaded: boolean;
  dirty: boolean;
  saving: boolean;

  load: () => Promise<void>;
  /** 局部更新（标记 dirty，不落盘） */
  patch: (p: Partial<Settings>) => void;
  /** 落盘到 Rust */
  save: () => Promise<void>;
}

export const useSettings = create<SettingsState>((set, get) => ({
  settings: DEFAULT_SETTINGS,
  loaded: false,
  dirty: false,
  saving: false,

  load: async () => {
    const s = await invoke<Settings>("get_settings");
    set({ settings: s ?? DEFAULT_SETTINGS, loaded: true, dirty: false });
  },

  patch: (p) =>
    set((st) => ({ settings: { ...st.settings, ...p }, dirty: true })),

  save: async () => {
    set({ saving: true });
    try {
      await invoke("save_settings", { settings: get().settings });
      set({ dirty: false });
    } finally {
      set({ saving: false });
    }
  },
}));
