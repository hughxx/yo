"""主壳：侧边栏导航 + 模块切换"""
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QStackedWidget, QSizePolicy, QLabel,
    QSystemTrayIcon, QMenu, QAction, QApplication
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon, QPixmap, QPainter
from PyQt5.QtSvg import QSvgRenderer
import os as _os, sys as _sys


def _asset(name: str) -> str:
    """返回 assets 文件路径，兼容 PyInstaller frozen 模式。"""
    base = getattr(_sys, '_MEIPASS', _os.path.dirname(_os.path.abspath(__file__)))
    return _os.path.join(base, 'assets', name)


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
QSS = """
* {
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif;
    font-size: 12px;
}
QMainWindow { background: #f0f0f0; }

/* 侧边栏 */
#sidebar {
    background: #252526;
    border-right: 1px solid #1a1a1a;
}
QPushButton#sideBtn {
    background: transparent;
    border: none;
    border-left: 3px solid transparent;
    color: #858585;
    font-size: 11px;
    padding: 6px 0;
}
QPushButton#sideBtn:hover {
    color: #cccccc;
    background: #2a2d2e;
}
QPushButton#sideBtn:checked {
    color: #ffffff;
    border-left: 3px solid #0078D4;
    background: #37373d;
}

/* 工具栏 */
#toolbar {
    background: #ffffff;
    border-bottom: 1px solid #d0d0d0;
    padding: 4px 8px;
}

/* 按钮基础 */
QPushButton {
    border: 1px solid #bbb;
    background: #f5f5f5;
    padding: 4px 12px;
    border-radius: 2px;
    min-height: 24px;
}
QPushButton:hover    { background: #e8e8e8; }
QPushButton:pressed  { background: #d8d8d8; }
QPushButton:disabled { color: #aaa; background: #f0f0f0; }

/* 刷新 */
QPushButton#btnRefresh {
    background: #008C64; color: white; border: none;
}
QPushButton#btnRefresh:hover   { background: #007a57; }
QPushButton#btnRefresh:pressed { background: #006b4c; }
QPushButton#btnRefresh:disabled { background: #99cbbf; }

/* 同步 */
QPushButton#btnSync {
    background: #0078D4; color: white; border: none;
}
QPushButton#btnSync:hover   { background: #006abf; }
QPushButton#btnSync:pressed { background: #005ca8; }
QPushButton#btnSync:disabled { background: #99c4e8; }

/* 设置 */
QPushButton#btnSettings {
    background: #505050; color: white; border: none;
}
QPushButton#btnSettings:hover   { background: #404040; }
QPushButton#btnSettings:pressed { background: #303030; }

/* 主要动作（蓝色） */
QPushButton#btnPrimary {
    background: #0078D4; color: white; border: none;
    padding: 4px 14px;
}
QPushButton#btnPrimary:hover { background: #006abf; }

/* 危险动作（红色） */
QPushButton#btnDanger { color: #c00; border-color: #e88; }
QPushButton#btnDanger:hover { background: #fff0f0; }

/* 进度条 */
QProgressBar {
    max-height: 3px;
    border: none;
    background: #e0e0e0;
}
QProgressBar::chunk { background: #0078D4; }

/* 表格 */
QTableWidget {
    border: none;
    gridline-color: #e8e8e8;
    background: white;
    alternate-background-color: #f9f9f9;
    selection-background-color: #cde8ff;
    selection-color: #000;
}
QTableWidget::item { padding: 2px 6px; }
QHeaderView::section {
    background: #f5f5f5;
    border: none;
    border-bottom: 1px solid #d0d0d0;
    border-right: 1px solid #e0e0e0;
    padding: 4px 6px;
    font-weight: bold;
}

/* 分页区 */
#pagination {
    background: #ffffff;
    border-top: 1px solid #d0d0d0;
    padding: 4px 8px;
}
QPushButton#pgBtn {
    border: 1px solid #ccc;
    background: #f5f5f5;
    padding: 2px 8px;
    min-height: 20px;
    min-width: 28px;
}
QPushButton#pgBtn:disabled { color: #ccc; }
QPushButton#pgBtn:hover:!disabled { background: #e0e0e0; }

/* 标签页 */
QTabWidget::pane  { border: 1px solid #d0d0d0; background: white; }
QTabBar::tab {
    padding: 5px 16px;
    background: #f0f0f0;
    border: 1px solid #d0d0d0;
    border-bottom: none;
    margin-right: 2px;
}
QTabBar::tab:selected { background: white; border-bottom: 1px solid white; }
QTabBar::tab:hover:!selected { background: #e4e4e4; }

/* 对话框 */
QDialog { background: #f5f5f5; }
QFormLayout { margin: 12px; }
"""

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

    def _make_sidebar(self):
        sidebar = QWidget()
        sidebar.setObjectName('sidebar')
        sidebar.setFixedWidth(56)
        sidebar.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        lay = QVBoxLayout(sidebar)
        lay.setContentsMargins(0, 8, 0, 8)
        lay.setSpacing(2)

        for idx, (name, PanelClass) in enumerate(_MODULES):
            panel = PanelClass()
            self._panels.append(panel)
            self._stack.addWidget(panel)

            btn = QPushButton(name)
            btn.setObjectName('sideBtn')
            btn.setCheckable(True)
            btn.setFixedHeight(40)
            btn.clicked.connect(lambda _checked, i=idx: self._switch(i))
            self._nav_btns.append(btn)
            lay.addWidget(btn)

        lay.addStretch()

        btn_gear = QPushButton('⚙')
        btn_gear.setObjectName('sideBtn')
        btn_gear.setFixedHeight(40)
        btn_gear.setToolTip('设置')
        btn_gear.clicked.connect(self._open_settings)
        lay.addWidget(btn_gear)

        ver = QLabel(f'v{APP_VERSION}')
        ver.setAlignment(Qt.AlignCenter)
        ver.setToolTip(f'客户端版本 v{APP_VERSION}')
        ver.setStyleSheet('color:#6b6b6b; font-size:9px; padding:2px 0;')
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
