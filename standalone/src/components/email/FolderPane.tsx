"use client";

import { useEffect, useMemo, useState } from "react";

import { invoke, isTauri } from "@/lib/tauri";
import { IMPORTED_MSG_SENTINEL } from "@/lib/types";
import { useSettings } from "@/store/settings";
import s from "./FolderPane.module.scss";

interface TreeNode {
  name: string;
  fullPath: string;
  children: TreeNode[];
}

function buildTree(paths: string[]): TreeNode[] {
  const roots: TreeNode[] = [];
  const map = new Map<string, TreeNode>();
  for (const p of paths) {
    const parts = p.split("\\");
    let prefix = "";
    let level = roots;
    for (const part of parts) {
      prefix = prefix ? `${prefix}\\${part}` : part;
      let node = map.get(prefix);
      if (!node) {
        node = { name: part, fullPath: prefix, children: [] };
        map.set(prefix, node);
        level.push(node);
      }
      level = node.children;
    }
  }
  return roots;
}

/**
 * 左侧文件夹树：纯勾选。勾选的文件夹（含「导入的 msg」）= 处理范围，
 * 手动表格内容与定时扫描都用它。勾选变化时回调 onScopeChange 让表格重载。
 */
export default function FolderPane({
  importedCount,
  refreshSignal,
  onScopeChange,
  onImportMsg,
  onImportPst,
}: {
  importedCount: number;
  refreshSignal: number;
  onScopeChange: () => void;
  onImportMsg: () => void;
  onImportPst: () => void;
}) {
  const [paths, setPaths] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const { settings, patch, save } = useSettings();
  const scope = settings.scan_folders;

  const tree = useMemo(() => buildTree(paths), [paths]);

  useEffect(() => {
    loadFolders();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshSignal]);

  async function loadFolders() {
    if (!isTauri()) return;
    setLoading(true);
    try {
      setPaths((await invoke<string[]>("list_folders")) ?? []);
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }

  async function toggle(key: string) {
    const next = scope.includes(key) ? scope.filter((p) => p !== key) : [...scope, key];
    patch({ scan_folders: next });
    await save();
    onScopeChange();
  }

  return (
    <div className={s.pane}>
      <div className={s.head}>
        <div className={s.importWrap}>
          <button className={s.importBtn} onClick={() => setShowImport((v) => !v)}>
            导入 ▾
          </button>
          {showImport && (
            <div className={s.menu}>
              <button className={s.menuItem} onClick={() => { setShowImport(false); onImportMsg(); }}>
                导入 .msg 文件
              </button>
              <button className={s.menuItem} onClick={() => { setShowImport(false); onImportPst(); }}>
                导入 .pst（挂载为文件夹）
              </button>
            </div>
          )}
        </div>
        <button className={s.reload} onClick={loadFolders}>
          {loading ? "…" : "刷新"}
        </button>
      </div>
      <div className={s.subhead}>勾选 = 处理 / 定时范围</div>

      <div className={s.tree}>
        {tree.map((n) => (
          <FolderRow key={n.fullPath} node={n} depth={0} scope={scope} onToggle={toggle} />
        ))}
        {paths.length === 0 && !loading && (
          <div className={s.hint}>点「刷新」加载 Outlook 文件夹</div>
        )}

        {/* 特殊节点：导入的 msg */}
        <div className={s.special}>
          <div className={s.row} onClick={() => toggle(IMPORTED_MSG_SENTINEL)}>
            <span className={s.twist} />
            <input
              type="checkbox"
              checked={scope.includes(IMPORTED_MSG_SENTINEL)}
              onClick={(e) => e.stopPropagation()}
              onChange={() => toggle(IMPORTED_MSG_SENTINEL)}
            />
            <span className={s.name}>📨 导入的 msg</span>
            <span className={s.count}>{importedCount}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function FolderRow({
  node,
  depth,
  scope,
  onToggle,
}: {
  node: TreeNode;
  depth: number;
  scope: string[];
  onToggle: (path: string) => void;
}) {
  const [open, setOpen] = useState(depth < 1);
  const hasChildren = node.children.length > 0;

  return (
    <div>
      <div className={s.row} style={{ paddingLeft: depth * 14 }} onClick={() => onToggle(node.fullPath)}>
        <span
          className={s.twist}
          onClick={(e) => {
            e.stopPropagation();
            if (hasChildren) setOpen(!open);
          }}
        >
          {hasChildren ? (open ? "▾" : "▸") : ""}
        </span>
        <input
          type="checkbox"
          checked={scope.includes(node.fullPath)}
          onClick={(e) => e.stopPropagation()}
          onChange={() => onToggle(node.fullPath)}
        />
        <span className={s.name}>{node.name}</span>
      </div>
      {open &&
        node.children.map((c) => (
          <FolderRow key={c.fullPath} node={c} depth={depth + 1} scope={scope} onToggle={onToggle} />
        ))}
    </div>
  );
}
