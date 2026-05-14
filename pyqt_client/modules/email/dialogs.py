"""邮件模块：设置对话框 + 规则编辑对话框"""
from PyQt5.QtWidgets import *
from PyQt5.QtCore import Qt, QTimer, QStringListModel
from PyQt5.QtGui import QFont

from modules.email import outlook
from modules.email import rules as rules_mod
import backend
from utils import Worker

_SERVER_PRESETS = {
    '云核心网': 'https://coreinsight-beta.rnd.huawei.com/collection',
}
_MANUAL_INPUT = '手动输入URL'

_API_DOC = """\
自定义服务器须实现以下 HTTP 接口（基础路径 /api/email/）：

━━ 必需接口 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GET  /api/email/ping
  响应: {"Success": true, "Message": "pong"}

GET  /api/email/namespaces
  响应: [{"id": int, "name": str, "description": str}, ...]

POST /api/email/receive
  请求体 (JSON 字段):
    EmailId           string   邮件唯一 ID
    ConversationTopic string   会话主题
    Subject           string   邮件主题
    SenderName        string   发件人姓名
    SenderEmail       string   发件人邮箱
    ReceivedTime      string   接收时间（ISO 格式）
    HtmlBody          string   邮件正文（HTML）
    MatchedRuleName   string   命中规则名称
    UserId            string   操作用户 ID
    Namespace         string   命名空间名称
    ExtraInfo         object   扩展字段（JSON 对象）
    Force             bool     是否强制重推
  响应: {"Success": bool, "Message": str}

POST /api/email/parse_status
  请求体: {"topics": ["会话主题A", ...], "namespace": "xxx"}
  响应:   {"会话主题A": "done|pending|failed", ...}

━━ 可选接口（云端规则管理）━━━━━━━━━━━━━━━━━━
GET    /api/email/rules?namespace=xxx
POST   /api/email/rules
PUT    /api/email/rules/{id}
DELETE /api/email/rules/{id}

━━ 必需接口（用户搜索）━━━━━━━━━━━━━━━━━━━━━━
GET /api/email/userinfo?info=xxx
  响应: [{"label": "姓名", "value": "账号"}, ...]
  说明: 工号必须从此接口返回值中选择，不支持自由输入
"""

def _resolve_server_url(text: str) -> str:
    text = text.strip()
    if text == _MANUAL_INPUT:
        return ''
    return _SERVER_PRESETS.get(text, text)

def _url_to_display(url: str) -> str:
    url = (url or '').rstrip('/')
    for name, u in _SERVER_PRESETS.items():
        if u.rstrip('/') == url:
            return name
    return url

def _show_api_doc(parent):
    dlg = QDialog(parent)
    dlg.setWindowTitle('接口实现说明')
    dlg.setMinimumSize(520, 480)
    lay = QVBoxLayout(dlg)
    te = QTextEdit()
    te.setReadOnly(True)
    te.setFont(QFont('Consolas', 9))
    te.setPlainText(_API_DOC)
    lay.addWidget(te)
    btn_close = QPushButton('关闭')
    btn_close.setFixedWidth(80)
    btn_close.clicked.connect(dlg.accept)
    blay = QHBoxLayout()
    blay.addStretch()
    blay.addWidget(btn_close)
    lay.addLayout(blay)
    dlg.exec_()


