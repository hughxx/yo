"""WeLink 定时采集（c）：按规则(群+可选起止关键字) + 每天某时刻，
到点自动翻页拉取当天记录 → 处理 → 直推（不审核）。仅群聊。交互对齐邮件「启动定时」。"""
from datetime import datetime

from PyQt5.QtWidgets import *
from PyQt5.QtCore import Qt, QTimer, QTime

import store
from utils import Worker
from modules.welink import cli, process


class SchedulePanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = store.load_settings()
        self._rules = list(self._settings.get('welinkScheduleRules', []))
        self._monitoring = False
        self._fired_date = ''
        self._workers = []
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._build_ui()
        self._render_rules()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        hint = QLabel('到点自动采集下方各群当天聊天记录，处理成 html+md 直接上报（不进审核）。'
                      '起止关键字可选，留空=当天全部。仅支持群聊。')
        hint.setWordWrap(True)
        hint.setStyleSheet('color:#666;')
        lay.addWidget(hint)

        # 时刻 + 启停
        row = QHBoxLayout()
        row.addWidget(QLabel('每天'))
        self._time = QTimeEdit()
        self._time.setDisplayFormat('HH:mm')
        try:
            hh, mm = (self._settings.get('welinkScheduleTime', '02:00')).split(':')
            self._time.setTime(QTime(int(hh), int(mm)))
        except Exception:
            self._time.setTime(QTime(2, 0))
        self._time.setMaximumWidth(90)
        row.addWidget(self._time)
        row.addWidget(QLabel('采集一次'))
        row.addStretch()
        self._btn_timer = QPushButton('启动定时')
        self._btn_timer.setFixedWidth(90)
        self._btn_timer.clicked.connect(self._toggle)
        row.addWidget(self._btn_timer)
        lay.addLayout(row)

        # 加规则
        addrow = QHBoxLayout()
        self._combo = QComboBox()
        self._combo.setMinimumWidth(220)
        self._btn_reload = QPushButton('刷新群')
        self._btn_reload.setFixedWidth(64)
        self._kw_start = QLineEdit(); self._kw_start.setPlaceholderText('开始关键字(可选)'); self._kw_start.setFixedWidth(120)
        self._kw_end = QLineEdit(); self._kw_end.setPlaceholderText('结束关键字(可选)'); self._kw_end.setFixedWidth(120)
        self._btn_add = QPushButton('添加'); self._btn_add.setFixedWidth(56)
        addrow.addWidget(self._combo, 1)
        addrow.addWidget(self._btn_reload)
        addrow.addWidget(self._kw_start)
        addrow.addWidget(self._kw_end)
        addrow.addWidget(self._btn_add)
        lay.addLayout(addrow)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(['群', 'group_id', '开始关键字', '结束关键字'])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.verticalHeader().setVisible(False)
        lay.addWidget(self._table, 1)

        botrow = QHBoxLayout()
        self._btn_del = QPushButton('删除选中规则')
        self._btn_del.setObjectName('btnDanger')
        botrow.addWidget(self._btn_del)
        botrow.addStretch()
        self._status = QLabel('未启动')
        self._status.setStyleSheet('color:#666;')
        botrow.addWidget(self._status)
        lay.addLayout(botrow)

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(300)
        self._log.setFixedHeight(110)
        self._log.setStyleSheet('background:#1e1e1e;color:#d4d4d4;border:none;')
        lay.addWidget(self._log)

        self._btn_reload.clicked.connect(self._load_groups)
        self._btn_add.clicked.connect(self._add_rule)
        self._btn_del.clicked.connect(self._del_rule)

    # ── 生命周期 ──────────────────────────────────────────
    def activate(self):
        self._settings = store.load_settings()
        if self._combo.count() == 0:
            self._load_groups()

    def deactivate(self):
        pass

    def on_settings_changed(self, s):
        self._settings = s

    def _say(self, m):
        self._log.appendPlainText(f'[{datetime.now().strftime("%H:%M:%S")}] {m}')

    # ── 群列表 ────────────────────────────────────────────
    def _load_groups(self):
        w = Worker(cli.recent_conversations, 60)
        w.ok.connect(self._on_groups)
        w.err.connect(lambda m: self._say(f'群加载失败: {m}'))
        w.start()
        self._workers.append(w)

    def _on_groups(self, res):
        convs, err = res
        self._combo.clear()
        for c in convs:
            if c['kind'] == 'group':            # 仅群聊
                self._combo.addItem(c['name'], c)
        self._say(f'已加载 {self._combo.count()} 个群')

    # ── 规则增删 ──────────────────────────────────────────
    def _add_rule(self):
        c = self._combo.currentData()
        if not c:
            return
        self._rules.append({
            'group_id':   c['id'],
            'group_name': c['name'],
            'start_kw':   self._kw_start.text().strip(),
            'end_kw':     self._kw_end.text().strip(),
        })
        self._kw_start.clear(); self._kw_end.clear()
        self._persist(); self._render_rules()

    def _del_rule(self):
        r = self._table.currentRow()
        if 0 <= r < len(self._rules):
            self._rules.pop(r)
            self._persist(); self._render_rules()

    def _render_rules(self):
        self._table.setRowCount(0)
        for rule in self._rules:
            r = self._table.rowCount()
            self._table.insertRow(r)
            self._table.setItem(r, 0, QTableWidgetItem(rule.get('group_name', '')))
            self._table.setItem(r, 1, QTableWidgetItem(str(rule.get('group_id', ''))))
            self._table.setItem(r, 2, QTableWidgetItem(rule.get('start_kw', '')))
            self._table.setItem(r, 3, QTableWidgetItem(rule.get('end_kw', '')))

    def _persist(self):
        self._settings = store.load_settings()
        self._settings['welinkScheduleRules'] = self._rules
        store.save_settings(self._settings)

    # ── 启停定时 ──────────────────────────────────────────
    def _toggle(self):
        if self._monitoring:
            self._timer.stop()
            self._monitoring = False
            self._btn_timer.setText('启动定时')
            self._status.setText('已停止')
            self._say('定时采集已停止')
            return
        if not self._rules:
            QMessageBox.warning(self, '提示', '请先添加至少一条群规则')
            return
        t = self._time.time().toString('HH:mm')
        self._settings = store.load_settings()
        self._settings['welinkScheduleTime'] = t
        self._settings['welinkScheduleRules'] = self._rules
        store.save_settings(self._settings)
        now = datetime.now()
        self._fired_date = now.strftime('%Y-%m-%d') if now.strftime('%H:%M') >= t else ''
        self._timer.start(30 * 1000)
        self._monitoring = True
        self._btn_timer.setText('停止定时')
        self._status.setText(f'已启动 · 每天 {t}')
        self._say(f'定时采集已启动：每天 {t}，{len(self._rules)} 条群规则')

    def _on_tick(self):
        now = datetime.now()
        today = now.strftime('%Y-%m-%d')
        target = self._time.time().toString('HH:mm')
        if now.strftime('%H:%M') >= target and self._fired_date != today:
            self._fired_date = today
            self._run_all(today)

    def _run_all(self, date_str):
        self._say(f'开始采集 {date_str} 各群当天记录…')
        day_start = datetime.strptime(date_str, '%Y-%m-%d')
        since_ms = int(day_start.timestamp() * 1000)
        settings = store.load_settings()
        for rule in list(self._rules):
            self._capture_one(rule, since_ms, date_str, settings)

    def _capture_one(self, rule, since_ms, date_str, settings):
        gid = str(rule.get('group_id', ''))
        gname = rule.get('group_name', gid)
        conv = {'kind': 'group', 'id': gid, 'account': '', 'name': gname}
        ks, ke = rule.get('start_kw', ''), rule.get('end_kw', '')

        def _work():
            msgs, err = cli.fetch_range(conv, since_ms=since_ms)
            if err and not msgs:
                return False, f'拉取失败: {err}'
            if ks:
                for i, m in enumerate(msgs):
                    if ks in (m.get('content', '') or ''):
                        msgs = msgs[i:]; break
            if ke:
                for i in range(len(msgs) - 1, -1, -1):
                    if ke in (msgs[i].get('content', '') or ''):
                        msgs = msgs[:i + 1]; break
            if not msgs:
                return True, '当天无消息'
            start_ms = msgs[0].get('serverSendTime', 0)
            end_ms   = msgs[-1].get('serverSendTime', 0)
            chat_id  = f'{gid}_{date_str}_daily'
            return process.push_session(settings, gname, gid, msgs, start_ms, end_ms, chat_id, is_daily=True)

        def _done(res):
            ok, msg = res
            self._say(f'[{gname}] {msg}')

        w = Worker(_work)
        w.ok.connect(_done)
        w.err.connect(lambda m: self._say(f'[{gname}] 异常: {m}'))
        w.start()
        self._workers.append(w)
