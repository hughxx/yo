"""WeLink 录制面板（a）：点录制→主窗缩小→右下角浮窗；后台轮询累积；
30 分钟提醒不自动停；停止后进审核对话框，勾选→处理选中(html+md)上报。"""
import time
from datetime import datetime

from PyQt5.QtWidgets import *
from PyQt5.QtCore import Qt, QThread, pyqtSignal

import store
from utils import Worker
from modules.welink import cli, process
from modules.welink.toast import RecordToast
from modules.welink.conv_input import ConvInput


class RecordWorker(QThread):
    tick = pyqtSignal(int, str, int)   # count, first_preview, elapsed_s

    def __init__(self, conv: dict, poll_interval: int = 3):
        super().__init__()
        self._conv = conv
        self._poll = max(1, poll_interval)
        self._running = False
        self._baseline = None          # 起录基准 msgId（只收更新的）
        self._collected = {}

    def stop(self):
        self._running = False

    def results(self) -> list:
        rows = list(self._collected.values())
        rows.sort(key=lambda m: m.get('serverSendTime', 0))
        return rows

    def run(self):
        self._running = True
        t0 = time.monotonic()
        while self._running:
            msgs, err = cli._history_page(self._conv, 50)
            if not err and msgs:
                ids = [int(m.get('msgId', 0)) for m in msgs]
                if self._baseline is None:
                    self._baseline = max(ids)   # 起录时刻之前的不收
                for m in msgs:
                    mid = int(m.get('msgId', 0))
                    if mid > self._baseline:
                        self._collected[mid] = m
            first = ''
            if self._collected:
                oldest = min(self._collected.values(), key=lambda m: m.get('serverSendTime', 0))
                first = oldest.get('content', '') or ''
            self.tick.emit(len(self._collected), first, int(time.monotonic() - t0))
            for _ in range(self._poll * 2):     # 0.5s 粒度，停止更跟手
                if not self._running:
                    break
                time.sleep(0.5)


class RecordPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = store.load_settings()
        self._worker = None
        self._toast = None
        self._reminded = False
        self._recording_conv = None   # 正在录制的会话（self._conv 是输入组件）
        self._workers = []
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)

        hint = QLabel('点「开始录制」后主窗口会缩小，右下角浮窗显示录制状态；'
                      '随时点浮窗「停止录制」结束，然后勾选要的消息处理上报。')
        hint.setWordWrap(True)
        hint.setStyleSheet('color:#666;')
        lay.addWidget(hint)

        row = QHBoxLayout()
        self._conv = ConvInput()
        row.addWidget(self._conv, 1)
        lay.addLayout(row)

        self._btn_rec = QPushButton('开始录制')
        self._btn_rec.setObjectName('btnPrimary')
        self._btn_rec.setMinimumHeight(34)
        lay.addWidget(self._btn_rec)

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(300)
        self._log.setStyleSheet('background:#1e1e1e;color:#d4d4d4;border:none;')
        lay.addWidget(self._log, 1)

        self._btn_rec.clicked.connect(self._start_record)

    # ── 生命周期 ──────────────────────────────────────────
    def activate(self):
        self._settings = store.load_settings()

    def deactivate(self):
        pass

    def on_settings_changed(self, s):
        self._settings = s

    def _say(self, msg):
        self._log.appendPlainText(f'[{datetime.now().strftime("%H:%M:%S")}] {msg}')

    # ── 录制 ──────────────────────────────────────────────
    def _start_record(self):
        conv = self._conv.current()
        if not conv:
            QMessageBox.warning(self, '提示', '请先填会话 id')
            return
        if self._worker:
            return
        self._conv.remember(conv)
        self._recording_conv = conv
        self._reminded = False
        self._worker = RecordWorker(conv, max(1, int(self._settings.get('welinkPollInterval', 3))))
        self._worker.tick.connect(self._on_tick)
        self._worker.start()

        self._toast = RecordToast(conv.get('name', ''))
        self._toast.stop_clicked.connect(self._stop_record)
        self._toast.show_bottom_right()

        self._btn_rec.setEnabled(False)
        self._say(f'开始录制：{conv.get("name", "")}')
        win = self.window()
        if win:
            win.showMinimized()

    def _on_tick(self, count, first, elapsed):
        if self._toast:
            self._toast.update_status(count, first, elapsed)
        if elapsed >= 1800 and not self._reminded:
            self._reminded = True
            QMessageBox.information(self, '录制提醒',
                                    '已经录制 30 分钟了，是不是忘了停止？\n（不会自动停，需要可继续录。）')

    def _stop_record(self):
        if not self._worker:
            return
        self._worker.stop()
        self._worker.wait(3000)
        msgs = self._worker.results()
        self._worker = None
        if self._toast:
            self._toast.close()
            self._toast = None
        self._btn_rec.setEnabled(True)
        win = self.window()
        if win:
            win.showNormal()
            win.activateWindow()
            win.raise_()
        self._say(f'录制结束，共 {len(msgs)} 条')
        if not msgs:
            QMessageBox.information(self, '录制结束', '这段时间没录到新消息。')
            return
        dlg = ReviewDialog(self._settings, self._recording_conv, msgs, parent=self)
        dlg.exec_()