# ── 规则编辑对话框 ────────────────────────────────────────
class RuleDialog(QDialog):
    def __init__(self, rule=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle('编辑规则' if rule else '添加规则')
        self.setFixedWidth(420)

        self.name_edit          = QLineEdit(rule['name']                       if rule else '')
        self.keywords_edit      = QLineEdit(', '.join(rule['keywords'])        if rule else '')
        self.body_keywords_edit = QLineEdit(', '.join(rule.get('body_keywords', [])) if rule else '')
        self.senders_edit       = QLineEdit(', '.join(rule['senders'])         if rule else '')
        self.logic_combo        = QComboBox()
        self.logic_combo.addItems(['OR（任一命中）', 'AND（同时命中）'])
        if rule and rule.get('logic') == 'AND':
            self.logic_combo.setCurrentIndex(1)

        self.keywords_edit.setPlaceholderText('逗号分隔，匹配邮件主题')
        self.body_keywords_edit.setPlaceholderText('逗号分隔，匹配邮件正文（Exchange 服务器搜索）')
        self.senders_edit.setPlaceholderText('逗号分隔，邮箱或姓名')

        form = QFormLayout()
        form.addRow('规则名称 *', self.name_edit)
        form.addRow('主题关键词', self.keywords_edit)
        form.addRow('正文关键词', self.body_keywords_edit)
        form.addRow('发件人',     self.senders_edit)
        form.addRow('匹配逻辑',   self.logic_combo)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText('保存')
        btns.button(QDialogButtonBox.Cancel).setText('取消')
        btns.accepted.connect(self._accept)
        btns.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(btns)

    def _accept(self):
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, '错误', '请输入规则名称')
            return
        self.accept()

    def result_data(self):
        return {
            'name':          self.name_edit.text().strip(),
            'keywords':      [k.strip() for k in self.keywords_edit.text().split(',')      if k.strip()],
            'body_keywords': [k.strip() for k in self.body_keywords_edit.text().split(',') if k.strip()],
            'senders':       [s.strip() for s in self.senders_edit.text().split(',')       if s.strip()],
            'logic':         'AND' if self.logic_combo.currentIndex() == 1 else 'OR',
        }


