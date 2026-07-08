"""邮件模块：设置对话框 + 规则编辑对话框"""
import time
import webbrowser

_REPO_URL = 'https://openx.huawei.com/ProblemLocating/overview'

from PyQt5.QtWidgets import *
from PyQt5.QtCore import Qt, QTimer, QStringListModel, QEvent
from PyQt5.QtGui import QFont

import backend
from utils import Worker

_OFFLINE_LABEL = '离线（仅本地导出）'
_SERVER_PRESETS = {
    '云核心网': 'https://coreinsight-beta.rnd.huawei.com/collection',
    _OFFLINE_LABEL: backend.OFFLINE,
}
_MANUAL_INPUT = '手动输入URL'

_API_DOC = """\
自定义服务器须实现以下 HTTP 接口（基础路径 /api/email/）：

━━ 必需接口 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GET  /api/config/ping
  响应: {"Success": true, "Message": "pong"}

GET  /api/config/namespaces
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

━━ 必需接口（用户搜索）━━━━━━━━━━━━━━━━━━━━━━
GET /api/config/userinfo?info=xxx
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


# ── 首次配置向导 ──────────────────────────────────────────
class SetupDialog(QDialog):
    """首次打开邮件标签时的强制配置：服务器 + 工号 + 命名空间。

    mandatory=True（首启强制配置）时：去掉关闭按钮、吞掉 Esc/关闭，普通用户关不掉；
    管理员可在「额外配置」框上**连续三击**隐藏地关闭（不保存）。
    mandatory=False（齿轮打开设置）时为普通可关闭对话框。
    """
    def __init__(self, settings: dict, parent=None, mandatory: bool = False):
        super().__init__(parent)
        self.setWindowTitle('初始配置 — 问题定位助手')
        self.setFixedWidth(420)
        flags = self.windowFlags() & ~Qt.WindowContextHelpButtonHint
        self._mandatory = mandatory
        self._allow_close = not mandatory
        self._click_ts = []
        if mandatory:
            # 去掉关闭按钮，并设为模态，逼用户面对它
            flags &= ~Qt.WindowCloseButtonHint
            flags |= Qt.CustomizeWindowHint | Qt.WindowTitleHint
            self.setModal(True)
        self.setWindowFlags(flags)
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
        btn_test.clicked.connect(self._test_conn)
        srv_row.addWidget(self._server_combo, stretch=1)
        srv_row.addWidget(btn_test)
        form.addRow('服务器：', srv_row)

        btn_repo = QPushButton('内源代码仓地址 ↗')
        btn_repo.setFlat(True)
        btn_repo.setStyleSheet('color: #2b54cc; text-align: left; border: none; padding: 0 2px;')
        btn_repo.setCursor(Qt.PointingHandCursor)
        btn_repo.clicked.connect(lambda: webbrowser.open(_REPO_URL))
        form.addRow('', btn_repo)

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
        btn_ns.clicked.connect(self._load_namespaces)
        ns_row.addWidget(self._ns_combo, stretch=1)
        ns_row.addWidget(btn_ns)
        form.addRow('Namespace：', ns_row)

        # 文件保存目录（html / md 本地保存位置，可改）
        dir_row = QHBoxLayout()
        dir_row.setSpacing(6)
        self._out_dir = QLineEdit(self._s.get('outputDir', ''))
        self._out_dir.setPlaceholderText('html / md 本地保存目录')
        btn_dir = QPushButton('更改目录')
        btn_dir.clicked.connect(self._pick_out_dir)
        dir_row.addWidget(self._out_dir, stretch=1)
        dir_row.addWidget(btn_dir)
        form.addRow('文件保存目录：', dir_row)

        # 额外配置（可选 JSON，随每封邮件作为 ExtraInfo 上报）
        self._custom_json = QPlainTextEdit(self._s.get('customJsonConfig', '{}'))
        self._custom_json.setFixedHeight(64)
        self._custom_json.setFont(QFont('Consolas', 10))
        self._custom_json.setPlaceholderText('{}')
        form.addRow('额外配置：', self._custom_json)
        # 隐藏的管理员关闭：在「额外配置」框上连续三击
        self._custom_json.viewport().installEventFilter(self)

        lay.addLayout(form)

        btn_ok = QPushButton('完成设置')
        btn_ok.setObjectName('btnPrimary')
        btn_ok.setMinimumHeight(30)
        btn_ok.clicked.connect(self._confirm)
        lay.addWidget(btn_ok)

        self._load_namespaces()

    # ── 强制模式下的关闭控制 + 隐藏管理员关闭 ──────────────
    def eventFilter(self, obj, event):
        if (obj is self._custom_json.viewport()
                and event.type() == QEvent.MouseButtonPress):
            now = time.monotonic()
            self._click_ts = [t for t in self._click_ts if now - t < 0.8] + [now]
            if len(self._click_ts) >= 3:
                self._click_ts = []
                self._admin_close()
        return super().eventFilter(obj, event)

    def _admin_close(self):
        """管理员三击「额外配置」：放行关闭并直接关掉（不保存）。"""
        self._allow_close = True
        self.reject()

    def closeEvent(self, event):
        if self._allow_close:
            event.accept()
        else:
            event.ignore()   # 强制模式：普通用户关不掉

    def reject(self):
        if self._allow_close:
            super().reject()
        # 强制模式下吞掉 Esc / 取消

    def keyPressEvent(self, event):
        if self._mandatory and not self._allow_close and event.key() == Qt.Key_Escape:
            return
        super().keyPressEvent(event)

    def _pick_out_dir(self):
        d = QFileDialog.getExistingDirectory(self, '选择文件保存目录', self._out_dir.text() or '')
        if d:
            self._out_dir.setText(d)

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
        if backend.is_offline_url(url):
            QMessageBox.information(self, '离线模式', '离线模式不连接服务器，处理结果只保存到本地目录。')
            return
        backend.set_base(url)
        ok = backend.ping()
        QMessageBox.information(self, '连接测试', '连接成功 ✓' if ok else '连接失败，请检查服务器地址')

    def _load_namespaces(self):
        url = self._get_url()
        if not url or backend.is_offline_url(url):
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
        if not query or not url or backend.is_offline_url(url):
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

        if not url:
            QMessageBox.warning(self, '错误', '请选择或输入服务器地址')
            return

        # 离线：不连服务器，工号/命名空间都无从校验，只要求填好本地保存目录
        if backend.is_offline_url(url):
            out = self._out_dir.text().strip()
            if not out:
                QMessageBox.warning(self, '错误', '离线模式请先设置「文件保存目录」')
                return
            self._s['backendUrl'] = url
            self._s['userId'] = self._user_id.text().strip()
            self._s['namespace'] = ''
            self._s['customJsonConfig'] = self._custom_json.toPlainText()
            self._s['outputDir'] = out
            self.accept()
            return

        ns = self._ns_combo.currentData() or ''
        if not self._confirmed_uid:
            QMessageBox.warning(self, '错误', '请搜索并从下拉结果中选择工号')
            return
        if not ns:
            QMessageBox.warning(self, '错误', '请选择命名空间')
            return

        self._s['backendUrl'] = url
        self._s['userId'] = self._confirmed_uid
        self._s['namespace'] = ns
        self._s['customJsonConfig'] = self._custom_json.toPlainText()
        self._s['outputDir'] = self._out_dir.text().strip()
        self.accept()

    def get_settings(self) -> dict:
        return self._s
