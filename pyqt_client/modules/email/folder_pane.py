"""左侧文件夹树：纯勾选。勾选的文件夹 = 处理 / 定时范围（参考 standalone FolderPane）。"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTreeWidget, QTreeWidgetItem,
)
from PyQt5.QtCore import Qt, pyqtSignal

from modules.email import outlook
import store
from utils import Worker


class FolderPane(QWidget):
    scopeChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('folderPane')
        self.setFixedWidth(220)
        self._scope = set(store.load_settings().get('scanFolders', []))
        self._building = False
        self._loading = False
        self._workers = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(4)

        head = QHBoxLayout()
        title = QLabel('文件夹')
        title.setStyleSheet('font-weight:bold;')
        self._btn_reload = QPushButton('刷新')
        self._btn_reload.setObjectName('pgBtn')
        self._btn_reload.setFixedWidth(48)
        head.addWidget(title)
        head.addStretch()
        head.addWidget(self._btn_reload)
        lay.addLayout(head)

        sub = QLabel('勾选 = 处理 / 定时范围')
        sub.setStyleSheet('color:#888;font-size:11px;')
        lay.addWidget(sub)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setAlternatingRowColors(True)
        self._tree.itemChanged.connect(self._on_item_changed)
        lay.addWidget(self._tree, 1)

        self._hint = QLabel('点「刷新」加载 Outlook 文件夹')
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet('color:#aaa;font-size:11px;')
        lay.addWidget(self._hint)

        self._btn_reload.clicked.connect(self.reload)

    # ── 加载 ──────────────────────────────────────────────
    def reload(self):
        if self._loading:
            return
        self._loading = True
        self._btn_reload.setEnabled(False)
        self._hint.setText('加载中…')

        def _done(paths):
            self._loading = False
            self._btn_reload.setEnabled(True)
            self._build_tree(paths or [])
            self._hint.setText('' if paths else '没有可用文件夹')

        def _fail(msg):
            self._loading = False
            self._btn_reload.setEnabled(True)
            self._hint.setText(f'加载失败：{msg}')

        w = Worker(outlook.folder_list)
        w.ok.connect(_done)
        w.err.connect(_fail)
        w.start()
        self._workers.append(w)

    def _build_tree(self, paths):
        self._building = True
        self._tree.clear()
        nodes = {}
        for p in paths:
            prefix = ''
            parent = None
            for part in p.split('\\'):
                prefix = f'{prefix}\\{part}' if prefix else part
                if prefix in nodes:
                    parent = nodes[prefix]
                    continue
                item = QTreeWidgetItem([part])
                item.setData(0, Qt.UserRole, prefix)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(0, Qt.Checked if prefix in self._scope else Qt.Unchecked)
                if parent is None:
                    self._tree.addTopLevelItem(item)
                else:
                    parent.addChild(item)
                nodes[prefix] = item
                parent = item
        self._tree.expandToDepth(0)
        self._building = False

    # ── 勾选 ──────────────────────────────────────────────
    def _on_item_changed(self, item, _col):
        if self._building:
            return
        path = item.data(0, Qt.UserRole)
        if item.checkState(0) == Qt.Checked:
            self._scope.add(path)
        else:
            self._scope.discard(path)
        s = store.load_settings()
        s['scanFolders'] = sorted(self._scope)
        store.save_settings(s)
        self.scopeChanged.emit()
