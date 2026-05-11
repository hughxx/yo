"""邮件模块：设置对话框 + 规则编辑对话框"""
from PyQt5.QtWidgets import *
from PyQt5.QtCore import Qt, QTimer, QStringListModel
from PyQt5.QtGui import QFont

from modules.email import outlook
from modules.email import rules as rules_mod
import backend
from utils import Worker


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
        self.setWindowTitle('邮件设置')
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
        w = QWidget()
        lay = QFormLayout(w)
        lay.setVerticalSpacing(4)
        lay.setHorizontalSpacing(8)
        lay.setContentsMargins(8, 6, 8, 6)

        row1 = QHBoxLayout()
        self._backend_url = QLineEdit(self._s.get('backendUrl', ''))
        self._backend_url.setPlaceholderText('http://localhost:8023')
        btn_test = QPushButton('测试连接')
        btn_test.setFixedWidth(80)
        btn_test.clicked.connect(self._test_conn)
        row1.addWidget(self._backend_url)
        row1.addWidget(btn_test)
        lay.addRow('后端地址：', row1)

        self._user_id = QLineEdit(self._s.get('userId', ''))
        self._user_id.setPlaceholderText('输入姓名或工号搜索')
        self._userinfo_map   = {}   # display → sAMAccountName
        self._selecting_user = False
        self._user_completer = QCompleter([], self)
        self._user_completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._user_completer.setCompletionMode(QCompleter.UnfilteredPopupCompletion)
        self._user_completer.setMaxVisibleItems(8)
        self._user_id.setCompleter(self._user_completer)
        self._user_completer.activated.connect(self._on_userinfo_selected)
        self._user_search_timer = QTimer(self)
        self._user_search_timer.setSingleShot(True)
        self._user_search_timer.timeout.connect(self._search_userinfo)
        self._user_id.textEdited.connect(lambda: self._user_search_timer.start(400))
        lay.addRow('工号：', self._user_id)

        row3 = QHBoxLayout()
        self._ns_combo = QComboBox()
        btn_ns = QPushButton('刷新')
        btn_ns.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        btn_ns.setMinimumWidth(50)
        btn_ns.clicked.connect(self._load_namespaces)
        row3.addWidget(self._ns_combo)
        row3.addWidget(btn_ns)
        lay.addRow('Namespace：', row3)

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

        self._load_namespaces()
        return w

    def _search_userinfo(self):
        if self._selecting_user:
            return
        query = self._user_id.text().strip()
        if not query:
            return
        url = self._backend_url.text().strip() or self._s.get('backendUrl', '')
        if not url:
            return
        backend.set_base(url)

        def _done(items):
            self._userinfo_map = {f'{r["label"]} ({r["value"]})': r['value'] for r in items}
            self._user_completer.setModel(QStringListModel(list(self._userinfo_map)))
            if self._userinfo_map:
                self._user_completer.complete()

        w = Worker(backend.get_userinfo, query)
        w.ok.connect(_done)
        w.start()
        self._workers.append(w)

    def _on_userinfo_selected(self, display_text: str):
        value = self._userinfo_map.get(display_text, display_text)
        self._selecting_user = True
        self._user_id.setText(value)
        self._selecting_user = False

    def _test_conn(self):
        url = self._backend_url.text().strip()
        if not url:
            QMessageBox.warning(self, '错误', '请先输入后端地址')
            return
        backend.set_base(url)
        ok = backend.ping()
        QMessageBox.information(self, '连接测试', '连接成功 ✓' if ok else '连接失败，请检查后端地址')

    def _load_namespaces(self):
        url = self._backend_url.text().strip() or self._s.get('backendUrl', '')
        backend.set_base(url)
        cur = self._s.get('namespace', '')

        def _done(items):
            self._ns_combo.clear()
            self._ns_combo.addItem('-- 请选择 --', '')
            for it in items:
                self._ns_combo.addItem(it['name'], it['name'])
            idx = self._ns_combo.findData(cur)
            if idx >= 0:
                self._ns_combo.setCurrentIndex(idx)

        w = Worker(backend.get_namespaces)
        w.ok.connect(_done)
        w.start()
        self._workers.append(w)

    # ── 文件夹 tab ───────────────────────────────────────
    def _make_folders(self):
        w = QWidget()
        lay = QVBoxLayout(w)

        hint = QLabel('勾选要扫描的文件夹，留空则只扫描默认收件箱。')
        hint.setStyleSheet('color: #555; font-size: 11px;')
        lay.addWidget(hint)

        top = QHBoxLayout()
        btn_load = QPushButton('从 Outlook 加载文件夹')
        self._folder_hint = QLabel('')
        self._folder_hint.setStyleSheet('color: #888; font-size: 11px;')
        top.addWidget(btn_load)
        top.addWidget(self._folder_hint)
        top.addStretch()
        lay.addLayout(top)

        self._folder_list = QListWidget()
        self._folder_list.setAlternatingRowColors(True)
        lay.addWidget(self._folder_list)

        btn_load.clicked.connect(self._load_outlook_folders)

        # 预填已选
        self._scan_folders = set(self._s.get('scanFolders', []))
        return w

    def _load_outlook_folders(self):
        self._folder_hint.setText('加载中...')

        def _work():
            return outlook.folder_list()

        def _done(folders):
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
        if self._tabs.tabText(idx) == '规则':
            self._load_cloud_rules()
            self._load_rules()

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
        url = self._backend_url.text().strip()
        if not url:
            QMessageBox.warning(self, '错误', '请输入后端地址')
            self._tabs.setCurrentIndex(0)
            return
        self._s['backendUrl']          = url
        self._s['userId']              = self._user_id.text().strip()
        self._s['namespace']           = self._ns_combo.currentData() or ''
        self._s['scanIntervalMinutes'] = self._interval.value()
        self._s['customJsonConfig']    = self._custom_json.toPlainText()
        self._s['scanFolders']         = sorted(self._scan_folders)
        self.accept()

    def get_settings(self) -> dict:
        return self._s
