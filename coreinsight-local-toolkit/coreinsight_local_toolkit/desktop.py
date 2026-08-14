from __future__ import annotations

import logging
import json
import os
import queue
import socket
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

import uvicorn

from . import __version__
from .app import create_app
from .config import Settings
from .updates import check_for_update


logger = logging.getLogger(__name__)


def asset_path(name: str) -> Path:
    return Path(__file__).with_name("assets") / name


def _native_notice(message: str, title: str = "CoreInsight Local Toolkit") -> None:
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, title, 0x40)
    except Exception:
        logger.warning("desktop notice: %s", message)


def _port_is_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def _activate_existing(port: int) -> bool:
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/health", timeout=1) as response:
            health = json.loads(response.read().decode("utf-8"))
        if health.get("service") != "coreinsight-local-toolkit":
            return False
    except (OSError, ValueError, urllib.error.URLError):
        return False

    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/desktop/show", data=b"{}", method="POST",
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=1) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def run_desktop(settings: Settings) -> None:
    import pystray
    import tkinter as tk
    from PIL import Image, ImageTk
    from tkinter import messagebox

    if _port_is_open(settings.port):
        if _activate_existing(settings.port):
            logger.info("existing toolkit instance activated port=%d", settings.port)
        else:
            _native_notice(
                f"本地端口 {settings.port} 已被其他程序占用，CoreInsight Local Toolkit 无法启动。\n\n"
                "请关闭占用该端口的程序，或通过 COREINSIGHT_AGENT_PORT 指定其他端口。")
            logger.error("local port is already occupied port=%d", settings.port)
        return

    ui_actions: queue.SimpleQueue[str] = queue.SimpleQueue()
    application = create_app(settings)

    @application.post("/desktop/show", include_in_schema=False)
    def activate_desktop() -> dict[str, bool]:
        ui_actions.put("show")
        return {"ok": True}

    server = uvicorn.Server(uvicorn.Config(
        application, host=settings.host, port=settings.port,
        log_level="info", log_config=None))
    server_thread = threading.Thread(
        target=server.run, name="coreinsight-http", daemon=True)
    server_thread.start()
    deadline = time.monotonic() + 10
    while not server.started and server_thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.05)
    if not server.started:
        server.should_exit = True
        server_thread.join(timeout=3)
        _native_notice(f"本地服务启动失败，请查看日志：{settings.data_dir / 'logs'}")
        return

    local_url = f"http://127.0.0.1:{settings.port}/demo/"
    email_url = settings.email_url or settings.portal_url
    chat_url = settings.chat_url or local_url
    root = tk.Tk(className="CoreInsightLocalToolkit")
    root.title("CoreInsight Local Toolkit")
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    transparent = "#010203"
    root.configure(bg=transparent)
    try:
        root.wm_attributes("-transparentcolor", transparent)
    except tk.TclError:
        pass

    source_image = Image.open(asset_path("icon.png")).convert("RGBA")
    floating_image = ImageTk.PhotoImage(source_image.resize((52, 52), Image.Resampling.LANCZOS))
    label = tk.Label(root, image=floating_image, bg=transparent, bd=0,
                     highlightthickness=0, cursor="hand2")
    label.pack(padx=4, pady=4)
    root.update_idletasks()
    width, height = 60, 60
    x = max(0, root.winfo_screenwidth() - width - 24)
    y = max(0, (root.winfo_screenheight() - height) // 2)
    root.geometry(f"{width}x{height}+{x}+{y}")

    state = {"press_x": 0, "press_y": 0, "root_x": 0, "root_y": 0, "dragged": False}

    def open_url(url: str) -> None:
        webbrowser.open(url)

    def show_floating(*_args) -> None:
        root.deiconify()
        root.lift()
        root.attributes("-topmost", True)

    def hide_floating(*_args) -> None:
        try:
            menu.unpost()
            menu.grab_release()
        except tk.TclError:
            pass
        root.after_idle(root.withdraw)

    def show_about(*_args) -> None:
        messagebox.showinfo(
            "关于 CoreInsight Local Toolkit",
            f"CoreInsight Local Toolkit\n版本：{__version__}\n"
            f"本地服务：http://127.0.0.1:{settings.port}",
            parent=root,
        )

    def open_logs(*_args) -> None:
        log_dir = settings.data_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        os.startfile(str(log_dir))

    exiting = threading.Event()

    def exit_on_ui_thread() -> None:
        if exiting.is_set():
            return
        exiting.set()
        server.should_exit = True
        root.quit()

    def request_exit(*_args) -> None:
        root.after(0, exit_on_ui_thread)

    def check_update(*_args) -> None:
        def worker() -> None:
            try:
                status = check_for_update(settings)
                if not status.configured:
                    message = "尚未配置更新信息"
                elif status.forceUpdate:
                    message = f"当前版本已停用，请更新到 {status.latestVersion}"
                elif status.updateAvailable:
                    message = f"发现新版本 {status.latestVersion}"
                else:
                    message = f"当前已是最新版本 {status.currentVersion}"
                tray.notify(message, "CoreInsight Local Toolkit")
            except Exception as exc:
                logger.exception("update check failed")
                tray.notify(f"版本检查失败：{exc}", "CoreInsight Local Toolkit")
        threading.Thread(target=worker, name="update-check", daemon=True).start()

    menu = tk.Menu(root, tearoff=False)
    menu.add_command(label="云见主页", command=lambda: open_url(settings.portal_url))
    menu.add_command(label="邮件提取", command=lambda: open_url(email_url))
    menu.add_command(label="聊天记录提取", command=lambda: open_url(chat_url))
    menu.add_separator()
    menu.add_command(label="打开日志目录", command=open_logs)
    menu.add_command(label="检查更新", command=check_update)
    menu.add_command(label="关于", command=show_about)
    menu.add_separator()
    menu.add_command(label="隐藏悬浮图标", command=hide_floating)
    menu.add_command(label="退出", command=request_exit)

    def popup_menu(event) -> None:
        menu.tk_popup(event.x_root, event.y_root)

    def press(event) -> None:
        state.update(press_x=event.x_root, press_y=event.y_root,
                     root_x=root.winfo_x(), root_y=root.winfo_y(), dragged=False)

    def drag(event) -> None:
        dx, dy = event.x_root - state["press_x"], event.y_root - state["press_y"]
        if abs(dx) + abs(dy) > 4:
            state["dragged"] = True
        root.geometry(f"+{state['root_x'] + dx}+{state['root_y'] + dy}")

    def release(_event) -> None:
        if not state["dragged"]:
            open_url(settings.portal_url)

    label.bind("<ButtonPress-1>", press)
    label.bind("<B1-Motion>", drag)
    label.bind("<ButtonRelease-1>", release)
    label.bind("<Button-3>", popup_menu)
    root.bind("<Button-3>", popup_menu)

    def process_ui_actions() -> None:
        try:
            while ui_actions.get_nowait() == "show":
                show_floating()
        except queue.Empty:
            pass
        if not exiting.is_set():
            root.after(100, process_ui_actions)

    root.after(100, process_ui_actions)

    tray = pystray.Icon(
        "coreinsight-local-toolkit", source_image,
        "CoreInsight Local Toolkit",
        menu=pystray.Menu(
            pystray.MenuItem("云见主页", lambda *_: open_url(settings.portal_url)),
            pystray.MenuItem("邮件提取", lambda *_: open_url(email_url)),
            pystray.MenuItem("聊天记录提取", lambda *_: open_url(chat_url)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("打开日志目录", open_logs),
            pystray.MenuItem("检查更新", check_update),
            pystray.MenuItem("关于", lambda *_: root.after(0, show_about)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("显示悬浮图标", lambda *_: root.after(0, show_floating), default=True),
            pystray.MenuItem("退出", request_exit),
        ),
    )
    tray_thread = threading.Thread(target=tray.run, name="coreinsight-tray", daemon=True)
    tray_thread.start()
    threading.Timer(2.0, check_update).start()
    logger.info("desktop floating icon and tray started")
    try:
        root.mainloop()
    finally:
        server.should_exit = True
        tray.stop()
        server_thread.join(timeout=10)
        root.destroy()
        logger.info("desktop host stopped")
