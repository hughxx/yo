"""主壳：侧边栏导航 + 模块切换"""
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QToolButton, QStackedWidget, QSizePolicy, QLabel,
    QSystemTrayIcon, QMenu, QAction, QApplication
)
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QIcon, QPixmap, QPainter, QColor
from PyQt5.QtSvg import QSvgRenderer
import os as _os, sys as _sys


def _asset(name: str) -> str:
    """返回 assets 文件路径，兼容 PyInstaller frozen 模式。"""
    base = getattr(_sys, '_MEIPASS', _os.path.dirname(_os.path.abspath(__file__)))
    return _os.path.join(base, 'assets', name)


# ── 侧栏 SVG 图标（单色线性图标 → 运行时按状态上色） ─────────
def _tint_pixmap(svg_path: str, size: int, color: str) -> QPixmap:
    """把单色 SVG 渲染成 size×size 像素并整体染成 color（保留描边形状的 alpha）。"""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    renderer = QSvgRenderer(svg_path)
    p = QPainter(pm)
    renderer.render(p)
    p.setCompositionMode(QPainter.CompositionMode_SourceIn)
    p.fillRect(pm.rect(), QColor(color))
    p.end()
    return pm


def _nav_icon(name: str, off: str = '#646a73', on: str = '#2b54cc') -> QIcon:
    """侧栏导航图标：未选中 off 色，选中(On)/悬停(Active) on 色。渲染 2× 保证清晰。"""
    path = _asset(_os.path.join('icons', f'{name}.svg'))
    ic = QIcon()
    if _os.path.exists(path):
        ic.addPixmap(_tint_pixmap(path, 44, off), QIcon.Normal, QIcon.Off)
        ic.addPixmap(_tint_pixmap(path, 44, on),  QIcon.Normal, QIcon.On)
        ic.addPixmap(_tint_pixmap(path, 44, on),  QIcon.Active, QIcon.Off)
    return ic


# 模块名 → 图标文件名
_NAV_ICONS = {'邮件': 'mail', 'WeLink': 'chat'}


def _app_icon() -> QIcon:
    svg_path = _asset('icon.svg')
    if _os.path.exists(svg_path):
        renderer = QSvgRenderer(svg_path)
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        return QIcon(pixmap)
    for name in ('icon.png', 'icon.ico'):
        path = _asset(name)
        if _os.path.exists(path):
            return QIcon(path)
    return QIcon()

from modules import ui as _ui
from modules.email.panel import EmailPanel
from modules.welink.container import WelinkContainer
from modules.email.dialogs import SetupDialog
from utils import Worker
from version import APP_VERSION
import webbrowser
import store
import backend


def _ver_tuple(v: str):
    try:
        return tuple(int(x) for x in str(v).split('.')[:3])
    except Exception:
        return (0, 0, 0)