# ── 设置对话框 ────────────────────────────────────────────
class SettingsDialog(QDialog):
    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle('设置')
        self.setMinimumSize(700, 480)
        self._s       = dict(settings)
        self._workers = []

        self._tabs = QTabWidget()
        self._tabs.addTab(self._make_basic(),   '基本')
        self._tabs.addTab(self._make_folders(), '文件夹')
        self._tabs.addTab(self._make_rules(),   '规则')
        self._tabs.currentChanged.connect(self._on_tab_changed)

        btns = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Save)
        btns.button(QDialogButtonBox.Save).setText('保存')
        btns.button(QDialogButtonBox.Cancel).setText('取消')
        btns.accepted.connect(self._on_save)
        btns.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addWidget(self._tabs)
        lay.addWidget(btns)

    # ── 基本 tab ─────────────────────────────────────────
    def _make_basic(self):
        outer = QWidget()
        vlay = QVBoxLayout(outer)
        vlay.setContentsMargins(0, 0, 0, 0)
        vlay.setSpacing(0)

        form_w = QWidget()
        lay = QFormLayout(form_w)
        lay.setVerticalSpacing(4)
        lay.setHorizontalSpacing(8)
        lay.setContentsMargins(8, 8, 8, 8)

        self._interval = QSpinBox()
        self._interval.setRange(1, 1440)
        self._interval.setValue(self._s.get('scanIntervalMinutes', 60))
        self._interval.setSuffix(' 分钟')
        self._interval.setMaximumWidth(120)
        lay.addRow('扫描间隔：', self._interval)

        self._custom_json = QPlainTextEdit(self._s.get('customJsonConfig', '{}'))
        self._custom_json.setFixedHeight(100)
        self._custom_json.setFont(QFont('Consolas', 10))
        lay.addRow('额外配置：', self._custom_json)

        vlay.addWidget(form_w)
        vlay.addStretch()
        return outer

    # ── 文件夹 tab ───────────────────────────────────────
    def _make_folders(self):
        w = QWidget()
        lay = QVBoxLayout(w)

        hint = QLabel('勾选要扫描的文件夹，留空则只扫描默认收件箱。')
        hint.setStyleSheet('color: #555; font-size: 11px;')
        lay.addWidget(hint)

        top = QHBoxLayout()
        self._btn_folder_refresh = QPushButton('刷新')
        self._btn_folder_refresh.setFixedWidth(60)
        self._folder_hint = QLabel('')
        self._folder_hint.setStyleSheet('color: #888; font-size: 11px;')
        top.addWidget(self._btn_folder_refresh)
        top.addWidget(self._folder_hint)
        top.addStretch()
        lay.addLayout(top)

        self._folder_list = QListWidget()
        self._folder_list.setAlternatingRowColors(True)
        lay.addWidget(self._folder_list)

        self._btn_folder_refresh.clicked.connect(self._load_outlook_folders)
        self._folder_loading = False

        self._scan_folders = set(self._s.get('scanFolders', []))
        self._prefill_folders()
        return w

    def _prefill_folders(self):
        """先把已保存的勾选项显示出来，等刷新后合并全量列表。"""
        if not self._scan_folders:
            return
        self._folder_list.blockSignals(True)
        self._folder_list.clear()
        for path in sorted(self._scan_folders):
            item = QListWidgetItem(path)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self._folder_list.addItem(item)
        self._folder_list.blockSignals(False)
        self._folder_list.itemChanged.connect(self._on_folder_changed)
        self._folder_hint.setText(f'已选 {len(self._scan_folders)} 个（点击刷新加载全部）')

    def _load_outlook_folders(self):
        if self._folder_loading:
            return
        self._folder_loading = True
        self._btn_folder_refresh.setEnabled(False)
        self._folder_hint.setText('加载中...')

        def _work():
            return outlook.folder_list()

        def _done(folders):
            self._folder_loading = False
            self._btn_folder_refresh.setEnabled(True)
            self._folder_hint.setText(f'共 {len(folders)} 个文件夹')
            self._folder_list.blockSignals(True)
            self._folder_list.clear()
            for path in folders:
                item = QListWidgetItem(path)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked if path in self._scan_folders else Qt.Unchecked)
                self._folder_list.addItem(item)
            self._folder_list.blockSignals(False)
            self._folder_list.itemChanged.connect(self._on_folder_changed)

        def _fail(msg):
            self._folder_loading = False
            self._btn_folder_refresh.setEnabled(True)
            self._folder_hint.setText(f'加载失败: {msg}')

        w = Worker(_work)
        w.ok.connect(_done)
        w.err.connect(_fail)
        w.start()
        self._workers.append(w)

    def _on_folder_changed(self, item):
        if item.checkState() == Qt.Checked:
            self._scan_folders.add(item.text())
        else:
            self._scan_folders.discard(item.text())

    # ── 规则 tab ─────────────────────────────────────────
    def _make_rules(self):
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setSpacing(8)

        # ── 云端规则 ──────────────────────────────────
        self._cloud_group = QGroupBox('云端规则（命名空间）')
        cg = QVBoxLayout(self._cloud_group)

        self._cloud_table = self._make_rule_table()
        cg.addWidget(self._cloud_table)

        cr_row = QHBoxLayout()
        cb_add    = QPushButton('添加')
        cb_edit   = QPushButton('编辑')
        cb_del    = QPushButton('删除')
        cb_toggle = QPushButton('启用/禁用')
        cb_refresh= QPushButton('刷新')
        cb_del.setObjectName('btnDanger')
        for b in (cb_add, cb_edit, cb_del, cb_toggle):
            b.setFixedHeight(24)
            cr_row.addWidget(b)
        cr_row.addStretch()
        cb_refresh.setFixedHeight(24)
        cr_row.addWidget(cb_refresh)
        cg.addLayout(cr_row)
        outer.addWidget(self._cloud_group)

        self._cloud_rules_data = []
        cb_add.clicked.connect(self._cloud_rule_add)
        cb_edit.clicked.connect(self._cloud_rule_edit)
        cb_del.clicked.connect(self._cloud_rule_delete)
        cb_toggle.clicked.connect(self._cloud_rule_toggle)
        cb_refresh.clicked.connect(self._load_cloud_rules)

        # ── 本地规则 ──────────────────────────────────
        local_group = QGroupBox('本地规则')
        lg = QVBoxLayout(local_group)

        self._rule_table = self._make_rule_table()
        lg.addWidget(self._rule_table)

        lr_row = QHBoxLayout()
        btn_add    = QPushButton('添加')
        btn_edit   = QPushButton('编辑')
        btn_del    = QPushButton('删除')
        btn_toggle = QPushButton('启用/禁用')
        btn_del.setObjectName('btnDanger')
        for b in (btn_add, btn_edit, btn_del, btn_toggle):
            b.setFixedHeight(24)
            lr_row.addWidget(b)
        lr_row.addStretch()
        lg.addLayout(lr_row)
        outer.addWidget(local_group)

        self._rules_data = []
        btn_add.clicked.connect(self._rule_add)
        btn_edit.clicked.connect(self._rule_edit)
        btn_del.clicked.connect(self._rule_delete)
        btn_toggle.clicked.connect(self._rule_toggle)
        return w

    @staticmethod
    def _make_rule_table() -> QTableWidget:
        t = QTableWidget(0, 6)
        t.setHorizontalHeaderLabels(['启用', '规则名称', '主题关键词', '正文关键词', '发件人', '逻辑'])
        t.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        t.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        t.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        t.setColumnWidth(0, 40)
        t.setColumnWidth(1, 110)
        t.setColumnWidth(5, 44)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.setAlternatingRowColors(True)
        t.setMaximumHeight(160)
        return t

    def _on_tab_changed(self, idx):
        tab = self._tabs.tabText(idx)
        if tab == '规则':
            self._load_cloud_rules()
            self._load_rules()
        elif tab == '文件夹':
            self._load_outlook_folders()

    # ── 云端规则操作 ──────────────────────────────────
    def _load_cloud_rules(self):
        ns = self._s.get('namespace', '')
        self._cloud_group.setTitle(f'云端规则（{ns or "未选择命名空间"}）')
        if not ns:
            self._cloud_rules_data = []
            self._render_rule_table(self._cloud_table, [])
            return

        def _work():
            return backend.get_cloud_rules(ns)

        def _done(rules):
            self._cloud_rules_data = rules
            self._render_rule_table(self._cloud_table, rules)

        w = Worker(_work)
        w.ok.connect(_done)
        w.start()
        self._workers.append(w)

    def _cloud_rule_add(self):
        ns = self._s.get('namespace', '')
        if not ns:
            QMessageBox.warning(self, '提示', '请先在基本设置中选择命名空间')
            return
        dlg = RuleDialog(parent=self)
        if dlg.exec_() != QDialog.Accepted:
            return
        d = dlg.result_data()
        def _done(_): self._load_cloud_rules()
        w = Worker(backend.add_cloud_rule, ns, d['name'], d['keywords'], d['body_keywords'], d['senders'], d['logic'])
        w.ok.connect(_done)
        w.err.connect(lambda m: QMessageBox.warning(self, '错误', m))
        w.start()
        self._workers.append(w)

    def _cloud_rule_edit(self):
        rule = self._selected_from(self._cloud_table, self._cloud_rules_data)
        if not rule:
            QMessageBox.information(self, '提示', '请先选择一条规则')
            return
        dlg = RuleDialog(rule=rule, parent=self)
        if dlg.exec_() != QDialog.Accepted:
            return
        def _done(_): self._load_cloud_rules()
        w = Worker(backend.edit_cloud_rule, rule['id'], dlg.result_data())
        w.ok.connect(_done)
        w.err.connect(lambda m: QMessageBox.warning(self, '错误', m))
        w.start()
        self._workers.append(w)

    def _cloud_rule_delete(self):
        rule = self._selected_from(self._cloud_table, self._cloud_rules_data)
        if not rule:
            QMessageBox.information(self, '提示', '请先选择一条规则')
            return
        if QMessageBox.question(self, '确认', f'确定删除云端规则「{rule["name"]}」？') != QMessageBox.Yes:
            return
        def _done(_): self._load_cloud_rules()
        w = Worker(backend.delete_cloud_rule, rule['id'])
        w.ok.connect(_done)
        w.err.connect(lambda m: QMessageBox.warning(self, '错误', m))
        w.start()
        self._workers.append(w)

    def _cloud_rule_toggle(self):
        rule = self._selected_from(self._cloud_table, self._cloud_rules_data)
        if not rule:
            QMessageBox.information(self, '提示', '请先选择一条规则')
            return
        def _done(_): self._load_cloud_rules()
        w = Worker(backend.edit_cloud_rule, rule['id'], {'enabled': not rule['enabled']})
        w.ok.connect(_done)
        w.err.connect(lambda m: QMessageBox.warning(self, '错误', m))
        w.start()
        self._workers.append(w)

    # ── 本地规则操作 ──────────────────────────────────
    def _load_rules(self):
        self._rules_data = rules_mod.load()
        self._render_rule_table(self._rule_table, self._rules_data)

    def _rule_add(self):
        dlg = RuleDialog(parent=self)
        if dlg.exec_() != QDialog.Accepted:
            return
        d = dlg.result_data()
        rules_mod.add(d['name'], d['keywords'], d['body_keywords'], d['senders'], d['logic'])
        self._load_rules()

    def _rule_edit(self):
        rule = self._selected_from(self._rule_table, self._rules_data)
        if not rule:
            QMessageBox.information(self, '提示', '请先选择一条规则')
            return
        dlg = RuleDialog(rule=rule, parent=self)
        if dlg.exec_() != QDialog.Accepted:
            return
        rules_mod.edit(rule['id'], dlg.result_data())
        self._load_rules()

    def _rule_delete(self):
        rule = self._selected_from(self._rule_table, self._rules_data)
        if not rule:
            QMessageBox.information(self, '提示', '请先选择一条规则')
            return
        if QMessageBox.question(self, '确认', f'确定删除本地规则「{rule["name"]}」？') != QMessageBox.Yes:
            return
        rules_mod.delete(rule['id'])
        self._load_rules()

    def _rule_toggle(self):
        rule = self._selected_from(self._rule_table, self._rules_data)
        if not rule:
            QMessageBox.information(self, '提示', '请先选择一条规则')
            return
        rules_mod.edit(rule['id'], {'enabled': not rule['enabled']})
        self._load_rules()

    # ── 公用 ─────────────────────────────────────────
    @staticmethod
    def _selected_from(table: QTableWidget, data: list):
        if not table.selectedItems():
            return None
        row = table.currentRow()
        return data[row] if row < len(data) else None

    @staticmethod
    def _render_rule_table(table: QTableWidget, rules: list):
        table.setRowCount(0)
        for r in rules:
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, QTableWidgetItem('是' if r['enabled'] else '否'))
            table.setItem(row, 1, QTableWidgetItem(r['name']))
            table.setItem(row, 2, QTableWidgetItem(', '.join(r.get('keywords', []))))
            table.setItem(row, 3, QTableWidgetItem(', '.join(r.get('body_keywords', []))))
            table.setItem(row, 4, QTableWidgetItem(', '.join(r.get('senders', []))))
            table.setItem(row, 5, QTableWidgetItem('且' if r['logic'] == 'AND' else '或'))
            if not r['enabled']:
                for col in range(6):
                    it = table.item(row, col)
                    if it:
                        it.setForeground(Qt.gray)

    # ── 保存 ─────────────────────────────────────────────
    def _on_save(self):
        self._s['scanIntervalMinutes'] = self._interval.value()
        self._s['customJsonConfig']    = self._custom_json.toPlainText()
        self._s['scanFolders']         = sorted(self._scan_folders)
        self.accept()

    def get_settings(self) -> dict:
        return self._s


