# pywebview 客户端

客户端现采用以下结构：

- 前端：`web/index.html`、`web/styles.css`、`web/app.js`（原生 HTML/CSS/JS）
- 宿主：`main.py`（pywebview，Windows 强制使用 Edge Chromium/WebView2）
- JS Bridge：`webview_api.py`
- 业务：原有 `backend.py`、`store.py`、`modules/email`、`modules/welink`
- 打包：PyInstaller onefile（`pywebview.spec`）

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

产物位于 `pyqt_client/dist/问题定位助手.exe`。目标电脑需要安装 Microsoft Edge
WebView2 Runtime；Windows 10/11 的正常更新版本通常已包含它。

服务端仍由 `python -m server` 启动，HTTP API 与原 PyQt 客户端保持兼容，无需随 UI
技术迁移而修改。