class ReviewDialog(QDialog):
    """录制结果审核：勾选要的消息 → 处理选中(html+md)上报。"""
    def __init__(self, settings, conv, msgs, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._conv = conv
        self._msgs = sorted(msgs, key=lambda m: m.get('serverSendTime', 0))
        self._checked = {int(m.get('msgId', 0)) for m in self._msgs}   # 默认全选
        self._building = False
        self._workers = []
        self.setWindowTitle(f'审核录制 · {conv.get("name", "")}')
        self.setMinimumSize(720, 520)

        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self._btn_all = QPushButton('全选/取消')
        self._btn_all.setFixedWidth(80)
        top.addWidget(self._btn_all)
        top.addStretch()
        self._status = QLabel('')
        self._status.setStyleSheet('color:#666;')
        top.addWidget(self._status)
        self._btn_proc = QPushButton('处理选中')
        self._btn_proc.setObjectName('btnPrimary')
        top.addWidget(self._btn_proc)
        lay.addLayout(top)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(['', '时间', '发送人', '内容'])
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self._table.setColumnWidth(0, 30)
        self._table.setColumnWidth(1, 150)
        self._table.setColumnWidth(2, 110)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.itemChanged.connect(self._on_item_changed)
        lay.addWidget(self._table, 1)

        self._btn_all.clicked.connect(self._toggle_all)
        self._btn_proc.clicked.connect(self._process)
        self._render()

    def _render(self):
        self._building = True
        self._table.setRowCount(0)
        for m in self._msgs:
            r = self._table.rowCount()
            self._table.insertRow(r)
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            mid = int(m.get('msgId', 0))
            chk.setCheckState(Qt.Checked if mid in self._checked else Qt.Unchecked)
            chk.setData(Qt.UserRole, mid)
            self._table.setItem(r, 0, chk)
            t = datetime.fromtimestamp(m.get('serverSendTime', 0) / 1000).strftime('%H:%M:%S') if m.get('serverSendTime') else ''
            self._table.setItem(r, 1, QTableWidgetItem(t))
            self._table.setItem(r, 2, QTableWidgetItem(m.get('sender', '')))
            self._table.setItem(r, 3, QTableWidgetItem((m.get('content', '') or '').replace('\n', ' ')[:120]))
        self._building = False
        self._update()

    def _on_item_changed(self, item):
        if self._building or item.column() != 0:
            return
        mid = item.data(Qt.UserRole)
        if item.checkState() == Qt.Checked:
            self._checked.add(mid)
        else:
            self._checked.discard(mid)
        self._update()

    def _toggle_all(self):
        ids = [int(m.get('msgId', 0)) for m in self._msgs]
        if all(i in self._checked for i in ids):
            self._checked.clear()
        else:
            self._checked = set(ids)
        self._render()

    def _update(self):
        n = len(self._checked)
        self._btn_proc.setText(f'处理选中 ({n})')
        self._btn_proc.setEnabled(n > 0)

    def _process(self):
        sel = [m for m in self._msgs if int(m.get('msgId', 0)) in self._checked]
        if not sel:
            return
        self._btn_proc.setEnabled(False)
        self._status.setText('处理中…')
        conv = self._conv
        settings = self._settings
        start_ms = sel[0].get('serverSendTime', 0)
        end_ms   = sel[-1].get('serverSendTime', 0)
        chat_id  = f'{conv.get("id") or conv.get("account")}_{sel[0].get("msgId")}_rec'

        def _work():
            return process.push_session(settings, conv.get('name', ''), conv.get('id', ''),
                                        sel, start_ms, end_ms, chat_id)

        def _done(res):
            ok, msg = res
            self._status.setText(msg)
            if ok:
                QMessageBox.information(self, '完成', msg)
                self.accept()
            else:
                self._btn_proc.setEnabled(True)

        w = Worker(_work)
        w.ok.connect(_done)
        w.err.connect(lambda m: (self._status.setText(f'失败: {m}'), self._btn_proc.setEnabled(True)))
        w.start()
        self._workers.append(w)