# ── 首次配置向导 ──────────────────────────────────────────
class SetupDialog(QDialog):
    """首次打开邮件标签时的强制配置：服务器 + 工号 + 命名空间"""
    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle('初始配置 — 问题定位助手')
        self.setFixedWidth(420)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self._s = dict(settings)
        self._workers = []
        self._userinfo_map = {}
        self._confirmed_uid = settings.get('userId', '')

        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        hint = QLabel('首次使用前，请完成以下基本配置：')
        hint.setStyleSheet('font-weight: bold; padding: 4px 0;')
        lay.addWidget(hint)

        form = QFormLayout()
        form.setVerticalSpacing(8)
        form.setHorizontalSpacing(8)

        # 服务器
        srv_row = QHBoxLayout()
        srv_row.setSpacing(6)
        self._server_combo = QComboBox()
        self._server_combo.setEditable(True)
        for _name in _SERVER_PRESETS:
            self._server_combo.addItem(_name)
        self._server_combo.addItem(_MANUAL_INPUT)
        self._server_combo.lineEdit().setPlaceholderText('选择预设或输入服务器地址')
        self._server_combo.setCurrentText(_url_to_display(self._s.get('backendUrl', '')) or '云核心网')
        self._server_combo.activated.connect(self._on_server_activated)
        btn_test = QPushButton('测试')
        btn_test.setFixedWidth(50)
        btn_test.clicked.connect(self._test_conn)
        srv_row.addWidget(self._server_combo, stretch=1)
        srv_row.addWidget(btn_test)
        form.addRow('服务器：', srv_row)

        btn_api_doc = QPushButton('接口实现说明 ↗')
        btn_api_doc.setFlat(True)
        btn_api_doc.setStyleSheet('color: #0078D4; text-align: left; border: none; padding: 0 2px;')
        btn_api_doc.setCursor(Qt.PointingHandCursor)
        btn_api_doc.clicked.connect(lambda: _show_api_doc(self))
        form.addRow('', btn_api_doc)

        # 工号
        self._user_id = QLineEdit(self._s.get('userId', ''))
        self._user_id.setPlaceholderText('输入姓名或工号搜索，从下拉结果中选择')
        self._user_completer = QCompleter([], self)
        self._user_completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._user_completer.setCompletionMode(QCompleter.UnfilteredPopupCompletion)
        self._user_completer.setMaxVisibleItems(8)
        self._user_id.setCompleter(self._user_completer)
        self._user_completer.activated.connect(self._on_userinfo_selected)
        self._user_search_timer = QTimer(self)
        self._user_search_timer.setSingleShot(True)
        self._user_search_timer.timeout.connect(self._search_userinfo)
        self._user_id.textEdited.connect(self._on_uid_edited)
        form.addRow('工号：', self._user_id)

        # Namespace
        ns_row = QHBoxLayout()
        ns_row.setSpacing(6)
        self._ns_combo = QComboBox()
        btn_ns = QPushButton('刷新')
        btn_ns.setFixedWidth(50)
        btn_ns.clicked.connect(self._load_namespaces)
        ns_row.addWidget(self._ns_combo, stretch=1)
        ns_row.addWidget(btn_ns)
        form.addRow('Namespace：', ns_row)

        lay.addLayout(form)

        btn_ok = QPushButton('完成设置')
        btn_ok.setObjectName('btnPrimary')
        btn_ok.setMinimumHeight(30)
        btn_ok.clicked.connect(self._confirm)
        lay.addWidget(btn_ok)

        self._load_namespaces()

    def _on_server_activated(self, index: int):
        if self._server_combo.itemText(index) == _MANUAL_INPUT:
            self._server_combo.setCurrentText('')
            self._server_combo.lineEdit().setFocus()
        else:
            self._load_namespaces()

    def _get_url(self) -> str:
        return _resolve_server_url(self._server_combo.currentText())

    def _test_conn(self):
        url = self._get_url()
        if not url:
            QMessageBox.warning(self, '错误', '请选择或输入服务器地址')
            return
        backend.set_base(url)
        ok = backend.ping()
        QMessageBox.information(self, '连接测试', '连接成功 ✓' if ok else '连接失败，请检查服务器地址')

    def _load_namespaces(self):
        url = self._get_url()
        if not url:
            return
        backend.set_base(url)
        cur = self._s.get('namespace', '')

        def _done(items):
            self._ns_combo.clear()
            self._ns_combo.addItem('-- 请选择 --', '')
            for it in sorted(items, key=lambda x: x.get('id', 0)):
                self._ns_combo.addItem(it['name'], it['name'])
            idx = self._ns_combo.findData(cur)
            if idx >= 0:
                self._ns_combo.setCurrentIndex(idx)

        w = Worker(backend.get_namespaces)
        w.ok.connect(_done)
        w.start()
        self._workers.append(w)

    def _search_userinfo(self):
        query = self._user_id.text().strip()
        url = self._get_url()
        if not query or not url:
            return
        backend.set_base(url)

        def _done(items):
            self._userinfo_map = {r["label"]: r["value"] for r in items}
            self._user_completer.setModel(QStringListModel(list(self._userinfo_map)))
            if self._userinfo_map:
                self._user_completer.complete()

        w = Worker(backend.get_userinfo, query)
        w.ok.connect(_done)
        w.start()
        self._workers.append(w)

    def _on_uid_edited(self):
        self._confirmed_uid = ''
        self._user_search_timer.start(400)

    def _on_userinfo_selected(self, text: str):
        value = self._userinfo_map.get(text, text)
        self._confirmed_uid = value
        QTimer.singleShot(0, lambda: self._user_id.setText(value))

    def _confirm(self):
        url = self._get_url()
        ns = self._ns_combo.currentData() or ''

        if not url:
            QMessageBox.warning(self, '错误', '请选择或输入服务器地址')
            return
        if not self._confirmed_uid:
            QMessageBox.warning(self, '错误', '请搜索并从下拉结果中选择工号')
            return
        if not ns:
            QMessageBox.warning(self, '错误', '请选择命名空间')
            return

        self._s['backendUrl'] = url
        self._s['userId'] = self._confirmed_uid
        self._s['namespace'] = ns
        self.accept()

    def get_settings(self) -> dict:
        return self._s
