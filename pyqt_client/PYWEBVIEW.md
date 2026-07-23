# pywebview 客户端

客户端现采用以下结构：

- 前端：`web/index.html`、`web/styles.css`、`web/app.js`（原生 HTML/CSS/JS）
- 宿主：`main.py`（pywebview，Windows 强制使用 Edge Chromium/WebView2）
- JS Bridge：`webview_api.py`
- 业务：原有 `backend.py`、`store.py`、`modules/email`、`modules/welink`
- 打包：PyInstaller onefile（`pywebview.spec`）

宿主负责系统托盘、邮件定时任务、WeLink 历史聊天分页挖掘和后台线程生命周期；关闭窗口只隐藏
到托盘。聊天记录按群组/用户独立处理，支持手动选择、增量定时和全量定时，不包含自动回复和聊天记录 ZIP 导入。
UI 不展示运行日志。日志统一写到可执行文件同级的 `log/app.log`，按 5 MB 滚动、保留
5 个备份，清理 14 天前文件并限制日志目录总量不超过约 30 MB。

## 开发运行

```powershell
cd pyqt_client
python -m pip install -r requirements.txt
python main.py
```

## 打包

```powershell
cd pyqt_client
python build.py
```

产物位于 `pyqt_client/dist/CoreMiner.exe`。目标电脑需要安装 Microsoft Edge
WebView2 Runtime；Windows 10/11 的正常更新版本通常已包含它。

服务端仍由 `python -m server` 启动，HTTP API 与原 PyQt 客户端保持兼容，无需随 UI
技术迁移而修改。
