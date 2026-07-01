"""邮件模块主面板（基于 win32com Outlook）"""
import json
from PyQt5.QtWidgets import *
from PyQt5.QtCore import Qt, QTimer, QPoint, QRect, pyqtSignal
from PyQt5.QtGui import QColor, QFont

from modules.email import outlook, rules as rules_mod, local_archive
from modules.email.folder_pane import FolderPane
from modules.email.rules_editor import RulesDialog, StartTimerDialog
from modules.email.log_panel import LogPanel
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
            gpos = self.mapToGlobal(QPoint(self.width() // 2 - 210, self.height() + 2))
            self._popup.show_at(self._full, gpos)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._popup.schedule_hide()
        super().leaveEvent(e)


class _CheckHeader(QHeaderView):
    """带「全选」复选框的表头：在第 0 列放一个**真实 QCheckBox** 子控件。

    之前自绘(paintSection/drawPrimitive)在全局 QSS(QStyleSheetStyle)下会被吞掉、画不出来，
    实测像素为 0。放真控件走原生样式，QSS 影响不到，稳定可见。
    """
    toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self.setSectionsClickable(True)
        self.setHighlightSections(False)
        self._cb = QCheckBox(self)
        self._cb.setToolTip('全选/取消（当前筛选下）')
        self._cb.setStyleSheet('QCheckBox{background:transparent;margin:0;padding:0;}')
        self._cb.toggled.connect(self.toggled)
        self.sectionResized.connect(lambda *a: self._reposition())

    def setChecked(self, c: bool):
        self._cb.blockSignals(True)
        self._cb.setChecked(bool(c))
        self._cb.blockSignals(False)

    def _reposition(self):
        w = self.sectionSize(0)
        h = self.height()
        sz = self._cb.sizeHint()
        self._cb.setGeometry((w - sz.width()) // 2, (h - sz.height()) // 2,
                             sz.width(), sz.height())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._reposition()

    def showEvent(self, e):
        super().showEvent(e)
        self._reposition()


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
        self._building = False        # 重建表格时屏蔽 itemChanged
        self._checked = set()         # 选中的 item_id（跨分页/筛选保持）
        self._filter_mode = 'all'     # 'all' | 'matched'，对应分段筛选
        self._monitoring = False      # 定时同步是否在运行
        self._cancel_sync = False     # 请求中止当前推送（处理选中/同步/重推）
        self._folders_loaded_once = False  # 文件夹是否已首次加载
        self._pending_refresh = False      # 文件夹加载完成后是否补一次邮件刷新
        self._last_sync_time = self._settings.get('lastSyncTime', '')

        # 定时同步：仅创建，不自动启动；由用户用「启动定时 / 停止定时」控制
        self._timer_mode = 'interval'   # 'interval'（每N分钟）| 'daily'（每天某时刻）
        self._daily_time = self._settings.get('scanDailyTime', '09:00')
        self._daily_fired_date = ''     # 'daily' 模式当天是否已触发
        self._sync_timer = QTimer(self)
        self._sync_timer.timeout.connect(self._on_timer_tick)

        self._build_ui()

    # ── UI 构建 ───────────────────────────────────────────
    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._folder_pane = FolderPane()
        self._folder_pane.scopeChanged.connect(self._on_scope_changed)
        self._folder_pane.loaded.connect(self._on_folders_loaded)
        root.addWidget(self._folder_pane)

        right = QWidget()
        rlay = QVBoxLayout(right)
        rlay.setContentsMargins(0, 0, 0, 0)
        rlay.setSpacing(0)
        rlay.addWidget(self._make_toolbar())
        rlay.addWidget(self._make_progress())
        rlay.addWidget(self._make_table(), stretch=1)
        rlay.addWidget(self._make_pagination())

        self._log = LogPanel()
        rlay.addWidget(self._log)

        root.addWidget(right, stretch=1)

        self._folder_pane.set_log(self._log.append)

    def _make_toolbar(self):
        bar = QWidget()
        bar.setObjectName('toolbar')
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(6)

        # 分段筛选：全部 / 按规则匹配（参考 standalone）
        seg_style = (
            'QPushButton{border:1px solid #bbb;background:#f5f5f5;padding:4px 12px;'
            'min-height:24px;border-radius:0;}'
            'QPushButton:checked{background:#008C64;color:white;border:1px solid #008C64;}')
        self._seg_all     = QPushButton('全部 (0)')
        self._seg_matched = QPushButton('按规则匹配 (0)')
        seg_group = QButtonGroup(self)
        seg_group.setExclusive(True)
        for b in (self._seg_all, self._seg_matched):
            b.setCheckable(True)
            b.setStyleSheet(seg_style)
            seg_group.addButton(b)
        self._seg_all.setChecked(True)
        lay.addWidget(self._seg_all)
        lay.addWidget(self._seg_matched)

        self._btn_rules = QPushButton('规则')
        lay.addWidget(self._btn_rules)

        self._btn_refresh = QPushButton('刷新邮件')
        self._btn_refresh.setObjectName('btnRefresh')
        lay.addWidget(self._btn_refresh)

        lay.addStretch()   # 搜索框在「刷新邮件」和「启动定时」之间居中

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText('🔍 搜索主题/发件人…')
        self._search_edit.setFixedWidth(170)
        self._search_edit.setClearButtonEnabled(True)
        lay.addWidget(self._search_edit)

        lay.addStretch()

        self._btn_timer = QPushButton('启动定时')
        self._btn_timer.setFixedWidth(76)
        lay.addWidget(self._btn_timer)

        self._btn_process = QPushButton('处理选中 (0)')
        self._btn_process.setObjectName('btnPrimary')
        self._btn_process.setEnabled(False)
        lay.addWidget(self._btn_process)

        self._btn_refresh.clicked.connect(self._do_refresh)
        self._seg_all.clicked.connect(lambda: self._set_filter_mode('all'))
        self._seg_matched.clicked.connect(lambda: self._set_filter_mode('matched'))
        self._btn_rules.clicked.connect(self._open_rules_dialog)
        self._search_edit.textChanged.connect(self._on_filter_changed)
        self._btn_process.clicked.connect(self._on_process_clicked)
        self._btn_timer.clicked.connect(self._toggle_timer)
        self._refresh_timer_style()
        return bar

    def _open_rules_dialog(self):
        dlg = RulesDialog(self._settings.get('namespace', ''),
                          on_changed=self._on_rules_changed, parent=self)
        dlg.exec_()

    def _make_progress(self):
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setMaximumHeight(3)
        self._progress.setVisible(False)
        return self._progress

    def _make_table(self):
        self._table = QTableWidget(0, 7)
        self._check_header = _CheckHeader(self._table)
        self._table.setHorizontalHeader(self._check_header)
        self._check_header.toggled.connect(self._on_header_toggle)
        self._table.setHorizontalHeaderLabels(
            ['', '#', '状态', '时间', '发件人', '主题', '会话主题'])
        hh = self._check_header
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setSectionResizeMode(5, QHeaderView.Stretch)
        hh.setSectionResizeMode(6, QHeaderView.Stretch)
        self._table.setColumnWidth(0,  30)
        self._table.setColumnWidth(1,  36)
        self._table.setColumnWidth(2,  80)
        self._table.setColumnWidth(3, 150)
        self._table.setColumnWidth(4, 110)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(26)
        self._table.itemChanged.connect(self._on_item_changed)
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

    # ── 定时同步（用户启停） ───────────────────────────────
    def _toggle_timer(self):
        if self._monitoring:
            self._stop_timer()
        else:
            self._start_timer()

    def _start_timer(self):
        if not self._is_configured():
            QMessageBox.warning(self, '提示', '请先在设置中配置后端地址、工号与命名空间')
            return
        default = int(self._settings.get('scanIntervalMinutes', 60) or 60)
        scan_count = len(self._settings.get('scanFolders', []))
        dlg = StartTimerDialog(
            self._settings.get('namespace', ''), scan_count, default,
            daily_time=self._settings.get('scanDailyTime', '09:00'),
            mode=self._settings.get('scanTimerMode', 'interval'),
            on_changed=self._on_rules_changed, parent=self)
        if dlg.exec_() != QDialog.Accepted:
            return
        self._timer_mode = dlg.mode()
        if self._timer_mode == 'daily':
            from datetime import datetime
            self._daily_time = dlg.daily_time()
            now = datetime.now()
            # 启动时若已过当天时刻，标记今天已触发，避免点一下就立刻全量推一次（明天才跑）
            self._daily_fired_date = now.strftime('%Y-%m-%d') if now.strftime('%H:%M') >= self._daily_time else ''
            self._settings['scanTimerMode'] = 'daily'
            self._settings['scanDailyTime'] = self._daily_time
            store.save_settings(self._settings)
            self._sync_timer.start(30 * 1000)   # 每 30s 查一次是否到点
            label = f'定时同步已启动：每天 {self._daily_time}（可随时点「停止定时」）'
        else:
            mins = dlg.interval()
            self._settings['scanTimerMode'] = 'interval'
            self._settings['scanIntervalMinutes'] = mins
            store.save_settings(self._settings)
            self._sync_timer.start(mins * 60 * 1000)
            label = f'定时同步已启动：每 {mins} 分钟一次（可随时点「停止定时」）'
        self._monitoring = True
        self._refresh_timer_style()
        self._set_status(label)

    def _on_timer_tick(self):
        if self._timer_mode == 'daily':
            from datetime import datetime
            now = datetime.now()
            today = now.strftime('%Y-%m-%d')
            if now.strftime('%H:%M') >= self._daily_time and self._daily_fired_date != today:
                self._daily_fired_date = today
                self._do_sync()
        else:
            self._do_sync()

    def _stop_timer(self):
        self._sync_timer.stop()
        self._monitoring = False
        self._refresh_timer_style()
        self._set_status('定时同步已停止')

    def _refresh_timer_style(self):
        if self._monitoring:
            self._btn_timer.setText('停止定时')
            self._btn_timer.setStyleSheet(
                'QPushButton{background:#B71C1C;color:white;border:none;}'
                'QPushButton:hover{background:#a01818;}')
        else:
            self._btn_timer.setText('启动定时')
            self._btn_timer.setStyleSheet(
                'QPushButton{background:#008C64;color:white;border:none;}'
                'QPushButton:hover{background:#007a57;}')

    def activate(self):
        self._settings = store.load_settings()
        backend.set_base(self._settings.get('backendUrl', ''))
        if self._is_configured():
            # 先刷邮件：mail_list 会 GetDefaultFolder 触发 MAPI logon 把 Outlook 暖起来，
            # 刷完(在 _on_refresh_done)再加载文件夹——此时 ns.Stores 才齐，避免“0 个”。
            self._do_refresh()
        elif not self._folders_loaded_once:
            self._folders_loaded_once = True
            self._folder_pane.reload()

    def _on_folders_loaded(self):
        pass

    def _on_scope_changed(self):
        self._settings = store.load_settings()
        self._log.append('文件夹范围已更新，重新读取')
        self._do_refresh()

    def _on_rules_changed(self):
        self._log.append('规则已变更，重新匹配')
        self._do_refresh()

    def _is_configured(self) -> bool:
        s = self._settings
        return bool(s.get('backendUrl') and s.get('userId') and s.get('namespace'))

    def deactivate(self):
        pass

    def on_settings_changed(self, s: dict):
        self._settings = s
        backend.set_base(s.get('backendUrl', ''))
        self._do_refresh()

    # ── 状态：统一写入底部日志（不再有工具栏「就绪」标签）──────
    def _set_status(self, text: str, color: str = 'green'):
        self._log.append(text)

    def _set_busy(self, loading=False, syncing=False):
        self._loading = loading
        self._syncing = syncing
        busy = loading or syncing
        self._progress.setVisible(busy)
        self._btn_refresh.setEnabled(not busy)
        self._update_selection_ui()

    # ── 匹配：规则集合 − 黑名单集合 ─────────────────────────
    def _match_emails(self, emails, scan_folders):
        """命中规则(白名单)且未命中黑名单 → matched_rule=规则名；否则空。在 Worker 线程里跑。"""
        whitelist = rules_mod.load()
        blacklist = rules_mod.load_blacklist()
        wl_maps = rules_mod.build_match_maps(whitelist, scan_folders)
        bl_maps = rules_mod.build_match_maps(blacklist, scan_folders)
        for e in emails:
            wl = rules_mod.match(e, whitelist, wl_maps)
            bl = rules_mod.match(e, blacklist, bl_maps)
            e['matched_rule'] = wl if (wl and not bl) else ''
        return emails

    # ── 刷新邮件 ──────────────────────────────────────────
    def _do_refresh(self):
        if self._loading or self._syncing:
            return
        self._set_busy(loading=True)
        self._set_status('读取 Outlook...', 'orange')

        scan_folders = self._settings.get('scanFolders', [])

        def _work():
            emails = outlook.mail_list(scan_folders or None)
            self._match_emails(emails, scan_folders)
            for e in emails:
                e['parseStatus'] = '-'
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
        self._checked.clear()
        self._render_table()
        if errors:
            msgs = '；'.join(e['_folder_error'] for e in errors)
            self._set_status(f'文件夹错误：{msgs}', 'red')
        else:
            sync = f'，上次同步 {self._last_sync_time}' if self._last_sync_time else ''
            self._set_status(f'读取 {len(self._emails)} 封{sync}', 'green')
        self._set_busy()
        self._fetch_page_status()
        if not self._folders_loaded_once:
            # 邮件已刷完，Outlook 已暖；此时加载文件夹树才能拿全 Stores
            self._folders_loaded_once = True
            self._folder_pane.reload()

    # ── 同步 ─────────────────────────────────────────────
    def _do_sync(self):
        self._start_sync(force=False)

    def _start_sync(self, force: bool):
        if self._loading or self._syncing:
            return
        self._cancel_sync = False
        self._set_busy(syncing=True)
        self._set_status('定时同步中...', 'darkcyan')

        scan_folders = self._settings.get('scanFolders', [])

        def _prep():
            emails = outlook.mail_list(scan_folders or None)
            self._match_emails(emails, scan_folders)
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
        self._sync_batch(matched, 0, 0, 0, force, '重推' if force else '同步')

    # ── 处理选中：把勾选的邮件推送到服务端 ──────────────────
    def _do_process_selected(self):
        if self._loading or self._syncing:
            return
        if not self._is_configured():
            QMessageBox.warning(self, '提示', '请先在设置中配置后端地址、工号与命名空间')
            return
        selected = [e for e in self._emails if e['item_id'] in self._checked]
        if not selected:
            return
        if QMessageBox.question(
                self, '处理选中',
                f'将选中的 {len(selected)} 封邮件推送到服务端处理（含已解析的会重新解析）。\n'
                f'（未命中规则的邮件将以「手动处理」为规则名）\n\n确定继续？',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) != QMessageBox.Yes:
            return
        self._cancel_sync = False
        self._set_busy(syncing=True)
        self._set_status(f'处理选中... (0/{len(selected)})', 'darkcyan')
        # 你手动勾选 = 明确想处理它，force=True 让已解析的也重跑（替代旧「强制重推」）
        self._sync_batch(selected, 0, 0, 0, True, '处理选中')

    def _sync_batch(self, matched, offset, success, failed, force, verb):
        BATCH = 10
        # 已处理完，或用户在批次间点了「停止」 → 收尾
        if offset >= len(matched) or self._cancel_sync:
            from datetime import datetime
            self._last_sync_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            self._settings['lastSyncTime'] = self._last_sync_time
            store.save_settings(self._settings)
            if self._cancel_sync:
                summary = (f'{verb}已停止：已处理 {offset}/{len(matched)} 封，'
                           f'成功 {success}，失败 {failed}')
            else:
                summary = f'{verb}完成：{len(matched)} 封，成功 {success}，失败 {failed}'
            self._cancel_sync = False
            self._set_status(summary, 'red' if failed else 'green')
            self._set_busy()
            self._do_refresh()
            return

        batch   = matched[offset:offset + BATCH]
        img_api = self._settings.get('backendUrl', '')

        def _get():
            return [outlook.mail_get(e['item_id'], img_api) for e in batch]

        def _done(items):
            s, f = 0, 0
            for item, src in zip(items, batch):
                if self._cancel_sync:   # 批次内也及时停，未推送的留待收尾
                    break
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
                        'MarkdownBody':      item.get('markdown_body', ''),
                        'MatchedRuleName':   src.get('matched_rule') or '手动处理',
                        'UserId':            self._settings.get('userId', ''),
                        'Namespace':         self._settings.get('namespace', ''),
                        'ExtraInfo':         extra,
                        'Force':             force,
                    })
                    # 推送成功后，HTML + MD 两份都存到本地保存目录
                    local_archive.save_email(
                        self._settings.get('outputDir', ''),
                        item.get('subject') or item.get('conversation_topic', ''),
                        item.get('html_body', ''),
                        item.get('markdown_body', ''))
                    s += 1
                except Exception:
                    f += 1
            # 仅推进实际尝试过的数量；若中途停止，剩余的不计入 offset，由收尾分支结束
            self._sync_batch(matched, offset + s + f, success + s, failed + f, force, verb)

        def _fail(msg):
            self._sync_batch(matched, offset + len(batch), success, failed + len(batch), force, verb)

        w = Worker(_get)
        w.ok.connect(_done)
        w.err.connect(_fail)
        w.start()
        self._workers.append(w)

    # ── 筛选 / 选择 ───────────────────────────────────────
    def _visible_emails(self):
        rows = self._emails
        if self._filter_mode == 'matched':
            rows = [e for e in rows if e.get('matched_rule')]
        q = self._search_edit.text().strip().lower()
        if q:
            rows = [e for e in rows if q in (
                f"{e.get('subject', '')} {e.get('sender_name', '')} "
                f"{e.get('sender_email', '')} {e.get('conversation_topic', '')}").lower()]
        return rows

    def _set_filter_mode(self, mode: str):
        self._filter_mode = mode
        self._page = 1
        self._update_table()

    def _on_filter_changed(self, _=None):
        self._page = 1
        self._update_table()

    def _on_item_changed(self, item):
        if self._building or item.column() != 0:
            return
        iid = item.data(Qt.UserRole)
        if item.checkState() == Qt.Checked:
            self._checked.add(iid)
        else:
            self._checked.discard(iid)
        self._update_selection_ui()

    def _on_header_toggle(self, checked: bool):
        """表头「全选」：勾选/取消当前筛选下的全部（跨分页）。"""
        vis_ids = [e['item_id'] for e in self._visible_emails()]
        if checked:
            self._checked.update(vis_ids)
        else:
            for i in vis_ids:
                self._checked.discard(i)
        self._update_table()

    def _update_selection_ui(self):
        if not hasattr(self, '_btn_process'):
            return
        if self._syncing:
            # 推送进行中：按钮变成「停止」，随时可中止
            self._btn_process.setText('停止')
            self._btn_process.setEnabled(not self._cancel_sync)
            self._btn_process.setStyleSheet(
                'QPushButton{background:#B71C1C;color:white;border:none;}'
                'QPushButton:hover{background:#a01818;}')
        else:
            n = len(self._checked)
            self._btn_process.setText(f'处理选中 ({n})')
            self._btn_process.setEnabled(n > 0 and not self._loading)
            self._btn_process.setStyleSheet('')
        vis_ids = [e['item_id'] for e in self._visible_emails()]
        all_checked = bool(vis_ids) and all(i in self._checked for i in vis_ids)
        self._check_header.setChecked(all_checked)

    # ── 处理选中 / 停止 ───────────────────────────────────
    def _on_process_clicked(self):
        if self._syncing:
            self._cancel_sync = True
            self._set_status('正在停止…（当前批次完成后停止）', 'orange')
            self._update_selection_ui()
        else:
            self._do_process_selected()

    def _render_table(self):
        self._page = 1
        self._update_table()

    def _update_table(self):
        rows_data = self._visible_emails()
        total     = max(1, (len(rows_data) + PAGE_SIZE - 1) // PAGE_SIZE)
        self._page = max(1, min(self._page, total))

        start = (self._page - 1) * PAGE_SIZE
        rows  = rows_data[start:start + PAGE_SIZE]

        self._building = True
        self._table.setRowCount(0)
        for idx, e in enumerate(rows):
            r = self._table.rowCount()
            self._table.insertRow(r)

            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk.setCheckState(Qt.Checked if e['item_id'] in self._checked else Qt.Unchecked)
            chk.setData(Qt.UserRole, e['item_id'])
            self._table.setItem(r, 0, chk)

            num = QTableWidgetItem(str(start + idx + 1))
            num.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(r, 1, num)

            ps = e['parseStatus']
            if ps == '已解析':
                self._table.setItem(r, 2, _badge('已解析',   '#2EA043'))
            elif ps == '解析失败':
                self._table.setItem(r, 2, _badge('解析失败', '#B43C3C'))
            elif ps == '解析中':
                self._table.setItem(r, 2, _badge('解析中',   '#B48200'))
            else:
                dash = QTableWidgetItem('-')
                dash.setForeground(QColor('#aaa'))
                dash.setTextAlignment(Qt.AlignCenter)
                self._table.setItem(r, 2, dash)

            self._table.setItem(r, 3, QTableWidgetItem(e['received_time'].replace('T', ' ')))
            self._table.setItem(r, 4, QTableWidgetItem(e['sender_name']))

            subj_item = QTableWidgetItem(e['subject'])
            subj_item.setToolTip(e['subject'])
            self._table.setItem(r, 5, subj_item)

            topic_item = QTableWidgetItem(e['conversation_topic'])
            topic_item.setToolTip(e['conversation_topic'])
            self._table.setItem(r, 6, topic_item)
        self._building = False

        self._seg_all.setText(f'全部 ({len(self._emails)})')
        self._seg_matched.setText(
            f'按规则匹配 ({sum(1 for e in self._emails if e.get("matched_rule"))})')
        self._total_label.setText(f'共 {len(rows_data)} 封')
        self._page_label.setText(f'第 {self._page} / {total} 页')
        self._btn_first.setEnabled(self._page > 1)
        self._btn_prev.setEnabled(self._page > 1)
        self._btn_next.setEnabled(self._page < total)
        self._btn_last.setEnabled(self._page < total)
        self._update_selection_ui()

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

