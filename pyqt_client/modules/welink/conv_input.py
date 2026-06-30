"""会话输入组件：类型(群/个人) + id 可编辑下拉（带最近使用历史）。
不再自动列会话，让用户自己填 id；用过的会记下来方便下次选。历史存 settings。"""
from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLabel, QComboBox
from PyQt5.QtCore import Qt

import store


class ConvInput(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        lay.addWidget(QLabel('类型'))
        self._type = QComboBox()
        self._type.addItems(['群', '个人'])
        self._type.setFixedWidth(64)
        lay.addWidget(self._type)

        lay.addWidget(QLabel('ID'))
        self._id = QComboBox()
        self._id.setEditable(True)
        self._id.setMinimumWidth(260)
        self._id.lineEdit().setPlaceholderText('群填 group_id；个人填工号（如 c00872275）')
        lay.addWidget(self._id, 1)

        self._id.activated.connect(self._on_pick_history)
        self._load_history()

    # ── 历史 ──────────────────────────────────────────────
    def _load_history(self):
        cur = self._id.currentText()
        self._id.blockSignals(True)
        self._id.clear()
        for h in store.load_settings().get('welinkRecentConvs', []):
            tag = '群' if h.get('kind') == 'group' else '人'
            label = f'[{tag}] {h.get("name") or h.get("key", "")}'
            self._id.addItem(label, h)
        self._id.setCurrentText(cur)   # 不默认选中历史项
        self._id.blockSignals(False)

    def _on_pick_history(self, index):
        h = self._id.itemData(index)
        if isinstance(h, dict):
            self._type.setCurrentText('群' if h.get('kind') == 'group' else '个人')
            self._id.setCurrentText(h.get('key', ''))

    # ── 对外 ──────────────────────────────────────────────
    def current(self) -> dict:
        """返回 {kind, id, account, name} 或 None。"""
        text = self._id.currentText().strip()
        # 选中历史项时 currentText 可能是 "[群] xxx" 标签，取 itemData 的 key
        data = self._id.currentData()
        if isinstance(data, dict) and self._id.currentText() == self._fmt(data):
            text = data.get('key', '')
        if not text:
            return None
        kind = 'group' if self._type.currentText() == '群' else 'p2p'
        if kind == 'group':
            return {'kind': 'group', 'id': text, 'account': '', 'name': f'群{text}'}
        return {'kind': 'p2p', 'id': '', 'account': text, 'name': text}

    @staticmethod
    def _fmt(h: dict) -> str:
        tag = '群' if h.get('kind') == 'group' else '人'
        return f'[{tag}] {h.get("name") or h.get("key", "")}'

    def remember(self, conv: dict):
        if not conv:
            return
        key = conv.get('id') or conv.get('account')
        if not key:
            return
        rec = {'kind': conv.get('kind', 'group'), 'key': key, 'name': conv.get('name', '')}
        s = store.load_settings()
        hist = [h for h in s.get('welinkRecentConvs', [])
                if not (h.get('kind') == rec['kind'] and h.get('key') == rec['key'])]
        hist.insert(0, rec)
        s['welinkRecentConvs'] = hist[:20]
        store.save_settings(s)
        self._load_history()