# ── 样式表 ────────────────────────────────────────────────
_QSS_TEMPLATE = """
* {
    font-family: "Segoe UI", "Microsoft YaHei UI", "Microsoft YaHei", sans-serif;
    font-size: 12px;
    color: #1f2329;
}
QMainWindow, QWidget { background: #ffffff; }

/* ── 侧栏：宽版横排 + 选中淡蓝底 + 左侧蓝竖条（UU 风） ── */
#sidebar { background: #f7f8fa; border-right: 1px solid #eceef1; }
#brandTitle { font-weight: 700; font-size: 14px; color: #1f2329; }
QPushButton#sideBtn { background: transparent; border: none; border-left: 3px solid transparent;
    border-radius: 0; text-align: left; padding: 9px 12px 9px 16px; color: #4e5969; font-size: 13px; font-weight: 500; }
QPushButton#sideBtn:hover { background: #eef0f3; color: #1f2329; }
QPushButton#sideBtn:checked { background: #e8f0ff; color: #2b54cc; font-weight: 700; border-left: 3px solid #2b54cc; }

#toolbar { background: #ffffff; border-bottom: 1px solid #eceef1; padding: 8px 14px; }
#pagination { background: #ffffff; border-top: 1px solid #eceef1; padding: 7px 14px; }

/* 卡片用 QFrame#card 显式声明；GroupBox 一律无框（只留标题），避免「卡片框套表格框」双层框 */
QFrame#card { background: #ffffff; border: 1px solid #e5e6eb; border-radius: 10px; }
QGroupBox { background: transparent; border: none; margin-top: 16px; padding: 4px 0 0 0; font-weight: 700; }
QGroupBox::title { subcontrol-origin: margin; left: 2px; padding: 0 2px; color: #1f2329; }
/* QLabel 继承自 QFrame，务必复位：否则每个文字都被套一个边框白框 */
QLabel { background: transparent; border: none; }

/* ── 按钮：白底 + 6px 圆角（飞书） ── */
QPushButton { border: 1px solid #dee0e3; background: #ffffff; padding: 6px 14px; border-radius: 6px; min-height: 26px; color: #1f2329; }
QPushButton:hover { background: #f5f6f7; border-color: #c9cdd4; color: #2b54cc; }
QPushButton:pressed { background: #eff2fb; border-color: #2b54cc; }
QPushButton:disabled { color: #bbc0c9; background: #f7f8fa; border-color: #eceef1; }

/* 主行动：飞书蓝 */
QPushButton#btnPrimary, QPushButton#btnSync { background: #2b54cc; color: #ffffff; border: 1px solid #2b54cc; font-weight: 600; }
QPushButton#btnPrimary:hover, QPushButton#btnSync:hover { background: #21419e; border-color: #21419e; color: #ffffff; }
QPushButton#btnPrimary:pressed, QPushButton#btnSync:pressed { background: #1a3f96; border-color: #1a3f96; }
QPushButton#btnPrimary:disabled, QPushButton#btnSync:disabled { background: #a8c0ff; border-color: #a8c0ff; color: #f2f6ff; }

QPushButton#btnRefresh { color: #1f2329; }
QPushButton#btnRefresh:hover { color: #2b54cc; }
QPushButton#btnDanger { color: #e5484d; border-color: #f6c6c8; background: #ffffff; }
QPushButton#btnDanger:hover { background: #fdecec; border-color: #eea3a6; }
QPushButton#pgBtn { padding: 2px 9px; min-height: 22px; min-width: 26px; border-radius: 6px; }
QPushButton#pgBtn:disabled { color: #c6cad2; }

/* ── 输入：修好下拉箭头（塞 SVG）；选中色淡蓝 ── */
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QTimeEdit {
    background: #ffffff; border: 1px solid #dee0e3; border-radius: 6px; padding: 5px 9px;
    selection-background-color: #d4e2ff; selection-color: #1f2329; }
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus, QTimeEdit:focus { border: 1px solid #2b54cc; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled { color: #9ca3af; background: #f7f8fa; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox::down-arrow { image: url(__CHEVRON__); width: 12px; height: 12px; }
QComboBox QAbstractItemView { border: 1px solid #e5e6eb; border-radius: 8px; background: #ffffff;
    selection-background-color: #eff2fb; selection-color: #1f2329; outline: none; padding: 4px; }
QSpinBox::up-button, QSpinBox::down-button, QTimeEdit::up-button, QTimeEdit::down-button { width: 0; border: none; }

/* ── 复选框：QSS indicator（不再是原生白方块） ── */
QCheckBox { spacing: 6px; color: #1f2329; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1.5px solid #c0c4cc; border-radius: 4px; background: #ffffff; }
QCheckBox::indicator:hover { border-color: #2b54cc; }
QCheckBox::indicator:checked { background: #2b54cc; border-color: #2b54cc; image: url(__CHECK__); }
/* 树/表里的勾选框同款（否则又是原生白方块） */
QTreeView::indicator, QTreeWidget::indicator, QTableView::indicator, QTableWidget::indicator {
    width: 15px; height: 15px; border: 1.5px solid #c0c4cc; border-radius: 4px; background: #ffffff; }
QTreeView::indicator:checked, QTreeWidget::indicator:checked, QTableView::indicator:checked, QTableWidget::indicator:checked {
    background: #2b54cc; border-color: #2b54cc; image: url(__CHECK__); }

/* ── 列表：无边框、圆角选中/悬停 ── */
QListWidget { border: none; background: transparent; outline: none; }
QListWidget::item { border-radius: 8px; margin: 1px 0; color: #1f2329; }
QListWidget::item:hover { background: #f2f3f5; }
QListWidget::item:selected { background: #eff2fb; color: #1f2329; }

/* 树/表（文件夹、规则表等）保留但飞书化 */
QTreeWidget, QTableWidget { border: 1px solid #e5e6eb; border-radius: 8px; background: #ffffff;
    gridline-color: #f0f1f2; selection-background-color: #eff2fb; selection-color: #1f2329; outline: none; }
QTreeWidget::item, QTableWidget::item { padding: 5px 7px; }
QHeaderView::section { background: #fafbfc; border: none; border-bottom: 1px solid #eceef1; padding: 8px 10px; color: #646a73; font-weight: 700; }

/* ── 页签：选中蓝字（飞书） ── */
QTabWidget::pane { border: none; border-top: 1px solid #eceef1; background: #ffffff; top: -1px; }
QTabBar::tab { padding: 9px 4px; margin-right: 22px; background: transparent; border: none;
    border-bottom: 2px solid transparent; color: #646a73; }
QTabBar::tab:selected { color: #2b54cc; border-bottom: 2px solid #2b54cc; font-weight: 700; }
QTabBar::tab:hover:!selected { color: #1f2329; }

QProgressBar { max-height: 3px; border: none; border-radius: 2px; background: #eceef1; }
QProgressBar::chunk { border-radius: 2px; background: #2b54cc; }
QScrollBar:vertical { background: transparent; width: 9px; margin: 2px; }
QScrollBar::handle:vertical { background: #d5d8dd; border-radius: 4px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #c0c4cc; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QToolTip { color: #ffffff; background: #1f2329; border: none; border-radius: 6px; padding: 6px 8px; }
QDialog, QMessageBox { background: #ffffff; }
QDialogButtonBox QPushButton { min-width: 78px; }
"""

