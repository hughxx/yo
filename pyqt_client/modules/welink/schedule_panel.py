"""聊天记录定时采集：配 会话(群/人) + 规则，每天某时刻自动截取当天记录并直推。

规则两类，每类可多条：
  · 开始结束：start_kw … end_kw 配对，取每对之间；一天多对 → 多段，各自成条推送。
  · 总结命令：命中 summary_cmd 的消息里带「名 工号 起始时间 [名 工号 结束时间]」，取该时间段。
"""
import re
import unicodedata
from datetime import datetime

from PyQt5.QtWidgets import *
from PyQt5.QtCore import Qt, QTimer, QTime

import store
from utils import Worker
from modules.welink import cli, process
from modules.welink.conv_input import ConvInput

_SPACES = re.compile('[   　​]')


def _norm(t: str) -> str:
    return _SPACES.sub(' ', unicodedata.normalize('NFKC', t or ''))


def _parse_summary(cmd: str, norm: str):
    """总结命令后接：名1 工号1 date time [名2 工号2 date time] → (start_dt, end_dt|None) 或 None。"""
    if cmd not in norm:
        return None
    parts = norm[norm.index(cmd) + len(cmd):].strip().split()
    try:
        if len(parts) >= 8:
            a = datetime.strptime(f'{parts[2]} {parts[3]}', '%Y-%m-%d %H:%M')
            b = datetime.strptime(f'{parts[6]} {parts[7]}', '%Y-%m-%d %H:%M')
            return (a, b) if a <= b else (b, a)
        if len(parts) >= 4:
            a = datetime.strptime(f'{parts[2]} {parts[3]}', '%Y-%m-%d %H:%M')
            return (a, None)
    except ValueError:
        pass
    return None


def _pair_segments(msgs: list, start_kw: str, end_kw: str) -> list:
    """按 start_kw…end_kw 配对切分，返回 [[msg,...], ...]。有开始没结束 → 截到末尾。"""
    segs, i, n = [], 0, len(msgs)
    while i < n:
        while i < n and start_kw not in _norm(msgs[i].get('content', '')):
            i += 1
        if i >= n:
            break
        s = i
        i += 1
        while i < n and end_kw not in _norm(msgs[i].get('content', '')):
            i += 1
        if i >= n:
            segs.append(msgs[s:])
            break
        segs.append(msgs[s:i + 1])
        i += 1
    return segs


class SchedulePanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = store.load_settings()
        # 只认新结构(带 type)，旧版本残留的规则丢弃，避免 KeyError
        self._rules = [r for r in self._settings.get('welinkScheduleRules', [])
                       if r.get('type') in ('startend', 'summary')]
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

        hint = QLabel('到点自动采集下方各规则的当天聊天记录，按规则截取后处理成 html+md 直推(不审核)。')
        hint.setWordWrap(True); hint.setStyleSheet('color:#666;')
        lay.addWidget(hint)

        # 时刻 + 启停
        row = QHBoxLayout()
        row.addWidget(QLabel('每天'))
        self._time = QTimeEdit(); self._time.setDisplayFormat('HH:mm'); self._time.setMaximumWidth(90)
        try:
            hh, mm = (self._settings.get('welinkScheduleTime', '02:00')).split(':')
            self._time.setTime(QTime(int(hh), int(mm)))
        except Exception:
            self._time.setTime(QTime(2, 0))
        row.addWidget(self._time)
        row.addWidget(QLabel('采集一次'))
        row.addStretch()
        self._btn_timer = QPushButton('启动定时'); self._btn_timer.setFixedWidth(90)
        self._btn_timer.clicked.connect(self._toggle)
        row.addWidget(self._btn_timer)
        lay.addLayout(row)

        # 加规则：会话 + 类型 + 参数
        add1 = QHBoxLayout()
        self._conv = ConvInput()
        add1.addWidget(self._conv, 1)
        lay.addLayout(add1)

        add2 = QHBoxLayout()
        add2.addWidget(QLabel('类型'))
        self._type = QComboBox(); self._type.addItems(['开始结束', '总结命令']); self._type.setFixedWidth(96)
        add2.addWidget(self._type)
        self._kw_start = QLineEdit(); self._kw_start.setPlaceholderText('开始关键字'); self._kw_start.setFixedWidth(120)
        self._kw_end = QLineEdit(); self._kw_end.setPlaceholderText('结束关键字'); self._kw_end.setFixedWidth(120)
        self._summary = QLineEdit(); self._summary.setPlaceholderText('总结命令(如 @云见 总结经验)'); self._summary.setFixedWidth(200)
        add2.addWidget(self._kw_start); add2.addWidget(self._kw_end); add2.addWidget(self._summary)
        self._btn_add = QPushButton('添加规则'); self._btn_add.setFixedWidth(80)
        add2.addWidget(self._btn_add)
        add2.addStretch()
        lay.addLayout(add2)
        self._type.currentTextChanged.connect(self._sync_fields)
        self._btn_add.clicked.connect(self._add_rule)
        self._sync_fields()

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(['会话', '类型', '参数'])
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self._table.setColumnWidth(0, 200); self._table.setColumnWidth(1, 90)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.verticalHeader().setVisible(False)
        lay.addWidget(self._table, 1)

        bot = QHBoxLayout()
        self._btn_del = QPushButton('删除选中规则'); self._btn_del.setObjectName('btnDanger')
        self._btn_del.clicked.connect(self._del_rule)
        bot.addWidget(self._btn_del)
        bot.addStretch()
        self._status = QLabel('未启动'); self._status.setStyleSheet('color:#666;')
        bot.addWidget(self._status)
        lay.addLayout(bot)

        self._log = QPlainTextEdit(); self._log.setReadOnly(True); self._log.setMaximumBlockCount(300)
        self._log.setFixedHeight(110); self._log.setStyleSheet('background:#1e1e1e;color:#d4d4d4;border:none;')
        lay.addWidget(self._log)

    def _sync_fields(self):
        is_se = self._type.currentText() == '开始结束'
        self._kw_start.setVisible(is_se); self._kw_end.setVisible(is_se)
        self._summary.setVisible(not is_se)

    # ── 生命周期 ──────────────────────────────────────────
    def activate(self):
        self._settings = store.load_settings()

    def deactivate(self):
        pass

    def on_settings_changed(self, s):
        self._settings = s

    def _say(self, m):
        self._log.appendPlainText(f'[{datetime.now().strftime("%H:%M:%S")}] {m}')

    # ── 规则增删 ──────────────────────────────────────────
    def _add_rule(self):
        conv = self._conv.current()
        if not conv:
            QMessageBox.warning(self, '提示', '请先填会话 id'); return
        if self._type.currentText() == '开始结束':
            ks, ke = self._kw_start.text().strip(), self._kw_end.text().strip()
            if not ks or not ke:
                QMessageBox.warning(self, '提示', '开始/结束关键字都要填'); return
            rule = {'kind': conv['kind'], 'target': conv.get('id') or conv.get('account'),
                    'name': conv['name'], 'type': 'startend', 'start_kw': ks, 'end_kw': ke}
        else:
            cmd = self._summary.text().strip()
            if not cmd:
                QMessageBox.warning(self, '提示', '总结命令要填'); return
            rule = {'kind': conv['kind'], 'target': conv.get('id') or conv.get('account'),
                    'name': conv['name'], 'type': 'summary', 'summary_cmd': cmd}
        self._conv.remember(conv)
        self._rules.append(rule)
        self._kw_start.clear(); self._kw_end.clear(); self._summary.clear()
        self._persist(); self._render_rules()

    def _del_rule(self):
        r = self._table.currentRow()
        if 0 <= r < len(self._rules):
            self._rules.pop(r); self._persist(); self._render_rules()

    def _render_rules(self):
        self._table.setRowCount(0)
        for rule in self._rules:
            r = self._table.rowCount(); self._table.insertRow(r)
            tag = '群' if rule.get('kind') == 'group' else '人'
            self._table.setItem(r, 0, QTableWidgetItem(f'[{tag}] {rule.get("name","")}'))
            if rule.get('type') == 'startend':
                self._table.setItem(r, 1, QTableWidgetItem('开始结束'))
                self._table.setItem(r, 2, QTableWidgetItem(f'{rule.get("start_kw","")} … {rule.get("end_kw","")}'))
            else:
                self._table.setItem(r, 1, QTableWidgetItem('总结命令'))
                self._table.setItem(r, 2, QTableWidgetItem(rule.get('summary_cmd', '')))

    def _persist(self):
        self._settings = store.load_settings()
        self._settings['welinkScheduleRules'] = self._rules
        store.save_settings(self._settings)

    # ── 启停定时 ──────────────────────────────────────────
    def _toggle(self):
        if self._monitoring:
            self._timer.stop(); self._monitoring = False
            self._btn_timer.setText('启动定时'); self._status.setText('已停止')
            self._say('定时采集已停止'); return
        if not self._rules:
            QMessageBox.warning(self, '提示', '请先添加至少一条规则'); return
        t = self._time.time().toString('HH:mm')
        self._settings = store.load_settings()
        self._settings['welinkScheduleTime'] = t
        self._settings['welinkScheduleRules'] = self._rules
        store.save_settings(self._settings)
        now = datetime.now()
        self._fired_date = now.strftime('%Y-%m-%d') if now.strftime('%H:%M') >= t else ''
        self._timer.start(30 * 1000)
        self._monitoring = True
        self._btn_timer.setText('停止定时'); self._status.setText(f'已启动 · 每天 {t}')
        self._say(f'定时采集已启动：每天 {t}，{len(self._rules)} 条规则')

    def _on_tick(self):
        now = datetime.now()
        today = now.strftime('%Y-%m-%d')
        if now.strftime('%H:%M') >= self._time.time().toString('HH:mm') and self._fired_date != today:
            self._fired_date = today
            self._run_all(today)

    def _run_all(self, date_str):
        self._say(f'开始采集 {date_str} …')
        since_ms = int(datetime.strptime(date_str, '%Y-%m-%d').timestamp() * 1000)
        settings = store.load_settings()
        for rule in list(self._rules):
            self._capture(rule, since_ms, date_str, settings)

    def _capture(self, rule, since_ms, date_str, settings):
        conv = {'kind': rule.get('kind', 'group'), 'id': rule.get('target', ''),
                'account': rule.get('target', ''), 'name': rule.get('name', '')}
        conv['id'] = rule.get('target', '') if rule.get('kind') == 'group' else ''
        conv['account'] = rule.get('target', '') if rule.get('kind') == 'p2p' else ''
        gname = rule.get('name', '')

        def _work():
            msgs, err = cli.fetch_range(conv, since_ms=since_ms)
            if err and not msgs:
                return (gname, 0, 0, f'拉取失败: {err}')
            if rule['type'] == 'startend':
                segs = _pair_segments(msgs, rule['start_kw'], rule['end_kw'])
            else:
                cmd = rule['summary_cmd']
                segs = []
                for m in msgs:
                    pr = _parse_summary(cmd, _norm(m.get('content', '')))
                    if not pr:
                        continue
                    s_dt, e_dt = pr
                    s_ms = int(s_dt.timestamp() * 1000)
                    e_ms = int(e_dt.timestamp() * 1000) if e_dt else m.get('serverSendTime', 0)
                    seg = [x for x in msgs if s_ms <= x.get('serverSendTime', 0) <= e_ms]
                    if seg:
                        segs.append(seg)
            pushed = 0
            for idx, seg in enumerate(segs):
                if not seg:
                    continue
                start_ms = seg[0].get('serverSendTime', 0)
                end_ms   = seg[-1].get('serverSendTime', 0)
                chat_id  = f'{rule.get("target","")}_{date_str}_{rule["type"]}_{idx}'
                ok, _ = process.push_session(settings, gname, conv['id'], seg, start_ms, end_ms, chat_id, is_daily=True)
                if ok:
                    pushed += 1
            return (gname, pushed, len(segs), '')

        def _done(res):
            gname, pushed, total, err = res
            if err:
                self._say(f'[{gname}] {err}')
            else:
                self._say(f'[{gname}] 命中 {total} 段，推送 {pushed} 段')

        w = Worker(_work)
        w.ok.connect(_done)
        w.err.connect(lambda m: self._say(f'[{gname}] 异常: {m}'))
        w.start()
        self._workers.append(w)
