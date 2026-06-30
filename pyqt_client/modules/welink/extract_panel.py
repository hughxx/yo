"""在线拉取：自填会话 id → 起止时间/关键字粗筛 → 翻页拉取 →
消息清单(勾选/搜索/全选) → 处理选中(html+md)上报。交互对齐邮件「立即处理」。"""
from datetime import datetime

from PyQt5.QtWidgets import *
from PyQt5.QtCore import Qt, QDateTime

import store
from utils import Worker
from modules.welink import cli, process
from modules.welink.conv_input import ConvInput


class ExtractPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = store.load_settings()
        self._msgs = []
        self._checked = set()
        self._workers = []
        self._building = False
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 6)
        lay.setSpacing(6)

        # 第一行：会话输入 + 拉取
        row1 = QHBoxLayout()
        self._conv = ConvInput()
        row1.addWidget(self._conv, 1)
        self._btn_fetch = QPushButton('拉取')
        self._btn_fetch.setObjectName('btnRefresh')
        self._btn_fetch.setFixedWidth(72)
        row1.addWidget(self._btn_fetch)
        lay.addLayout(row1)

        # 第二行：时间范围 + 关键字
        row2 = QHBoxLayout()
        row2.addWidget(QLabel('从'))
        self._dt_start = QDateTimeEdit(QDateTime.currentDateTime().addDays(-1))
        self._dt_start.setDisplayFormat('yyyy-MM-dd HH:mm')
        row2.addWidget(self._dt_start)
        row2.addWidget(QLabel('到'))
        self._dt_end = QDateTimeEdit(QDateTime.currentDateTime())
        self._dt_end.setDisplayFormat('yyyy-MM-dd HH:mm')
        row2.addWidget(self._dt_end)
        self._kw_start = QLineEdit(); self._kw_start.setPlaceholderText('开始关键字(可选)'); self._kw_start.setFixedWidth(130)
        self._kw_end = QLineEdit(); self._kw_end.setPlaceholderText('结束关键字(可选)'); self._kw_end.setFixedWidth(130)
        row2.addWidget(self._kw_start)
        row2.addWidget(self._kw_end)
        row2.addStretch()
        lay.addLayout(row2)

        # 第三行：搜索 + 全选 + 状态 + 处理选中
        row3 = QHBoxLayout()
        self._search = QLineEdit(); self._search.setPlaceholderText('🔍 搜索内容/发送人…'); self._search.setFixedWidth(200)
        row3.addWidget(self._search)
        self._btn_all = QPushButton('全选'); self._btn_all.setObjectName('pgBtn'); self._btn_all.setFixedWidth(56)
        row3.addWidget(self._btn_all)
        row3.addStretch()
        self._status = QLabel('填会话 id 后点「拉取」')
        self._status.setStyleSheet('color:#666;')
        row3.addWidget(self._status)
        self._btn_proc = QPushButton('处理选中 (0)'); self._btn_proc.setObjectName('btnPrimary'); self._btn_proc.setEnabled(False)
        row3.addWidget(self._btn_proc)
        lay.addLayout(row3)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(['', '时间', '发送人', '内容'])
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self._table.setColumnWidth(0, 30); self._table.setColumnWidth(1, 150); self._table.setColumnWidth(2, 110)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.itemChanged.connect(self._on_item_changed)
        lay.addWidget(self._table, 1)

        self._btn_fetch.clicked.connect(self._fetch)
        self._search.textChanged.connect(self._render)
        self._btn_all.clicked.connect(self._toggle_all)
        self._btn_proc.clicked.connect(self._process)

    # ── 生命周期 ──────────────────────────────────────────
    def activate(self):
        self._settings = store.load_settings()

    def deactivate(self):
        pass

    def on_settings_changed(self, s):
        self._settings = s

    # ── 拉取 ──────────────────────────────────────────────
    def _fetch(self):
        conv = self._conv.current()
        if not conv:
            self._status.setText('请先填会话 id')
            return
        since_ms = int(self._dt_start.dateTime().toMSecsSinceEpoch())
        until_ms = int(self._dt_end.dateTime().toMSecsSinceEpoch())
        self._status.setText('拉取中…')
        self._btn_fetch.setEnabled(False)
        self._conv.remember(conv)

        def _work():
            return cli.fetch_range(conv, since_ms=since_ms, until_ms=until_ms)

        def _done(res):
            self._btn_fetch.setEnabled(True)
            msgs, err = res
            msgs = self._apply_keywords(msgs)
            self._msgs = msgs
            self._checked = set()
            self._render()
            self._status.setText(f'拉取 {len(msgs)} 条' + (f'（{err}）' if err else ''))

        w = Worker(_work)
        w.ok.connect(_done)
        w.err.connect(lambda m: (self._btn_fetch.setEnabled(True), self._status.setText(f'拉取失败: {m}')))
        w.start()
        self._workers.append(w)

    def _apply_keywords(self, msgs):
        ks = self._kw_start.text().strip()
        ke = self._kw_end.text().strip()
        if ks:
            for i, m in enumerate(msgs):
                if ks in (m.get('content', '') or ''):
                    msgs = msgs[i:]; break
        if ke:
            for i in range(len(msgs) - 1, -1, -1):
                if ke in (msgs[i].get('content', '') or ''):
                    msgs = msgs[:i + 1]; break
        return msgs

    # ── 渲染/选择 ─────────────────────────────────────────
    def _visible(self):
        q = self._search.text().strip().lower()
        if not q:
            return self._msgs
        return [m for m in self._msgs if q in (m.get('content', '') + ' ' + m.get('sender', '')).lower()]

    def _render(self):
        self._building = True
        self._table.setRowCount(0)
        for m in self._visible():
            r = self._table.rowCount(); self._table.insertRow(r)
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            mid = int(m.get('msgId', 0))
            chk.setCheckState(Qt.Checked if mid in self._checked else Qt.Unchecked)
            chk.setData(Qt.UserRole, mid)
            self._table.setItem(r, 0, chk)
            t = datetime.fromtimestamp(m.get('serverSendTime', 0) / 1000).strftime('%Y-%m-%d %H:%M:%S') if m.get('serverSendTime') else ''
            self._table.setItem(r, 1, QTableWidgetItem(t))
            self._table.setItem(r, 2, QTableWidgetItem(m.get('sender', '')))
            self._table.setItem(r, 3, QTableWidgetItem((m.get('content', '') or '').replace('\n', ' ')[:120]))
        self._building = False
        self._update_proc()

    def _on_item_changed(self, item):
        if self._building or item.column() != 0:
            return
        mid = item.data(Qt.UserRole)
        if item.checkState() == Qt.Checked:
            self._checked.add(mid)
        else:
            self._checked.discard(mid)
        self._update_proc()

    def _toggle_all(self):
        ids = [int(m.get('msgId', 0)) for m in self._visible()]
        if ids and all(i in self._checked for i in ids):
            for i in ids:
                self._checked.discard(i)
        else:
            self._checked.update(ids)
        self._render()

    def _update_proc(self):
        n = len(self._checked)
        self._btn_proc.setText(f'处理选中 ({n})')
        self._btn_proc.setEnabled(n > 0)

    # ── 处理选中 ──────────────────────────────────────────
    def _process(self):
        conv = self._conv.current()
        if not conv:
            return
        sel = [m for m in self._msgs if int(m.get('msgId', 0)) in self._checked]
        if not sel:
            return
        sel.sort(key=lambda m: m.get('serverSendTime', 0))
        if QMessageBox.question(
                self, '处理选中',
                f'将选中的 {len(sel)} 条消息处理成 HTML+MD 上报到服务端，并本地存档。\n确定？',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) != QMessageBox.Yes:
            return
        self._btn_proc.setEnabled(False)
        self._status.setText('处理中…')
        settings = self._settings
        start_ms = sel[0].get('serverSendTime', 0)
        end_ms   = sel[-1].get('serverSendTime', 0)
        chat_id  = f'{conv.get("id") or conv.get("account")}_{sel[0].get("msgId")}_x'
        name, gid = conv.get('name', ''), conv.get('id', '')

        def _work():
            return process.push_session(settings, name, gid, sel, start_ms, end_ms, chat_id)

        def _done(res):
            ok, msg = res
            self._status.setText(msg)
            self._update_proc()

        w = Worker(_work)
        w.ok.connect(_done)
        w.err.connect(lambda m: (self._status.setText(f'处理失败: {m}'), self._update_proc()))
        w.start()
        self._workers.append(w)
