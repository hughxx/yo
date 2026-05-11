"""设置对话框 + 规则编辑对话框"""
from PyQt5.QtWidgets import *
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont

import cli
import backend
import store


# ── 通用工作线程 ──────────────────────────────────────────
class Worker(QThread):
    ok  = pyqtSignal(object)
    err = pyqtSignal(str)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn, self._a, self._kw = fn, args, kwargs

    def run(self):
        try:
            self.ok.emit(self._fn(*self._a, **self._kw))
        except Exception as e:
            self.err.emit(str(e))


# ── 规则编辑对话框 ────────────────────────────────────────
class RuleDialog(QDialog):
    def __init__(self, rule=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle('编辑规则' if rule else '添加规则')
        self.setFixedWidth(420)
        self.rule = rule

        self.name_edit     = QLineEdit(rule['name']                 if rule else '')
        self.keywords_edit = QLineEdit(', '.join(rule['keywords'])  if rule else '')
        self.senders_edit  = QLineEdit(', '.join(rule['senders'])   if rule else '')
        self.logic_combo   = QComboBox()
        self.logic_combo.addItems(['OR（任一命中）', 'AND（同时命中）'])
        if rule and rule.get('logic') == 'AND':
            self.logic_combo.setCurrentIndex(1)

        form = QFormLayout()
        form.addRow('规则名称 *', self.name_edit)
        form.addRow('关键词',     self.keywords_edit)
        form.addRow('发件人',     self.senders_edit)
        form.addRow('匹配逻辑',   self.logic_combo)

        self.keywords_edit.setPlaceholderText('逗号分隔，匹配邮件主题')
        self.senders_edit.setPlaceholderText('逗号分隔，邮箱或姓名')

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
            'name':     self.name_edit.text().strip(),
            'keywords': [k.strip() for k in self.keywords_edit.text().split(',') if k.strip()],
            'senders':  [s.strip() for s in self.senders_edit.text().split(',')  if s.strip()],
            'logic':    'AND' if self.logic_combo.currentIndex() == 1 else 'OR',
        }


