"""WeLink 聊天记录手动导出面板

用户把 WeLink「导出聊天记录」打成的 zip 拖进来，解析 HistoryRecord（txt + 图片文件夹），
按时间戳把 [图片] 占位符对齐到图片文件，上传图片后拼成 HTML，POST 到现有
/api/welink/receive，复用服务端整条经验归档管线（html2md → OCR → LLM → 入库）。

rar 暂不支持，选到时提示用户解压后重新打成 zip。
"""
import hashlib
from datetime import datetime

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QPlainTextEdit, QFileDialog, QMessageBox,
)
from PyQt5.QtCore import QThread, pyqtSignal

import backend
import store
from modules.welink import chatlog_import


class _ImportWorker(QThread):
    log_signal  = pyqtSignal(str)
    done_signal = pyqtSignal(dict)   # {'duplicate': bool, 'count': int}
    err_signal  = pyqtSignal(str)

    def __init__(self, zip_path: str, group_name: str, user_id: str):
        super().__init__()
        self._zip_path   = zip_path
        self._group_name = group_name
        self._user_id    = user_id

    def run(self):
        try:
            self._log(f'读取压缩包: {self._zip_path}')
            stem, text, images = chatlog_import.read_zip(self._zip_path)
            self._log(f'图片文件 {len(images)} 张')

            messages = chatlog_import.parse_chatlog(text)
            if not messages:
                self.err_signal.emit('未解析到任何消息，请确认 txt 格式')
                return
            self._log(f'解析到 {len(messages)} 条消息')

            match = chatlog_import.match_images(messages, images)
            if match['summary']:
                self._log(match['summary'])

            self._upload_images(match)

            html = chatlog_import.build_html(messages, match)

            group_name = self._group_name or stem
            start_dt = messages[0]['ts']
            end_dt   = messages[-1]['ts']
            chat_id = (
                f'manual_{stem}_{int(start_dt.timestamp() * 1000)}_'
                f'{hashlib.md5(text.encode("utf-8", "ignore")).hexdigest()[:8]}'
            )

            self._log('上传聊天记录到服务端…')
            result = backend.receive_welink_chatlog({
                'ChatId':    chat_id,
                'GroupId':   stem,
                'GroupName': group_name,
                'StartTime': int(start_dt.timestamp() * 1000),
                'EndTime':   int(end_dt.timestamp() * 1000),
                'HtmlBody':  html,
                'UploadBy':  self._user_id,
            })
            dup = bool(result.get('Duplicate'))
            self.done_signal.emit({'duplicate': dup, 'count': len(messages)})
        except Exception as e:
            self.err_signal.emit(str(e))

    def _upload_images(self, match: dict):
        """给每个被引用到的 image dict 写入 'url'（失败为 None）。"""
        to_upload = [im for im in match['assign'] if im] + list(match['leftover'])
        if not to_upload:
            return
        self._log(f'上传图片 {len(to_upload)} 张…')
        ok = 0
        for im in to_upload:
            if 'url' in im:   # 同一张图可能被多个占位符引用，避免重复上传
                continue
            url = backend.upload_image(im['data'], im['name'])
            im['url'] = url
            if url:
                ok += 1
            else:
                self._log(f'  图片上传失败: {im["name"]}')
        self._log(f'图片上传完成: 成功 {ok}/{len(to_upload)}')

    def _log(self, msg: str):
        ts = datetime.now().strftime('%H:%M:%S')
        self.log_signal.emit(f'[{ts}] {msg}')


class ManualExportPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._build_ui()

    # ── UI ────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 8)
        root.setSpacing(8)

        intro = QLabel(
            '把 WeLink「导出聊天记录」生成的 HistoryRecord 文件夹打成 <b>zip</b> 后选择导入。<br>'
            '系统会解析 txt 与图片文件夹，按时间戳还原图片位置，归档为经验。'
        )
        intro.setWordWrap(True)
        intro.setStyleSheet('color:#344054')
        root.addWidget(intro)

        row = QHBoxLayout()
        self._path_edit = QLineEdit()
        self._path_edit.setReadOnly(True)
        self._path_edit.setPlaceholderText('未选择文件')
        btn_pick = QPushButton('选择 zip')
        btn_pick.setFixedWidth(80)
        btn_pick.clicked.connect(self._pick_file)
        row.addWidget(self._path_edit, 1)
        row.addWidget(btn_pick)
        root.addLayout(row)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel('群名(可选):'))
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText('留空则用 txt 文件名')
        row2.addWidget(self._name_edit, 1)
        self._btn_import = QPushButton('开始导入')
        self._btn_import.setObjectName('btnSync')
        self._btn_import.setFixedWidth(96)
        self._btn_import.clicked.connect(self._do_import)
        row2.addWidget(self._btn_import)
        root.addLayout(row2)

        root.addWidget(QLabel('日志'))
        self._log_edit = QPlainTextEdit()
        self._log_edit.setReadOnly(True)
        self._log_edit.setMaximumBlockCount(500)
        self._log_edit.setStyleSheet(
            'background:#f8fafc;color:#344054;border:1px solid #e1e7ef;border-radius:8px;'
            'font-family:Consolas,monospace;font-size:11px'
        )
        root.addWidget(self._log_edit, stretch=1)

        self._zip_path = ''

    # ── actions ───────────────────────────────────────────────────

    def _pick_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, '选择聊天记录压缩包', '', '聊天记录压缩包 (*.zip *.rar)')
        if not path:
            return
        if path.lower().endswith('.rar'):
            QMessageBox.information(
                self, 'rar 暂不支持',
                '暂不支持 rar。请先解压，再把 HistoryRecord 文件夹重新打成 zip 后导入。')
            return
        self._zip_path = path
        self._path_edit.setText(path)

    def _do_import(self):
        if self._worker and self._worker.isRunning():
            return
        if not self._zip_path:
            QMessageBox.warning(self, '提示', '请先选择 zip 文件')
            return

        s = store.load_settings()
        backend.set_base(s.get('backendUrl', ''))
        user_id = s.get('welinkUserId', '') or s.get('userId', '')

        self._btn_import.setEnabled(False)
        self._log_edit.clear()

        self._worker = _ImportWorker(self._zip_path, self._name_edit.text().strip(), user_id)
        self._worker.log_signal.connect(self._append_log)
        self._worker.done_signal.connect(self._on_done)
        self._worker.err_signal.connect(self._on_err)
        self._worker.start()

    def _on_done(self, info: dict):
        if info.get('duplicate'):
            self._append_log('该记录已存在，服务端已跳过。')
        else:
            self._append_log(f'导入成功（{info.get("count", 0)} 条消息），服务端正在后台解析归档。')
        self._btn_import.setEnabled(True)

    def _on_err(self, msg: str):
        self._append_log(f'导入失败: {msg}')
        QMessageBox.warning(self, '导入失败', msg)
        self._btn_import.setEnabled(True)

    def _append_log(self, text: str):
        self._log_edit.appendPlainText(text)

    # ── lifecycle ─────────────────────────────────────────────────

    def activate(self):
        pass

    def deactivate(self):
        pass

