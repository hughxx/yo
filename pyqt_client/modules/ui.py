"""飞书风 UI 工具库：调色板 + 可复用小组件（头像 / 标签 / 状态点）。

原则：不拿 QSS 去套原生复杂控件（那会出白框、吞箭头），而是用这些自绘小部件拼行。
"""
import os as _os
import sys as _sys

from PyQt5.QtWidgets import QLabel, QFrame
from PyQt5.QtCore import Qt


# ── 调色板（飞书） ──────────────────────────────────────────
ACCENT       = '#2b54cc'   # 主蓝
ACCENT_HOVER = '#21419e'
ACCENT_WEAK  = '#eff2fb'   # 选中/悬停 淡蓝
ACCENT_WEAK2 = '#e1eaff'   # chip 蓝底
INK          = '#1f2329'   # 正文
SUB          = '#646a73'   # 次级
FAINT        = '#8f959e'   # 三级
BG           = '#ffffff'
SIDEBAR      = '#f5f6f7'
HOVER        = '#f2f3f5'
HAIR         = '#e5e6eb'

# 语义色（状态）：(前景, 底色)
STATUS = {
    'done':  ('#2ba471', '#e8f7f0'),
    'pend':  ('#d98800', '#fdf3e2'),
    'fail':  ('#e5484d', '#fdecec'),
    'none':  ('#8f959e', '#f0f1f2'),
}

# 头像色板：(底, 字)
_AVATAR = [
    ('#e1eaff', '#2b54cc'), ('#ffe9d6', '#d9720b'), ('#e3f6ec', '#2ba471'),
    ('#efe6ff', '#7a4ddb'), ('#ffe2ec', '#d9436b'), ('#fff2d6', '#b8860b'),
    ('#d9f4f4', '#0e9aa7'), ('#e6e9ff', '#4f46e5'),
]


def _hash(s: str) -> int:
    h = 0
    for c in s or '':
        h = (h * 31 + ord(c)) & 0xFFFFFFFF
    return h


def avatar_colors(name: str):
    return _AVATAR[_hash(name) % len(_AVATAR)]


def initial(name: str) -> str:
    name = (name or '').strip()
    return name[0].upper() if name else '?'


def asset_icon(name: str) -> str:
    """assets/icons/<name> 的绝对路径（兼容 PyInstaller frozen）。用正斜杠，便于塞进 QSS url()。"""
    base = getattr(_sys, '_MEIPASS', _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    return _os.path.join(base, 'assets', 'icons', name).replace('\\', '/')


# ── 组件 ────────────────────────────────────────────────────
class Avatar(QLabel):
    """圆角方形首字母头像，颜色由名字确定。"""
    def __init__(self, name: str, size: int = 36, parent=None):
        super().__init__(parent)
        bg, fg = avatar_colors(name)
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignCenter)
        self.setText(initial(name))
        self.setToolTip(name or '')
        self.setStyleSheet(
            f'background:{bg}; color:{fg}; border-radius:{max(6, size//4)}px;'
            f'font-weight:700; font-size:{int(size*0.42)}px;')


class Chip(QLabel):
    """小圆角标签。kind: default / blue / green / red / amber。"""
    _KIND = {
        'default': (SUB,      '#f0f1f2'),
        'blue':    (ACCENT,   ACCENT_WEAK2),
        'green':   ('#2ba471', '#e3f6ec'),
        'red':     ('#e5484d', '#fdecec'),
        'amber':   ('#d98800', '#fdf3e2'),
    }
    def __init__(self, text: str, kind: str = 'default', parent=None):
        super().__init__(text, parent)
        fg, bg = self._KIND.get(kind, self._KIND['default'])
        self.setStyleSheet(
            f'background:{bg}; color:{fg}; border-radius:5px;'
            f'padding:1px 7px; font-size:11px; font-weight:600;')
        self.setAlignment(Qt.AlignCenter)


class StatusChip(QLabel):
    """状态点+文字胶囊。status: done/pend/fail/none。"""
    def __init__(self, text: str, status: str = 'none', parent=None):
        super().__init__(text, parent)
        fg, bg = STATUS.get(status, STATUS['none'])
        self.setStyleSheet(
            f'background:{bg}; color:{fg}; border-radius:9px;'
            f'padding:2px 10px; font-size:11px; font-weight:600;')
        self.setAlignment(Qt.AlignCenter)


class HLine(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(1)
        self.setStyleSheet(f'background:{HAIR}; border:none;')


class ElidedLabel(QLabel):
    """右侧省略号的单行 Label（长文本不会撑爆行宽）。"""
    def __init__(self, text: str = '', parent=None):
        super().__init__(parent)
        self._full = text
        super().setText(text)

    def setText(self, t: str):
        self._full = t or ''
        self._elide()

    def text(self) -> str:
        return self._full

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._elide()

    def _elide(self):
        fm = self.fontMetrics()
        super().setText(fm.elidedText(self._full, Qt.ElideRight, max(0, self.width() - 2)))
