"""邮件模块主面板（基于 win32com Outlook）"""
import json
from PyQt5.QtWidgets import *
from PyQt5.QtCore import Qt, QTimer, QPoint
from PyQt5.QtGui import QColor, QFont

from modules.email import outlook, rules as rules_mod
from modules.email.dialogs import SettingsDialog, SetupDialog
import backend
import store  # 仅用于 settings 读写
from utils import Worker

PAGE_SIZE = 30


class _StatusPopup(QFrame):
    """悬浮弹窗，显示完整状态文字，支持文字选中和复制。"""
    def __init__(self):
        super().__init__(None, Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setStyleSheet(
            'QFrame { background:#2b2b2b; border:1px solid #555; border-radius:4px; }'
            'QTextEdit { background:transparent; color:#eee; border:none; }'
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        self._edit = QTextEdit()
        self._edit.setReadOnly(True)
        self._edit.setFont(QFont('Consolas', 9))
        self._edit.setMinimumWidth(420)
        self._edit.setMaximumWidth(700)
        lay.addWidget(self._edit)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

    def show_at(self, text: str, global_pos: QPoint):
        self._edit.setPlainText(text)
        self._edit.document().setTextWidth(420)
        lines = text.count('\n') + 1
        h = min(240, max(60, lines * 18 + 24))
        self._edit.setFixedHeight(h)
        self.adjustSize()
        self.move(global_pos)
        self._hide_timer.stop()
        self.show()

    def schedule_hide(self):
        self._hide_timer.start(300)

    def enterEvent(self, e):
        self._hide_timer.stop()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.schedule_hide()
        super().leaveEvent(e)


class _StatusLabel(QLabel):
    """状态标签，悬停时弹出完整内容窗口。"""
    def __init__(self, popup: '_StatusPopup', parent=None):
        super().__init__(parent)
        self._popup = popup
        self._full  = ''

    def set_status(self, text: str, color: str):
        self._full = text
        self.setText(text.split('\n')[0])
        self.setStyleSheet(f'color:{color}; font-weight:bold;')

    def enterEvent(self, e):
        if self._full:
            gpos = self.mapToGlobal(QPoint(0, self.height() + 2))
            self._popup.show_at(self._full, gpos)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._popup.schedule_hide()
        super().leaveEvent(e)


def _badge(text: str, bg: str, fg: str = '#fff') -> QTableWidgetItem:
    item = QTableWidgetItem(f'  {text}  ')
    item.setBackground(QColor(bg))
    item.setForeground(QColor(fg))
    item.setTextAlignment(Qt.AlignCenter)
    return item

def _parse_status(raw: str) -> str:
    return {'done': '已解析', 'failed': '解析失败', 'pending': '解析中'}.get(raw, '-')


class EmailPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self._settings = store.load_settings()
        backend.set_base(self._settings['backendUrl'])

        self._emails  = []   # 全量（已应用规则）
        self._page    = 1
        self._workers = []
        self._loading = False
        self._syncing = False
        self._setup_dlg = None

        self._build_ui()
        self._start_auto_sync()

    # ── UI 构建 ───────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._make_toolbar())
        root.addWidget(self._make_progress())
        root.addWidget(self._make_table(), stretch=1)
        root.addWidget(self._make_pagination())

    def _make_toolbar(self):
        bar = QWidget()
        bar.setObjectName('toolbar')
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(6)

        self._btn_refresh  = QPushButton('刷新邮件')
        self._btn_sync     = QPushButton('立即同步')
        self._btn_settings = QPushButton('设置')
        self._btn_refresh.setObjectName('btnRefresh')
        self._btn_sync.setObjectName('btnSync')
        self._btn_settings.setObjectName('btnSettings')
        for b in (self._btn_refresh, self._btn_sync, self._btn_settings):
            lay.addWidget(b)

        self._btn_more = QToolButton()
        self._btn_more.setText('···')
        self._btn_more.setObjectName('btnMore')
        self._btn_more.setFixedSize(28, 24)
        self._btn_more.setStyleSheet('QToolButton::menu-indicator { image: none; width: 0; }')
        _more_menu = QMenu(self._btn_more)
        _more_menu.addAction('强制重推').triggered.connect(self._do_force_push)
        self._btn_more.setMenu(_more_menu)
        self._btn_more.setPopupMode(QToolButton.InstantPopup)
        lay.addWidget(self._btn_more)

        lay.addStretch()

        self._status_popup = _StatusPopup()
        self._status_label = _StatusLabel(self._status_popup)
        self._status_label.set_status('就绪', 'green')
        self._status_label.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._status_label)

        lay.addStretch()

        self._filter_check = QCheckBox('仅显示规则匹配的邮件')
        self._filter_check.setChecked(True)
        self._filter_check.stateChanged.connect(self._update_table)
        lay.addWidget(self._filter_check)

        self._btn_refresh.clicked.connect(self._do_refresh)
        self._btn_sync.clicked.connect(self._do_sync)
        self._btn_settings.clicked.connect(self._open_settings)
        return bar

    def _make_progress(self):
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setMaximumHeight(3)
        self._progress.setVisible(False)
        return self._progress

    def _make_table(self):
        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            ['#', '状态', '时间', '发件人', '主题', '会话主题'])
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setSectionResizeMode(4, QHeaderView.Stretch)
        hh.setSectionResizeMode(5, QHeaderView.Stretch)
        self._table.setColumnWidth(0,  36)
        self._table.setColumnWidth(1,  80)
        self._table.setColumnWidth(2, 150)
        self._table.setColumnWidth(3, 110)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(26)
        return self._table

    def _make_pagination(self):
        bar = QWidget()
        bar.setObjectName('pagination')
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(4)

        self._btn_first = QPushButton('|<')
        self._btn_prev  = QPushButton('<')
        self._btn_next  = QPushButton('>')
        self._btn_last  = QPushButton('>|')
        for b in (self._btn_first, self._btn_prev, self._btn_next, self._btn_last):
            b.setObjectName('pgBtn')
            b.setFixedWidth(30)
            lay.addWidget(b)

        self._page_label = QLabel('第 1 / 1 页')
        lay.addWidget(self._page_label)
        lay.addStretch()

        self._total_label = QLabel('')
        self._total_label.setStyleSheet('color: #555;')
        lay.addWidget(self._total_label)

        self._btn_first.clicked.connect(lambda: self._go_page(1))
        self._btn_prev.clicked.connect(lambda: self._go_page(self._page - 1))
        self._btn_next.clicked.connect(lambda: self._go_page(self._page + 1))
        self._btn_last.clicked.connect(lambda: self._go_page(self._total_pages()))
        return bar

    # ── 自动扫描 ──────────────────────────────────────────
    def _start_auto_sync(self):
        if hasattr(self, '_sync_timer'):
            self._sync_timer.stop()
        ms = self._settings.get('scanIntervalMinutes', 60) * 60 * 1000
        self._sync_timer = QTimer(self)
        self._sync_timer.timeout.connect(self._do_sync)
        self._sync_timer.start(ms)

    def activate(self):
        self._settings = store.load_settings()
        backend.set_base(self._settings.get('backendUrl', ''))
        if not self._is_configured():
            self._prompt_setup()

    def _is_configured(self) -> bool:
        s = self._settings
        return bool(s.get('backendUrl') and s.get('userId') and s.get('namespace'))

    def _prompt_setup(self):
        if self._setup_dlg and self._setup_dlg.isVisible():
            self._setup_dlg.raise_()
            return
        dlg = SetupDialog(self._settings, parent=self.window())
        dlg.accepted.connect(lambda: self._on_setup_accepted(dlg))
        dlg.show()
        self._setup_dlg = dlg

    def _on_setup_accepted(self, dlg):
        self._settings = dlg.get_settings()
        store.save_settings(self._settings)
        backend.set_base(self._settings['backendUrl'])
        self._start_auto_sync()

    def deactivate(self):
        if self._setup_dlg:
            self._setup_dlg.close()
            self._setup_dlg = None

    # ── 状态控制 ──────────────────────────────────────────
    def _set_status(self, text: str, color: str = 'green'):
        self._status_label.set_status(text, color)

    def _set_busy(self, loading=False, syncing=False):
        self._loading = loading
        self._syncing = syncing
        busy = loading or syncing
        self._progress.setVisible(busy)
        self._btn_refresh.setEnabled(not busy)
        self._btn_sync.setEnabled(not busy)
        self._btn_more.setEnabled(not busy)

    # ── 刷新邮件 ──────────────────────────────────────────
    def _do_refresh(self):
        if self._loading or self._syncing:
            return
        self._set_busy(loading=True)
        self._set_status('读取 Outlook...', 'orange')

        scan_folders = self._settings.get('scanFolders', [])
        ns           = self._settings.get('namespace', '')

        def _work():
            local_rules = rules_mod.load()
            cloud_rules = backend.get_cloud_rules(ns) if ns else []
            all_rules   = cloud_rules + local_rules
            body_matched_map = rules_mod.build_body_matched_map(all_rules, scan_folders)
            emails = outlook.mail_list(scan_folders or None)
            for e in emails:
                e['matched_rule'] = rules_mod.match(e, all_rules, body_matched_map)
                e['parseStatus']  = '-'
            return emails

        w = Worker(_work)
        w.ok.connect(self._on_refresh_done)
        w.err.connect(lambda m: (self._set_status(f'读取失败：{m}', 'red'), self._set_busy()))
        w.start()
        self._workers.append(w)

    def _on_refresh_done(self, emails):
        errors = [e for e in emails if '_folder_error' in e]
        diags  = [e for e in emails if '_diag' in e]
        self._emails = [e for e in emails if '_folder_error' not in e and '_diag' not in e]
        self._render_table()
        if errors:
            msgs = '；'.join(e['_folder_error'] for e in errors)
            self._set_status(f'文件夹错误：{msgs}', 'red')
        elif diags:
            diag_str = '  '.join(e['_diag'] for e in diags)
            self._set_status(f'就绪 [{diag_str}] 读取 {len(self._emails)} 封', 'green')
        else:
            self._set_status(f'就绪，读取 {len(self._emails)} 封', 'green')
        self._set_busy()
        self._fetch_page_status()

    # ── 同步 ─────────────────────────────────────────────
    def _do_sync(self):
        self._start_sync(force=False)

    def _do_force_push(self):
        if self._loading or self._syncing:
            return
        if QMessageBox.question(
            self, '确认强制重推',
            '将重新推送所有匹配邮件，服务端会重新解析。\n确定继续？'
        ) != QMessageBox.Yes:
            return
        self._start_sync(force=True)

    def _start_sync(self, force: bool):
        if self._loading or self._syncing:
            return
        self._set_busy(syncing=True)
        label = '强制重推中...' if force else '同步中...'
        self._set_status(label, 'darkcyan')

        scan_folders = self._settings.get('scanFolders', [])
        ns           = self._settings.get('namespace', '')

        def _prep():
            local_rules = rules_mod.load()
            cloud_rules = backend.get_cloud_rules(ns) if ns else []
            all_rules   = cloud_rules + local_rules
            body_matched_map = rules_mod.build_body_matched_map(all_rules, scan_folders)
            emails = outlook.mail_list(scan_folders or None)
            for e in emails:
                e['matched_rule'] = rules_mod.match(e, all_rules, body_matched_map)
            return [e for e in emails if e['matched_rule']]

        w = Worker(_prep)
        w.ok.connect(lambda matched: self._on_sync_prep(matched, force))
        w.err.connect(lambda m: (self._set_status(f'出错：{m}', 'red'), self._set_busy()))
        w.start()
        self._workers.append(w)

    def _on_sync_prep(self, matched, force):
        if not matched:
            self._set_status('无匹配邮件', 'green')
            self._set_busy()
            return
        self._sync_batch(matched, 0, 0, 0, force)

    def _sync_batch(self, matched, offset, success, failed, force):
        BATCH = 10
        if offset >= len(matched):
            verb = '重推' if force else '同步'
            summary = f'{verb}完成：{len(matched)} 封，成功 {success}，失败 {failed}'
            self._set_status(summary, 'red' if failed else 'green')
            self._set_busy()
            self._do_refresh()
            return

        verb = '重推' if force else '同步'
        self._set_status(f'{verb}中... ({offset}/{len(matched)})', 'darkcyan')
        batch   = matched[offset:offset + BATCH]
        img_api = self._settings.get('backendUrl', '')

        def _get():
            return [outlook.mail_get(e['item_id'], img_api) for e in batch]

        def _done(items):
            s, f = 0, 0
            for item, src in zip(items, batch):
                try:
                    extra = {}
                    try: extra = json.loads(self._settings.get('customJsonConfig', '{}'))
                    except Exception: pass
                    backend.receive_email({
                        'EmailId':           item['item_id'],
                        'ConversationTopic': item.get('conversation_topic', ''),
                        'Subject':           item.get('subject', ''),
                        'SenderName':        item.get('sender_name', ''),
                        'SenderEmail':       item.get('sender_email', ''),
                        'ReceivedTime':      item.get('received_time', ''),
                        'HtmlBody':          item.get('html_body', ''),
                        'MatchedRuleName':   src.get('matched_rule', ''),
                        'UserId':            self._settings.get('userId', ''),
                        'Namespace':         self._settings.get('namespace', ''),
                        'ExtraInfo':         extra,
                        'Force':             force,
                    })
                    s += 1
                except Exception:
                    f += 1
            self._sync_batch(matched, offset + BATCH, success + s, failed + f, force)

        def _fail(msg):
            self._sync_batch(matched, offset + BATCH, success, failed + len(batch), force)

        w = Worker(_get)
        w.ok.connect(_done)
        w.err.connect(_fail)
        w.start()
        self._workers.append(w)

    # ── 渲染表格 ──────────────────────────────────────────
    def _visible_emails(self):
        if self._filter_check.isChecked():
            return [e for e in self._emails if e.get('matched_rule')]
        return self._emails

    def _render_table(self):
        self._page = 1
        self._update_table()

    def _update_table(self):
        rows_data = self._visible_emails()
        total     = max(1, (len(rows_data) + PAGE_SIZE - 1) // PAGE_SIZE)
        self._page = max(1, min(self._page, total))

        start = (self._page - 1) * PAGE_SIZE
        rows  = rows_data[start:start + PAGE_SIZE]

        self._table.setRowCount(0)
        for idx, e in enumerate(rows):
            r = self._table.rowCount()
            self._table.insertRow(r)

            num = QTableWidgetItem(str(start + idx + 1))
            num.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(r, 0, num)

            ps = e['parseStatus']
            if ps == '已解析':
                self._table.setItem(r, 1, _badge('已解析',   '#2EA043'))
            elif ps == '解析失败':
                self._table.setItem(r, 1, _badge('解析失败', '#B43C3C'))
            elif ps == '解析中':
                self._table.setItem(r, 1, _badge('解析中',   '#B48200'))
            else:
                dash = QTableWidgetItem('-')
                dash.setForeground(QColor('#aaa'))
                dash.setTextAlignment(Qt.AlignCenter)
                self._table.setItem(r, 1, dash)

            self._table.setItem(r, 2, QTableWidgetItem(e['received_time'].replace('T', ' ')))
            self._table.setItem(r, 3, QTableWidgetItem(e['sender_name']))

            subj_item = QTableWidgetItem(e['subject'])
            subj_item.setToolTip(e['subject'])
            self._table.setItem(r, 4, subj_item)

            topic_item = QTableWidgetItem(e['conversation_topic'])
            topic_item.setToolTip(e['conversation_topic'])
            self._table.setItem(r, 5, topic_item)

        self._total_label.setText(f'共 {len(rows_data)} 封')
        self._page_label.setText(f'第 {self._page} / {total} 页')
        self._btn_first.setEnabled(self._page > 1)
        self._btn_prev.setEnabled(self._page > 1)
        self._btn_next.setEnabled(self._page < total)
        self._btn_last.setEnabled(self._page < total)

    def _total_pages(self):
        rows = self._visible_emails()
        return max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)

    def _go_page(self, p: int):
        self._page = p
        self._update_table()
        self._fetch_page_status()

    def _fetch_page_status(self):
        ns = self._settings.get('namespace', '')
        if not ns:
            return
        rows_data   = self._visible_emails()
        start       = (self._page - 1) * PAGE_SIZE
        page_emails = rows_data[start:start + PAGE_SIZE]
        topics      = [e['conversation_topic'] for e in page_emails if e.get('conversation_topic')]
        if not topics:
            return

        def _work():
            return backend.get_parse_status(topics, ns)

        def _done(status_map):
            for e in self._emails:
                raw = status_map.get(e.get('conversation_topic', '').strip(), '')
                if raw:
                    e['parseStatus'] = _parse_status(raw)
            self._update_table()

        w = Worker(_work)
        w.ok.connect(_done)
        w.err.connect(lambda _: None)
        w.start()
        self._workers.append(w)

    # ── 设置 ──────────────────────────────────────────────
    def _open_settings(self):
        dlg = SettingsDialog(self._settings, parent=self)
        if dlg.exec_() == SettingsDialog.Accepted:
            self._settings = dlg.get_settings()
            store.save_settings(self._settings)
            backend.set_base(self._settings['backendUrl'])
            self._start_auto_sync()
            self._set_status('设置已更新', 'green')
            self._do_refresh()
