"""问题自动回复面板：配置 prompt + 机器人工号，监听所有最近会话，自动回复。"""
import json
import os

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QPlainTextEdit, QFormLayout,
)
from PyQt5.QtCore import Qt

import store
from modules.welink.autoreply_monitor import AutoReplyMonitor

_CONFIG_FILE = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 '..', '..', '..', '.welink_autoreply.json')
)


def _load_cfg() -> dict:
    try:
        with open(_CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cfg(cfg: dict):
    with open(_CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


class AutoReplyPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._monitor = None
        self._build_ui()
        self._load_config()

    # ── UI ────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 8)
        root.setSpacing(8)

        # ── 状态行 ──
        hdr = QHBoxLayout()
        hdr.addStretch()
        self._dot = QLabel('●')
        self._dot.setStyleSheet('color:#ccc;font-size:14px')
        self._status_lbl = QLabel('未运行')
        self._status_lbl.setStyleSheet('color:#888;font-size:11px')
        self._btn_toggle = QPushButton('开始监听')
        self._btn_toggle.setObjectName('btnSync')
        self._btn_toggle.setFixedWidth(80)
        self._btn_toggle.clicked.connect(self._toggle_monitor)
        hdr.addWidget(self._dot)
        hdr.addWidget(self._status_lbl)
        hdr.addSpacing(8)
        hdr.addWidget(self._btn_toggle)
        root.addLayout(hdr)

        # ── 配置表单 ──
        form = QFormLayout()
        form.setSpacing(6)
        form.setContentsMargins(0, 0, 0, 0)

        self._bot_id_edit = QLineEdit()
        self._bot_id_edit.setPlaceholderText('机器人自身工号，用于群聊 @ 检测和过滤自发消息')
        form.addRow('机器人工号:', self._bot_id_edit)

        self._prompt_edit = QPlainTextEdit()
        self._prompt_edit.setPlaceholderText(
            '系统 Prompt，告诉 AI 如何回答。\n'
            '例：你是一名网络问题专家，请根据用户描述给出简洁的排查建议，不超过 200 字。'
        )
        self._prompt_edit.setFixedHeight(100)
        form.addRow('回复 Prompt:', self._prompt_edit)

        hint = QLabel(
            '· 私聊：监听最近 20 个会话中的所有新消息（简单应答词自动过滤）\n'
            '· 群聊：仅在 @ 机器人工号时触发'
        )
        hint.setStyleSheet('color:#888;font-size:10px')
        hint.setWordWrap(True)
        form.addRow('', hint)

        root.addLayout(form)

        _sep = QLabel()
        _sep.setFixedHeight(1)
        _sep.setStyleSheet('background:#ddd;margin:4px 0')
        root.addWidget(_sep)

        # ── 日志 ──
        root.addWidget(QLabel('运行日志'))
        self._log_edit = QPlainTextEdit()
        self._log_edit.setReadOnly(True)
        self._log_edit.setMaximumBlockCount(300)
        self._log_edit.setStyleSheet(
            'background:#1e1e1e;color:#d4d4d4;'
            'font-family:Consolas,monospace;font-size:11px'
        )
        root.addWidget(self._log_edit, stretch=1)

    # ── config ────────────────────────────────────────────────────

    def _load_config(self):
        cfg = _load_cfg()
        self._bot_id_edit.setText(cfg.get('botId', ''))
        self._prompt_edit.setPlainText(cfg.get('prompt', ''))

    def _save_config(self):
        _save_cfg({
            'botId':  self._bot_id_edit.text().strip(),
            'prompt': self._prompt_edit.toPlainText().strip(),
        })

    # ── monitor ───────────────────────────────────────────────────

    def _toggle_monitor(self):
        if self._monitor and self._monitor.isRunning():
            self._stop_monitor()
        else:
            self._start_monitor()

    def _start_monitor(self):
        self._save_config()
        cfg = _load_cfg()
        s   = store.load_settings()

        self._monitor = AutoReplyMonitor(
            prompt        = cfg.get('prompt', ''),
            bot_id        = cfg.get('botId', ''),
            backend_base  = s.get('backendUrl', 'http://localhost:8023'),
            poll_interval = s.get('welinkPollInterval', 5),
        )
        self._monitor.log_signal.connect(self._append_log)
        self._monitor.start()
        self._set_running(True)

    def _stop_monitor(self):
        if self._monitor:
            self._monitor.stop()
            self._monitor.wait(3000)
            self._monitor = None
        self._set_running(False)

    def _set_running(self, running: bool):
        self._bot_id_edit.setEnabled(not running)
        self._prompt_edit.setEnabled(not running)
        if running:
            self._dot.setStyleSheet('color:#008C64;font-size:14px')
            self._status_lbl.setText('监听中')
            self._status_lbl.setStyleSheet('color:#008C64;font-size:11px;font-weight:bold')
            self._btn_toggle.setText('停止监听')
            self._btn_toggle.setObjectName('btnDanger')
        else:
            self._dot.setStyleSheet('color:#ccc;font-size:14px')
            self._status_lbl.setText('未运行')
            self._status_lbl.setStyleSheet('color:#888;font-size:11px;font-weight:normal')
            self._btn_toggle.setText('开始监听')
            self._btn_toggle.setObjectName('btnSync')
        self._btn_toggle.style().unpolish(self._btn_toggle)
        self._btn_toggle.style().polish(self._btn_toggle)

    # ── slots ─────────────────────────────────────────────────────

    def _append_log(self, text: str):
        self._log_edit.appendPlainText(text)

    # ── lifecycle ─────────────────────────────────────────────────

    def activate(self): pass

    def deactivate(self): pass

    def closeEvent(self, event):
        self._stop_monitor()
        super().closeEvent(event)