QSS = (_QSS_TEMPLATE
       .replace('__CHEVRON__', _ui.asset_icon('chevron-down.svg'))
       .replace('__CHECK__', _ui.asset_icon('check-white.svg')))
# ── 模块注册表 ────────────────────────────────────────────
_MODULES = [
    ('邮件',   EmailPanel),
    ('WeLink', WelinkContainer),
]


# ── 主壳 ──────────────────────────────────────────────────
class MainShell(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('问题定位助手')
        self.setWindowIcon(_app_icon())
        self.resize(1320, 840)
        self.setMinimumSize(1080, 640)

        self._panels   = []
        self._nav_btns = []
        self._stack    = QStackedWidget()

        self._setup_dlg = None

        self._build_ui()
        self._build_tray()
        self._switch(0)
        self._check_setup()
        self._check_version()

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        lay = QHBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        lay.addWidget(self._make_sidebar())
        lay.addWidget(self._stack, stretch=1)

    @staticmethod
    def _side_button(text: str, icon_name: str, checkable: bool) -> QPushButton:
        btn = QPushButton(text)
        btn.setObjectName('sideBtn')
        btn.setIcon(_nav_icon(icon_name))
        btn.setIconSize(QSize(18, 18))
        btn.setCheckable(checkable)
        btn.setFixedHeight(40)
        btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        btn.setCursor(Qt.PointingHandCursor)
        return btn

    def _make_sidebar(self):
        sidebar = QWidget()
        sidebar.setObjectName('sidebar')
        sidebar.setFixedWidth(188)
        sidebar.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        lay = QVBoxLayout(sidebar)
        lay.setContentsMargins(0, 12, 0, 12)
        lay.setSpacing(2)

        for idx, (name, PanelClass) in enumerate(_MODULES):
            panel = PanelClass()
            self._panels.append(panel)
            self._stack.addWidget(panel)

            btn = self._side_button(name, _NAV_ICONS.get(name, 'mail'), checkable=True)
            btn.clicked.connect(lambda _checked, i=idx: self._switch(i))
            self._nav_btns.append(btn)
            lay.addWidget(btn)

        lay.addStretch()

        btn_gear = self._side_button('设置', 'settings', checkable=False)
        btn_gear.setToolTip('设置')
        btn_gear.clicked.connect(self._open_settings)
        lay.addWidget(btn_gear)

        ver = QLabel(f'v{APP_VERSION}')
        ver.setAlignment(Qt.AlignLeft)
        ver.setToolTip(f'客户端版本 v{APP_VERSION}')
        ver.setStyleSheet('color:#a9b0ba; font-size:10px; padding:6px 0 0 16px;')
        lay.addWidget(ver)

        return sidebar

    def _build_tray(self):
        self._tray = QSystemTrayIcon(self)
        self._tray.setIcon(_app_icon())
        self._tray.setToolTip('问题定位助手')

        menu = QMenu()
        act_show = QAction('显示', self)
        act_quit = QAction('退出', self)
        act_show.triggered.connect(self._restore)
        act_quit.triggered.connect(QApplication.quit)
        menu.addAction(act_show)
        menu.addSeparator()
        menu.addAction(act_quit)
        self._tray.setContextMenu(menu)

        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:   # 单击
            self._restore()

    def _restore(self):
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def closeEvent(self, event):
        event.ignore()
        self.hide()
        self._tray.showMessage(
            '问题定位助手',
            '程序已缩小到系统托盘，定时同步继续运行。',
            QSystemTrayIcon.Information,
            2000,
        )

    def _check_setup(self):
        s = store.load_settings()
        if not (s.get('backendUrl') and s.get('userId') and s.get('namespace')):
            self._show_setup(s)

    # ── 版本检查（后台拉服务端，发现新版本则提示） ──────────
    def _check_version(self):
        s = store.load_settings()
        url = s.get('backendUrl')
        if not url:
            return   # 未配置后端，跳过
        backend.set_base(url)
        w = Worker(backend.get_latest_version)
        w.ok.connect(self._on_version)
        w.err.connect(lambda _: None)
        w.start()
        self._ver_worker = w   # 持引用，防 GC

    def _on_version(self, info):
        if not isinstance(info, dict):
            return
        latest = info.get('latest', '')
        if not latest or _ver_tuple(APP_VERSION) >= _ver_tuple(latest):
            return   # 已是最新
        minv  = info.get('min', '')
        force = bool(minv) and _ver_tuple(APP_VERSION) < _ver_tuple(minv)
        self._show_update(latest, info.get('url', ''), info.get('notes', ''), force)

    def _show_update(self, latest, dl_url, notes, force):
        box = QMessageBox(self)
        box.setWindowTitle('版本更新')
        body = f'发现新版本 {latest}（当前 {APP_VERSION}）。'
        if notes:
            body += f'\n\n{notes}'
        if force:
            body += '\n\n这是强制更新，请更新到最新版后再使用。'
        box.setText(body)
        btn_dl = box.addButton('去下载', QMessageBox.AcceptRole)
        # 强更但没配下载地址时，退化为可关闭提醒，避免把用户卡死又无处可下
        if not force or not dl_url:
            box.addButton('稍后', QMessageBox.RejectRole)
        box.exec_()
        if box.clickedButton() is btn_dl and dl_url:
            try:
                webbrowser.open(dl_url)
            except Exception:
                pass
        if force and dl_url:
            QApplication.quit()

    def _show_setup(self, s):
        if self._setup_dlg and self._setup_dlg.isVisible():
            self._setup_dlg.raise_()
            return
        dlg = SetupDialog(s, parent=self, mandatory=True)
        dlg.accepted.connect(lambda: self._on_setup_accepted(dlg))
        dlg.show()
        self._setup_dlg = dlg

    def _on_setup_accepted(self, dlg):
        s = dlg.get_settings()
        store.save_settings(s)
        backend.set_base(s['backendUrl'])
        self._notify_settings_changed(s)

    def _open_settings(self):
        s = store.load_settings()
        dlg = SetupDialog(s, parent=self)
        if dlg.exec_() == SetupDialog.Accepted:
            s = dlg.get_settings()
            store.save_settings(s)
            backend.set_base(s['backendUrl'])
            self._notify_settings_changed(s)

    def _notify_settings_changed(self, s: dict):
        for panel in self._panels:
            if hasattr(panel, 'on_settings_changed'):
                panel.on_settings_changed(s)

    def _switch(self, idx: int):
        current = self._stack.currentIndex()
        if 0 <= current < len(self._panels):
            self._panels[current].deactivate()

        for i, btn in enumerate(self._nav_btns):
            btn.setChecked(i == idx)
        self._stack.setCurrentIndex(idx)

        if 0 <= idx < len(self._panels):
            self._panels[idx].activate()
            self.setWindowTitle('问题定位助手')

