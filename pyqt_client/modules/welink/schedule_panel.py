"""聊天记录定时采集：三块 —— ①定时时间 ②群组/用户列表 ③规则列表；右上角启动定时。
到点对「每个群组」用「每条规则」截取当天记录并直推(不审核)。规则两类，每类可多条。

  · 开始结束：start_kw … end_kw 配对切分，一天多对 → 多段。
  · 总结命令：命中 summary_cmd 的消息里带「名 工号 起始时间 [名 工号 结束时间]」，取该时段。
"""
import re
import unicodedata
from datetime import datetime

from PyQt5.QtWidgets import *
from PyQt5.QtCore import Qt, QTimer, QTime

import store
from utils import Worker
from modules.welink import cli, process

_SPACES = re.compile('[   　​]')


def _norm(t: str) -> str:
    return _SPACES.sub(' ', unicodedata.normalize('NFKC', t or ''))


def _parse_summary(cmd: str, norm: str):
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


# ── 规则编辑弹窗 ──────────────────────────────────────────
class _RuleDialog(QDialog):
    def __init__(self, rule=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle('编辑规则' if rule else '添加规则')
        self.setFixedWidth(420)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        lay = QVBoxLayout(self)

        trow = QHBoxLayout()
        trow.addWidget(QLabel('类型'))
        self._type = QComboBox(); self._type.addItems(['开始结束', '总结命令'])
        trow.addWidget(self._type); trow.addStretch()
        lay.addLayout(trow)

        form = QFormLayout()
        self._start = QLineEdit(); self._start.setPlaceholderText('开始关键字/命令')
        self._end = QLineEdit(); self._end.setPlaceholderText('结束关键字/命令')
        self._summary = QLineEdit(); self._summary.setPlaceholderText('总结命令，如 @云见 总结经验')
        form.addRow('开始', self._start)
        form.addRow('结束', self._end)
        form.addRow('总结命令', self._summary)
        lay.addLayout(form)
        self._lbl_start = form.labelForField(self._start)
        self._lbl_end = form.labelForField(self._end)
        self._lbl_sum = form.labelForField(self._summary)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._on_ok); btns.rejected.connect(self.reject)
        lay.addWidget(btns)

        self._type.currentTextChanged.connect(self._sync)
        if rule:
            self._type.setCurrentText('总结命令' if rule.get('type') == 'summary' else '开始结束')
            self._start.setText(rule.get('start_kw', ''))
            self._end.setText(rule.get('end_kw', ''))
            self._summary.setText(rule.get('summary_cmd', ''))
        self._sync()

    def _sync(self):
        se = self._type.currentText() == '开始结束'
        for w in (self._start, self._end, self._lbl_start, self._lbl_end):
            w.setVisible(se)
        for w in (self._summary, self._lbl_sum):
            w.setVisible(not se)

    def _on_ok(self):
        if self._type.currentText() == '开始结束':
            if not self._start.text().strip() or not self._end.text().strip():
                QMessageBox.warning(self, '提示', '开始/结束都要填'); return
        else:
            if not self._summary.text().strip():
                QMessageBox.warning(self, '提示', '总结命令要填'); return
        self.accept()

    def get_rule(self) -> dict:
        if self._type.currentText() == '开始结束':
            return {'type': 'startend', 'start_kw': self._start.text().strip(), 'end_kw': self._end.text().strip()}
        return {'type': 'summary', 'summary_cmd': self._summary.text().strip()}


class SchedulePanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        s = store.load_settings()
        self._groups = list(s.get('welinkScheduleGroups', []))
        self._rules = [r for r in s.get('welinkScheduleRules', []) if r.get('type') in ('startend', 'summary')]
        self._monitoring = False
        self._fired_date = ''
        self._workers = []
        self._timer = QTimer(self); self._timer.timeout.connect(self._on_tick)
        self._build_ui()
        self._render_groups(); self._render_rules()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 8)
        root.setSpacing(6)

        # 顶部：标题 + 启动定时(右上角)
        hdr = QHBoxLayout()
        hdr.addWidget(QLabel('聊天记录定时采集'))
        hdr.addStretch()
        self._status = QLabel('未启动'); self._status.setStyleSheet('color:#888;')
        hdr.addWidget(self._status)
        self._btn_timer = QPushButton('启动定时'); self._btn_timer.setObjectName('btnSync'); self._btn_timer.setFixedWidth(90)
        self._btn_timer.clicked.connect(self._toggle)
        hdr.addWidget(self._btn_timer)
        root.addLayout(hdr)

        # ① 定时时间
        root.addWidget(self._section_title('① 定时时间'))
        trow = QHBoxLayout()
        trow.addWidget(QLabel('每天'))
        self._time = QTimeEdit(); self._time.setDisplayFormat('HH:mm'); self._time.setMaximumWidth(90)
        try:
            hh, mm = (store.load_settings().get('welinkScheduleTime', '02:00')).split(':')
            self._time.setTime(QTime(int(hh), int(mm)))
        except Exception:
            self._time.setTime(QTime(2, 0))
        trow.addWidget(self._time); trow.addWidget(QLabel('采集一次')); trow.addStretch()
        root.addLayout(trow)

        # ② 群组/用户
        root.addWidget(self._section_title('② 群组 / 用户（采集对象）'))
        self._grp_table = QTableWidget(0, 3)
        self._grp_table.setHorizontalHeaderLabels(['类型', 'ID', '名称'])
        self._grp_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self._grp_table.setColumnWidth(0, 60); self._grp_table.setColumnWidth(1, 180)
        self._grp_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._grp_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._grp_table.verticalHeader().setVisible(False)
        self._grp_table.setMaximumHeight(150)
        root.addWidget(self._grp_table)
        grow = QHBoxLayout()
        self._g_kind = QComboBox(); self._g_kind.addItems(['群', '个人']); self._g_kind.setFixedWidth(64)
        self._g_id = QLineEdit(); self._g_id.setPlaceholderText('群 group_id / 个人工号'); self._g_id.setFixedWidth(200)
        self._g_name = QLineEdit(); self._g_name.setPlaceholderText('名称(可选)'); self._g_name.setFixedWidth(140)
        b_gadd = QPushButton('+ 添加'); b_gadd.setFixedWidth(60); b_gadd.clicked.connect(self._add_group)
        b_gdel = QPushButton('删除'); b_gdel.setFixedWidth(48); b_gdel.clicked.connect(self._del_group)
        for w in (self._g_kind, self._g_id, self._g_name, b_gadd, b_gdel):
            grow.addWidget(w)
        grow.addStretch()
        root.addLayout(grow)

        # ③ 规则
        root.addWidget(self._section_title('③ 规则（应用到上面所有对象）'))
        self._rule_table = QTableWidget(0, 2)
        self._rule_table.setHorizontalHeaderLabels(['类型', '参数'])
        self._rule_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._rule_table.setColumnWidth(0, 90)
        self._rule_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._rule_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._rule_table.verticalHeader().setVisible(False)
        self._rule_table.setMaximumHeight(140)
        self._rule_table.doubleClicked.connect(self._edit_rule)
        root.addWidget(self._rule_table)
        rrow = QHBoxLayout()
        b_radd = QPushButton('+ 添加规则'); b_radd.setFixedWidth(84); b_radd.clicked.connect(self._add_rule)
        b_redit = QPushButton('编辑'); b_redit.setFixedWidth(48); b_redit.clicked.connect(self._edit_rule)
        b_rdel = QPushButton('删除'); b_rdel.setObjectName('btnDanger'); b_rdel.setFixedWidth(48); b_rdel.clicked.connect(self._del_rule)
        for w in (b_radd, b_redit, b_rdel):
            rrow.addWidget(w)
        rrow.addStretch()
        root.addLayout(rrow)

        self._log = QPlainTextEdit(); self._log.setReadOnly(True); self._log.setMaximumBlockCount(300)
        self._log.setFixedHeight(90); self._log.setStyleSheet('background:#1e1e1e;color:#d4d4d4;border:none;')
        root.addWidget(self._log)

    @staticmethod
    def _section_title(t):
        lbl = QLabel(t); lbl.setStyleSheet('font-weight:bold;color:#333;margin-top:4px;')
        return lbl

    # ── 生命周期 ──────────────────────────────────────────
    def activate(self): pass
    def deactivate(self): pass
    def on_settings_changed(self, s): pass

    def _say(self, m):
        self._log.appendPlainText(f'[{datetime.now().strftime("%H:%M:%S")}] {m}')

    # ── 群组 ──────────────────────────────────────────────
    def _add_group(self):
        gid = self._g_id.text().strip()
        if not gid:
            QMessageBox.warning(self, '提示', 'ID 不能为空'); return
        kind = 'group' if self._g_kind.currentText() == '群' else 'p2p'
        if any(g['kind'] == kind and g['target'] == gid for g in self._groups):
            return
        self._groups.append({'kind': kind, 'target': gid, 'name': self._g_name.text().strip() or gid})
        self._g_id.clear(); self._g_name.clear()
        self._persist(); self._render_groups()

    def _del_group(self):
        r = self._grp_table.currentRow()
        if 0 <= r < len(self._groups):
            self._groups.pop(r); self._persist(); self._render_groups()

    def _render_groups(self):
        self._grp_table.setRowCount(0)
        for g in self._groups:
            r = self._grp_table.rowCount(); self._grp_table.insertRow(r)
            self._grp_table.setItem(r, 0, QTableWidgetItem('群' if g['kind'] == 'group' else '个人'))
            self._grp_table.setItem(r, 1, QTableWidgetItem(g['target']))
            self._grp_table.setItem(r, 2, QTableWidgetItem(g.get('name', '')))

    # ── 规则 ──────────────────────────────────────────────
    def _add_rule(self):
        dlg = _RuleDialog(parent=self)
        if dlg.exec_() == QDialog.Accepted:
            self._rules.append(dlg.get_rule()); self._persist(); self._render_rules()

    def _edit_rule(self):
        r = self._rule_table.currentRow()
        if not (0 <= r < len(self._rules)):
            return
        dlg = _RuleDialog(rule=self._rules[r], parent=self)
        if dlg.exec_() == QDialog.Accepted:
            self._rules[r] = dlg.get_rule(); self._persist(); self._render_rules()

    def _del_rule(self):
        r = self._rule_table.currentRow()
        if 0 <= r < len(self._rules):
            self._rules.pop(r); self._persist(); self._render_rules()

    def _render_rules(self):
        self._rule_table.setRowCount(0)
        for rule in self._rules:
            r = self._rule_table.rowCount(); self._rule_table.insertRow(r)
            if rule['type'] == 'startend':
                self._rule_table.setItem(r, 0, QTableWidgetItem('开始结束'))
                self._rule_table.setItem(r, 1, QTableWidgetItem(f'{rule.get("start_kw","")} … {rule.get("end_kw","")}'))
            else:
                self._rule_table.setItem(r, 0, QTableWidgetItem('总结命令'))
                self._rule_table.setItem(r, 1, QTableWidgetItem(rule.get('summary_cmd', '')))

    def _persist(self):
        s = store.load_settings()
        s['welinkScheduleGroups'] = self._groups
        s['welinkScheduleRules'] = self._rules
        store.save_settings(s)

    # ── 启停 ──────────────────────────────────────────────
    def _toggle(self):
        if self._monitoring:
            self._timer.stop(); self._monitoring = False
            self._btn_timer.setText('启动定时'); self._status.setText('已停止')
            self._say('定时采集已停止'); return
        if not self._groups or not self._rules:
            QMessageBox.warning(self, '提示', '请先添加至少一个对象和一条规则'); return
        t = self._time.time().toString('HH:mm')
        s = store.load_settings()
        s['welinkScheduleTime'] = t; s['welinkScheduleGroups'] = self._groups; s['welinkScheduleRules'] = self._rules
        store.save_settings(s)
        now = datetime.now()
        self._fired_date = now.strftime('%Y-%m-%d') if now.strftime('%H:%M') >= t else ''
        self._timer.start(30 * 1000); self._monitoring = True
        self._btn_timer.setText('停止定时'); self._status.setText(f'已启动 · 每天 {t}')
        self._say(f'定时采集已启动：每天 {t}，{len(self._groups)} 个对象 × {len(self._rules)} 条规则')

    def _on_tick(self):
        now = datetime.now(); today = now.strftime('%Y-%m-%d')
        if now.strftime('%H:%M') >= self._time.time().toString('HH:mm') and self._fired_date != today:
            self._fired_date = today
            self._run_all(today)

    def _run_all(self, date_str):
        self._say(f'开始采集 {date_str} …')
        since_ms = int(datetime.strptime(date_str, '%Y-%m-%d').timestamp() * 1000)
        settings = store.load_settings()
        for g in list(self._groups):
            self._capture_group(g, since_ms, date_str, settings)

    def _capture_group(self, g, since_ms, date_str, settings):
        conv = {'kind': g['kind'], 'id': g['target'] if g['kind'] == 'group' else '',
                'account': g['target'] if g['kind'] == 'p2p' else '', 'name': g.get('name', g['target'])}
        rules = list(self._rules)
        gname = conv['name']

        def _work():
            msgs, err = cli.fetch_range(conv, since_ms=since_ms)
            if err and not msgs:
                return (gname, 0, 0, f'拉取失败: {err}')
            segs = []
            for rule in rules:
                if rule['type'] == 'startend':
                    segs += _pair_segments(msgs, rule['start_kw'], rule['end_kw'])
                else:
                    cmd = rule['summary_cmd']
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
                chat_id = f'{g["target"]}_{date_str}_{idx}'
                ok, _ = process.push_session(settings, gname, conv['id'], seg,
                                             seg[0].get('serverSendTime', 0), seg[-1].get('serverSendTime', 0),
                                             chat_id, is_daily=True)
                if ok:
                    pushed += 1
            return (gname, pushed, len(segs), '')

        def _done(res):
            gname, pushed, total, err = res
            self._say(f'[{gname}] {err}' if err else f'[{gname}] 命中 {total} 段，推送 {pushed} 段')

        w = Worker(_work)
        w.ok.connect(_done)
        w.err.connect(lambda m: self._say(f'[{gname}] 异常: {m}'))
        w.start()
        self._workers.append(w)
