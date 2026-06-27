"""「本地导入」页：展示手动导入过的 .msg（本机记录），支持本地删除。"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QMessageBox,
)

from modules.email import imported_store


class LocalImportPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._data = []

        lay = QVBoxLayout(self)

        hint = QLabel(
            '手动导入的 .msg 会立即推送到远端，不会出现在「邮件」列表；此处仅为本机记录，'
            '方便你回看导入过哪些。删除只移除本机这条记录，不会从后端删除已推送的邮件。'
        )
        hint.setWordWrap(True)
        hint.setStyleSheet('color:#888;font-size:12px')
        lay.addWidget(hint)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(['主题', '发件人', '收件时间', '导入时间'])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._table.setColumnWidth(1, 150)
        self._table.setColumnWidth(2, 150)
        self._table.setColumnWidth(3, 150)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        lay.addWidget(self._table)

        row = QHBoxLayout()
        btn_refresh = QPushButton('刷新')
        btn_del = QPushButton('删除（仅本机记录）')
        btn_del.setObjectName('btnDanger')
        btn_refresh.clicked.connect(self.refresh)
        btn_del.clicked.connect(self._delete)
        row.addWidget(btn_refresh)
        row.addStretch()
        row.addWidget(btn_del)
        lay.addLayout(row)

        self.refresh()

    def refresh(self):
        self._data = imported_store.load()
        self._table.setRowCount(0)
        for rec in self._data:
            r = self._table.rowCount()
            self._table.insertRow(r)
            self._table.setItem(r, 0, QTableWidgetItem(rec.get('subject', '')))
            self._table.setItem(
                r, 1, QTableWidgetItem(rec.get('sender_name', '') or rec.get('sender_email', '')))
            self._table.setItem(
                r, 2, QTableWidgetItem((rec.get('received_time', '') or '').replace('T', ' ')))
            self._table.setItem(r, 3, QTableWidgetItem(rec.get('imported_at', '')))

    def _delete(self):
        if not self._table.selectedItems():
            QMessageBox.information(self, '提示', '请先选择一行')
            return
        row = self._table.currentRow()
        if row < 0 or row >= len(self._data):
            return
        rec = self._data[row]
        ret = QMessageBox.question(
            self, '删除本机记录',
            '只会从本机「本地导入」列表移除这条记录，\n'
            '不会从后端删除已推送的邮件。\n\n确定删除？',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret != QMessageBox.Yes:
            return
        imported_store.delete(rec.get('item_id'))
        self.refresh()
