# 智能助手

本地 Outlook 邮件扫描 + 云端同步工具，基于 PyQt5 + FastAPI。

## 目录结构

```
pyqt_client/   # 桌面客户端（Windows exe）
server/        # 后端服务（FastAPI + MySQL）
```

---

## 后端部署

### 1. 配置

```bash
cp server/utils/settings.example.py server/utils/settings.py
# 编辑 settings.py，填写数据库、LLM 等配置
```

### 2. 启动

```bash
# 安装依赖
pip install -r server/requirements.txt

# 启动（默认端口 8023）
python -m server
```

或直接双击 `server/start.bat`。

---

## 客户端打包（Windows）

**前置要求：**
- Python 3.10+
- 已安装并登录 Microsoft Outlook（需要 win32com）

```bash
cd pyqt_client

# 打包（自动安装依赖）
python build.py
# 或双击 build.bat
```

产物输出至 `pyqt_client/dist/智能助手.exe`，双击即可运行，无需 Python 环境。

---

## 客户端使用

1. 打开 `智能助手.exe`
2. 点击"设置" → 基本 tab，填写后端地址和命名空间
3. 在"规则" tab 配置邮件匹配规则
4. 点击"刷新邮件"读取本地 Outlook
5. 点击"立即同步"将匹配邮件推送到后端
