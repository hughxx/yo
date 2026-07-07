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


def _nav_icon(name: str, off: str = '#8b93a1', on: str = '#5e7ce0') -> QIcon:
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
    font-family: "Segoe UI", "Microsoft YaHei UI", "Microsoft YaHei", sans-serif;
    font-size: 12px;
    color: #191919;
}
QMainWindow, QWidget { background: #f5f6f8; }

/* ── 侧栏（浅色 + 圆角选中块） ── */
#sidebar { background: #ffffff; border-right: 1px solid #ececf0; }
QToolButton#sideBtn { background: transparent; border: none; border-radius: 12px; color: #777777; font-size: 11px; padding: 8px 0; }
QToolButton#sideBtn:hover { background: #f2f3f7; color: #4a5461; }
QToolButton#sideBtn:checked { background: #eef1fc; color: #5e7ce0; font-weight: 700; }

#toolbar, #pagination { background: #ffffff; border-bottom: 1px solid #ececf0; padding: 8px 12px; }
#pagination { border-top: 1px solid #ececf0; border-bottom: none; }
QFrame, QGroupBox { background: #ffffff; border: 1px solid #ececf0; border-radius: 12px; }
QGroupBox { margin-top: 12px; padding: 12px 12px 10px 12px; font-weight: 700; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; color: #777777; }

/* ── 按钮：默认白色圆角药丸 ── */
QPushButton { border: 1px solid #ececf0; background: #ffffff; padding: 6px 14px; border-radius: 999px; min-height: 26px; color: #191919; }
QPushButton:hover { background: #f6f7fb; border-color: #d7dbe6; color: #5e7ce0; }
QPushButton:pressed { background: #eef1fc; border-color: #5e7ce0; }
QPushButton:disabled { color: #b6bcc7; background: #f4f5f8; border-color: #ececf0; }

/* 主行动：periwinkle 实心 */
QPushButton#btnPrimary, QPushButton#btnSync { background: #5e7ce0; color: #ffffff; border: 1px solid #5e7ce0; font-weight: 600; }
QPushButton#btnPrimary:hover, QPushButton#btnSync:hover { background: #4f6ed6; border-color: #4f6ed6; color: #ffffff; }
QPushButton#btnPrimary:pressed, QPushButton#btnSync:pressed { background: #4661c4; border-color: #4661c4; }
QPushButton#btnPrimary:disabled, QPushButton#btnSync:disabled { background: #b9c4ee; border-color: #b9c4ee; color: #f5f7ff; }

/* 刷新：次要白按钮（继承默认样式，仅确保描边） */
QPushButton#btnRefresh { color: #191919; }
QPushButton#btnRefresh:hover { color: #5e7ce0; }

QPushButton#btnDanger { color: #e11d48; border-color: #f4c8d1; background: #ffffff; }
QPushButton#btnDanger:hover { background: #fdeceb; border-color: #eeaab6; }
QPushButton#pgBtn { padding: 2px 10px; min-height: 22px; min-width: 28px; border-radius: 999px; }
QPushButton#pgBtn:disabled { color: #c2c8d2; }

QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox { background: #ffffff; border: 1px solid #ececf0; border-radius: 8px; padding: 5px 9px; selection-background-color: #dfe5fb; selection-color: #191919; }
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus { border: 1px solid #5e7ce0; }
QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled, QComboBox:disabled, QSpinBox:disabled { color: #9ca3af; background: #f4f5f8; }
QComboBox::drop-down { border: none; width: 24px; }

QTableWidget, QTreeWidget, QListWidget { border: 1px solid #ececf0; border-radius: 12px; gridline-color: #f1f2f5; background: #ffffff; alternate-background-color: #fafbfc; selection-background-color: #eef1fc; selection-color: #191919; }
QTableWidget::item, QTreeWidget::item, QListWidget::item { padding: 5px 8px; }
QTableWidget::item:hover, QTreeWidget::item:hover, QListWidget::item:hover { background: #f5f6fd; }
QHeaderView::section { background: #ffffff; border: none; border-bottom: 1px solid #ececf0; padding: 9px 10px; color: #777777; font-weight: 700; }

QTabWidget::pane { border: 1px solid #ececf0; border-radius: 12px; background: #ffffff; top: -1px; }
QTabBar::tab { padding: 8px 18px; background: transparent; border: 1px solid transparent; border-bottom: none; border-top-left-radius: 10px; border-top-right-radius: 10px; margin-right: 4px; color: #777777; }
QTabBar::tab:selected { background: #ffffff; color: #5e7ce0; font-weight: 700; border-color: #ececf0; border-bottom: 1px solid #ffffff; }
QTabBar::tab:hover:!selected { color: #5e7ce0; }

QProgressBar { max-height: 4px; border: none; border-radius: 2px; background: #ececf0; }
QProgressBar::chunk { border-radius: 2px; background: #5e7ce0; }
QToolTip { color: #f5f6f8; background: #191919; border: none; border-radius: 8px; padding: 6px; }
QDialog, QMessageBox { background: #f5f6f8; }
QDialogButtonBox QPushButton { min-width: 78px; }
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
        lay.setSpacing(10)

        lay.addWidget(self._make_sidebar())
        lay.addWidget(self._stack, stretch=1)

    @staticmethod
    def _side_button(text: str, icon_name: str, checkable: bool) -> QToolButton:
        btn = QToolButton()
        btn.setObjectName('sideBtn')
        btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        btn.setIcon(_nav_icon(icon_name))
        btn.setIconSize(QSize(22, 22))
        btn.setText(text)
        btn.setCheckable(checkable)
        btn.setFixedHeight(54)
        btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        btn.setCursor(Qt.PointingHandCursor)
        return btn

    def _make_sidebar(self):
        sidebar = QWidget()
        sidebar.setObjectName('sidebar')
        sidebar.setFixedWidth(80)
        sidebar.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        lay = QVBoxLayout(sidebar)
        lay.setContentsMargins(8, 12, 8, 12)
        lay.setSpacing(6)

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
        ver.setAlignment(Qt.AlignCenter)
        ver.setToolTip(f'客户端版本 v{APP_VERSION}')
        ver.setStyleSheet('color:#9ca3af; font-size:9px; padding:2px 0;')
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