# ── 设置对话框 ────────────────────────────────────────────
class SettingsDialog(QDialog):
    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle('设置')
        self.setMinimumSize(700, 480)
        self._s   = dict(settings)
        self._workers = []   # 防止 GC

        self._tabs = QTabWidget()
        self._tabs.addTab(self._make_basic(),   '基本')
        self._tabs.addTab(self._make_conn(),    '连接')
        self._tabs.addTab(self._make_folders(), '文件夹')
        self._tabs.addTab(self._make_rules(),   '规则')
        self._tabs.addTab(self._make_cache(),   '缓存')
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
        lay.setSpacing(10)

        # 后端地址
        row1 = QHBoxLayout()
        self._backend_url = QLineEdit(self._s.get('backendUrl', ''))
        self._backend_url.setPlaceholderText('http://localhost:8023')
        btn_test = QPushButton('测试连接')
        btn_test.setFixedWidth(80)
        btn_test.clicked.connect(self._test_conn)
        row1.addWidget(self._backend_url)
        row1.addWidget(btn_test)
        lay.addRow('后端地址：', row1)

        # 工号
        self._user_id = QLineEdit(self._s.get('userId', ''))
        lay.addRow('工号：', self._user_id)

        # Namespace
        row3 = QHBoxLayout()
        self._ns_combo = QComboBox()
        self._ns_combo.setEditable(False)
        btn_ns = QPushButton('↻')
        btn_ns.setFixedWidth(28)
        btn_ns.clicked.connect(self._load_namespaces)
        row3.addWidget(self._ns_combo)
        row3.addWidget(btn_ns)
        lay.addRow('Namespace：', row3)

        # 扫描间隔
        self._interval = QSpinBox()
        self._interval.setRange(1, 1440)
        self._interval.setValue(self._s.get('scanIntervalMinutes', 60))
        self._interval.setSuffix(' 分钟')
        self._interval.setMaximumWidth(120)
        lay.addRow('扫描间隔：', self._interval)

        # 额外配置
        self._custom_json = QPlainTextEdit(self._s.get('customJsonConfig', '{}'))
        self._custom_json.setFixedHeight(100)
        self._custom_json.setFont(QFont('Consolas', 10))
        lay.addRow('额外配置：', self._custom_json)

        # 初始加载 namespace
        self._load_namespaces()
        return w

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

    # ── 连接 tab ─────────────────────────────────────────
    def _make_conn(self):
        w = QWidget()
        lay = QFormLayout(w)
        lay.setSpacing(10)

        self._conn_email    = QLineEdit()
        self._conn_email.setPlaceholderText('user@company.com')
        self._conn_password = QLineEdit()
        self._conn_password.setEchoMode(QLineEdit.Password)
        self._conn_password.setPlaceholderText('每次保存需重新输入')
        self._conn_ews_url  = QLineEdit()
        self._conn_ews_url.setPlaceholderText('留空则自动发现（autodiscover）')

        lay.addRow('邮箱地址：', self._conn_email)
        lay.addRow('密码：',     self._conn_password)
        lay.addRow('EWS 地址：', self._conn_ews_url)

        btn_save = QPushButton('保存并验证')
        btn_save.setObjectName('btnPrimary')
        btn_save.clicked.connect(self._save_conn)
        lay.addRow('', btn_save)

        self._conn_status = QLabel('')
        self._conn_status.setWordWrap(True)
        lay.addRow('', self._conn_status)
        return w

    def _on_tab_changed(self, idx):
        tab_name = self._tabs.tabText(idx)
        if tab_name == '连接':
            self._load_conn_config()
        elif tab_name == '文件夹':
            self._load_scan_folders()
        elif tab_name == '规则':
            self._load_rules()
        elif tab_name == '缓存':
            self._update_cache_count()

    def _load_conn_config(self):
        def _done(res):
            self._conn_email.setText(res.get('email', ''))
            self._conn_ews_url.setText(res.get('ews_url', ''))
            self._conn_status.setText('')
        def _fail(_):
            self._conn_status.setText('（未配置）')

        w = Worker(cli.config_get)
        w.ok.connect(_done)
        w.err.connect(_fail)
        w.start()
        self._workers.append(w)

    def _save_conn(self):
        email    = self._conn_email.text().strip()
        password = self._conn_password.text().strip()
        ews_url  = self._conn_ews_url.text().strip()
        if not email:
            QMessageBox.warning(self, '错误', '请输入邮箱地址')
            return
        if not password:
            QMessageBox.warning(self, '错误', '请输入密码')
            return

        self._conn_status.setText('验证中...')

        def _done(_):
            self._conn_status.setText('✓ 连接配置已保存，EWS 验证成功')
        def _fail(msg):
            if '凭据已保存' in msg:
                self._conn_status.setText(f'⚠ {msg}')
            else:
                self._conn_status.setText(f'✗ {msg}')

        w = Worker(cli.config_set, email, password, ews_url)
        w.ok.connect(_done)
        w.err.connect(_fail)
        w.start()
        self._workers.append(w)

    # ── 文件夹 tab ───────────────────────────────────────
    def _make_folders(self):
        w = QWidget()
        lay = QVBoxLayout(w)

        top = QHBoxLayout()
        btn_load = QPushButton('加载邮箱文件夹')
        self._folders_hint = QLabel('连接 EWS 获取可用文件夹')
        self._folders_hint.setStyleSheet('color: #888; font-size: 11px;')
        top.addWidget(btn_load)
        top.addWidget(self._folders_hint)
        top.addStretch()
        lay.addLayout(top)

        self._all_folders_list = QListWidget()
        self._all_folders_list.setMaximumHeight(180)
        lay.addWidget(self._all_folders_list)

        lay.addWidget(QLabel('已配置的扫描目录：'))
        self._scan_folders_list = QListWidget()
        self._scan_folders_list.setMaximumHeight(120)
        lay.addWidget(self._scan_folders_list)

        btn_load.clicked.connect(self._load_all_folders)
        self._all_folders_list.itemChanged.connect(self._on_folder_checked)
        return w

    def _load_scan_folders(self):
        def _done(res):
            self._scan_folders_list.clear()
            for f in res.get('scan_folders', []):
                item = QListWidgetItem(f)
                item.setCheckState(Qt.Checked)
                self._scan_folders_list.addItem(item)
            self._sync_folder_checks()
        w = Worker(cli.folder_show)
        w.ok.connect(_done)
        w.start()
        self._workers.append(w)

    def _load_all_folders(self):
        self._folders_hint.setText('加载中...')
        def _done(res):
            self._folders_hint.setText(f'找到 {len(res["folders"])} 个文件夹')
            self._all_folders_list.blockSignals(True)
            self._all_folders_list.clear()
            scan = self._get_scan_folder_names()
            for f in res['folders']:
                item = QListWidgetItem(f['name'])
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked if f['name'] in scan else Qt.Unchecked)
                self._all_folders_list.addItem(item)
            self._all_folders_list.blockSignals(False)
        def _fail(msg):
            self._folders_hint.setText(f'加载失败: {msg}')
        w = Worker(cli.folder_list)
        w.ok.connect(_done)
        w.err.connect(_fail)
        w.start()
        self._workers.append(w)

    def _get_scan_folder_names(self):
        return {self._scan_folders_list.item(i).text()
                for i in range(self._scan_folders_list.count())}

    def _sync_folder_checks(self):
        scan = self._get_scan_folder_names()
        self._all_folders_list.blockSignals(True)
        for i in range(self._all_folders_list.count()):
            item = self._all_folders_list.item(i)
            item.setCheckState(Qt.Checked if item.text() in scan else Qt.Unchecked)
        self._all_folders_list.blockSignals(False)

    def _on_folder_checked(self, item):
        path = item.text()
        if item.checkState() == Qt.Checked:
            def _done(res): self._refresh_scan_list(res['scan_folders'])
            w = Worker(cli.folder_add, path)
            w.ok.connect(_done)
            w.start()
            self._workers.append(w)
        else:
            def _done(res): self._refresh_scan_list(res['scan_folders'])
            w = Worker(cli.folder_remove, path)
            w.ok.connect(_done)
            w.start()
            self._workers.append(w)

    def _refresh_scan_list(self, folders):
        self._scan_folders_list.clear()
        for f in folders:
            item = QListWidgetItem(f)
            item.setCheckState(Qt.Checked)
            self._scan_folders_list.addItem(item)
        self._sync_folder_checks()

    # ── 规则 tab ─────────────────────────────────────────
    def _make_rules(self):
        w = QWidget()
        lay = QVBoxLayout(w)

        self._rule_table = QTableWidget(0, 5)
        self._rule_table.setHorizontalHeaderLabels(['启用', '规则名称', '关键词', '发件人', '逻辑'])
        self._rule_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self._rule_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self._rule_table.setColumnWidth(0, 40)
        self._rule_table.setColumnWidth(1, 130)
        self._rule_table.setColumnWidth(4, 50)
        self._rule_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._rule_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._rule_table.setAlternatingRowColors(True)
        lay.addWidget(self._rule_table)

        btn_row = QHBoxLayout()
        btn_add    = QPushButton('添加规则')
        btn_edit   = QPushButton('编辑规则')
        btn_del    = QPushButton('删除规则')
        btn_toggle = QPushButton('启用/禁用')
        btn_del.setObjectName('btnDanger')
        for b in (btn_add, btn_edit, btn_del, btn_toggle):
            b.setFixedHeight(26)
            btn_row.addWidget(b)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        self._rules_data = []
        btn_add.clicked.connect(self._rule_add)
        btn_edit.clicked.connect(self._rule_edit)
        btn_del.clicked.connect(self._rule_delete)
        btn_toggle.clicked.connect(self._rule_toggle)
        return w

    def _load_rules(self):
        def _done(res):
            self._rules_data = res.get('rules', [])
            self._render_rules()
        w = Worker(cli.rule_list)
        w.ok.connect(_done)
        w.start()
        self._workers.append(w)

    def _render_rules(self):
        self._rule_table.setRowCount(0)
        for r in self._rules_data:
            row = self._rule_table.rowCount()
            self._rule_table.insertRow(row)
            self._rule_table.setItem(row, 0, QTableWidgetItem('是' if r['enabled'] else '否'))
            self._rule_table.setItem(row, 1, QTableWidgetItem(r['name']))
            self._rule_table.setItem(row, 2, QTableWidgetItem(', '.join(r['keywords'])))
            self._rule_table.setItem(row, 3, QTableWidgetItem(', '.join(r['senders'])))
            self._rule_table.setItem(row, 4, QTableWidgetItem('且' if r['logic'] == 'AND' else '或'))
            if not r['enabled']:
                for col in range(5):
                    it = self._rule_table.item(row, col)
                    if it:
                        it.setForeground(Qt.gray)

    def _selected_rule(self):
        rows = self._rule_table.selectedItems()
        if not rows:
            return None, -1
        row = self._rule_table.currentRow()
        return self._rules_data[row] if row < len(self._rules_data) else None, row

    def _rule_add(self):
        dlg = RuleDialog(parent=self)
        if dlg.exec_() != QDialog.Accepted:
            return
        data = dlg.result_data()
        def _done(_): self._load_rules()
        w = Worker(cli.rule_add, data['name'], data['keywords'], data['senders'], data['logic'])
        w.ok.connect(_done)
        w.err.connect(lambda m: QMessageBox.warning(self, '错误', m))
        w.start()
        self._workers.append(w)

    def _rule_edit(self):
        rule, _ = self._selected_rule()
        if not rule:
            QMessageBox.information(self, '提示', '请先选择一条规则')
            return
        dlg = RuleDialog(rule=rule, parent=self)
        if dlg.exec_() != QDialog.Accepted:
            return
        data = dlg.result_data()
        def _done(_): self._load_rules()
        w = Worker(cli.rule_edit, rule['id'], data)
        w.ok.connect(_done)
        w.err.connect(lambda m: QMessageBox.warning(self, '错误', m))
        w.start()
        self._workers.append(w)

    def _rule_delete(self):
        rule, _ = self._selected_rule()
        if not rule:
            QMessageBox.information(self, '提示', '请先选择一条规则')
            return
        if QMessageBox.question(self, '确认', f'确定删除规则「{rule["name"]}」？') != QMessageBox.Yes:
            return
        def _done(_): self._load_rules()
        w = Worker(cli.rule_delete, rule['id'])
        w.ok.connect(_done)
        w.err.connect(lambda m: QMessageBox.warning(self, '错误', m))
        w.start()
        self._workers.append(w)

    def _rule_toggle(self):
        rule, _ = self._selected_rule()
        if not rule:
            QMessageBox.information(self, '提示', '请先选择一条规则')
            return
        def _done(_): self._load_rules()
        w = Worker(cli.rule_edit, rule['id'], {'enabled': not rule['enabled']})
        w.ok.connect(_done)
        w.err.connect(lambda m: QMessageBox.warning(self, '错误', m))
        w.start()
        self._workers.append(w)

    # ── 缓存 tab ─────────────────────────────────────────
    def _make_cache(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setAlignment(Qt.AlignTop)

        self._cache_label = QLabel()
        lay.addWidget(self._cache_label)

        btn_clear = QPushButton('清空缓存')
        btn_clear.setObjectName('btnDanger')
        btn_clear.setFixedWidth(100)
        btn_clear.clicked.connect(self._clear_cache)
        lay.addWidget(btn_clear)

        hint = QLabel('清空后下次立即同步会重新提交所有匹配邮件（后端会自动去重）')
        hint.setStyleSheet('color: #888; font-size: 11px;')
        hint.setWordWrap(True)
        lay.addWidget(hint)
        return w

    def _update_cache_count(self):
        n = store.processed_count()
        self._cache_label.setText(f'当前缓存了 <b>{n}</b> 封已处理邮件记录。')

    def _clear_cache(self):
        n = store.processed_count()
        if QMessageBox.question(
            self, '确认',
            f'当前缓存了 {n} 封已处理邮件记录。\n\n清空后下次立即同步会重新提交所有匹配邮件（后端会自动去重）。\n\n确定清空？'
        ) != QMessageBox.Yes:
            return
        store.clear_processed()
        self._update_cache_count()
        QMessageBox.information(self, '完成', '缓存已清空')

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
        self.accept()

    def get_settings(self) -> dict:
        return self._s
