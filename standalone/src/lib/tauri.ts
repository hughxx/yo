// 对 Tauri invoke / event 的薄封装。
// 在浏览器（非 Tauri）环境下 invoke 会缺失，这里做一层降级以便纯前端调试。
import { invoke as tauriInvoke } from "@tauri-apps/api/core";
import { listen as tauriListen, type UnlistenFn } from "@tauri-apps/api/event";

export function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

export async function invoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  if (!isTauri()) {
    console.warn(`[invoke:${cmd}] 非 Tauri 环境，返回空`);
    return undefined as unknown as T;
  }
  return tauriInvoke<T>(cmd, args);
}

export async function listen<T>(
  event: string,
  handler: (payload: T) => void
): Promise<UnlistenFn> {
  if (!isTauri()) return () => {};
  return tauriListen<T>(event, (e) => handler(e.payload));
}
