from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes
from typing import Callable

from PIL import Image


logger = logging.getLogger(__name__)

WM_DESTROY = 0x0002
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_APP_SHOW = 0x8001
WM_APP_ABOUT = 0x8002
WM_APP_EXIT = 0x8003
WS_POPUP = 0x80000000
WS_EX_LAYERED = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008
SW_HIDE = 0
SW_SHOWNOACTIVATE = 4
TPM_RIGHTBUTTON = 0x0002
TPM_RETURNCMD = 0x0100
ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0
AC_SRC_ALPHA = 1
BI_RGB = 0
DIB_RGB_COLORS = 0
IDC_ARROW = 32512
MF_STRING = 0x0000
MF_SEPARATOR = 0x0800


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class SIZE(ctypes.Structure):
    _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", wintypes.BYTE), ("BlendFlags", wintypes.BYTE),
        ("SourceConstantAlpha", wintypes.BYTE), ("AlphaFormat", wintypes.BYTE),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class RGBQUAD(ctypes.Structure):
    _fields_ = [
        ("rgbBlue", wintypes.BYTE), ("rgbGreen", wintypes.BYTE),
        ("rgbRed", wintypes.BYTE), ("rgbReserved", wintypes.BYTE),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", RGBQUAD * 1)]


LRESULT = ctypes.c_ssize_t
LPARAM = ctypes.c_ssize_t
WPARAM = ctypes.c_size_t
HANDLE = ctypes.c_void_p
WNDPROC = ctypes.WINFUNCTYPE(
    LRESULT, wintypes.HWND, wintypes.UINT, WPARAM, LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR),
    ]


class FloatingWindow:
    def __init__(self, image: Image.Image, actions: dict[str, Callable[[], None]]):
        self.user32 = ctypes.windll.user32
        self.gdi32 = ctypes.windll.gdi32
        self.kernel32 = ctypes.windll.kernel32
        self.actions = actions
        self.size = 60
        self.hwnd: int | None = None
        self._drag_start: tuple[int, int] | None = None
        self._window_start: tuple[int, int] | None = None
        self._dragged = False
        self._bitmap = None
        self._memory_dc = None
        self._old_bitmap = None
        self._wndproc = WNDPROC(self._window_proc)
        self._configure_api()
        self._create_window(image)

    def _configure_api(self) -> None:
        self.kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        self.kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
        self.user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
        self.user32.RegisterClassW.restype = wintypes.ATOM
        self.user32.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p]
        self.user32.DefWindowProcW.restype = LRESULT
        self.user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, WPARAM, LPARAM]
        self.user32.CreateWindowExW.restype = wintypes.HWND
        self.user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
        self.user32.LoadCursorW.restype = wintypes.HANDLE
        self.user32.GetDC.argtypes = [wintypes.HWND]
        self.user32.GetDC.restype = wintypes.HDC
        self.user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        self.user32.UpdateLayeredWindow.argtypes = [
            wintypes.HWND, wintypes.HDC, ctypes.POINTER(POINT), ctypes.POINTER(SIZE),
            wintypes.HDC, ctypes.POINTER(POINT), wintypes.COLORREF,
            ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD]
        self.user32.UpdateLayeredWindow.restype = wintypes.BOOL
        self.user32.CreatePopupMenu.restype = wintypes.HMENU
        self.user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, WPARAM, wintypes.LPCWSTR]
        self.user32.TrackPopupMenu.restype = wintypes.UINT
        self.user32.TrackPopupMenu.argtypes = [
            wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, wintypes.HWND, ctypes.c_void_p]
        self.user32.DestroyMenu.argtypes = [wintypes.HMENU]
        self.gdi32.CreateCompatibleDC.restype = wintypes.HDC
        self.gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
        self.gdi32.CreateDIBSection.restype = wintypes.HBITMAP
        self.gdi32.CreateDIBSection.argtypes = [
            wintypes.HDC, ctypes.POINTER(BITMAPINFO), wintypes.UINT,
            ctypes.POINTER(ctypes.c_void_p), HANDLE, wintypes.DWORD]
        self.gdi32.SelectObject.argtypes = [wintypes.HDC, HANDLE]
        self.gdi32.SelectObject.restype = HANDLE
        self.gdi32.DeleteObject.argtypes = [HANDLE]
        self.gdi32.DeleteDC.argtypes = [wintypes.HDC]

    def _create_window(self, source: Image.Image) -> None:
        instance = self.kernel32.GetModuleHandleW(None)
        class_name = "CoreInsightFloatingIcon"
        wc = WNDCLASSW()
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = instance
        wc.hCursor = self.user32.LoadCursorW(None, ctypes.c_void_p(IDC_ARROW))
        wc.lpszClassName = class_name
        self.user32.RegisterClassW(ctypes.byref(wc))
        screen_width = self.user32.GetSystemMetrics(0)
        screen_height = self.user32.GetSystemMetrics(1)
        self.hwnd = self.user32.CreateWindowExW(
            WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_TOPMOST, class_name,
            "CoreInsight Local Toolkit", WS_POPUP,
            max(0, screen_width - self.size - 24),
            max(0, (screen_height - self.size) // 2),
            self.size, self.size, None, None, instance, None)
        if not self.hwnd:
            raise ctypes.WinError()
        self._render(source)
        self.show()

    def _render(self, source: Image.Image) -> None:
        icon = source.convert("RGBA").resize((52, 52), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (self.size, self.size), (0, 0, 0, 0))
        canvas.alpha_composite(icon, (4, 4))
        pixels = bytearray(canvas.tobytes("raw", "BGRA"))
        for offset in range(0, len(pixels), 4):
            alpha = pixels[offset + 3]
            pixels[offset] = pixels[offset] * alpha // 255
            pixels[offset + 1] = pixels[offset + 1] * alpha // 255
            pixels[offset + 2] = pixels[offset + 2] * alpha // 255

        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = self.size
        bmi.bmiHeader.biHeight = -self.size
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = BI_RGB
        screen_dc = self.user32.GetDC(None)
        self._memory_dc = self.gdi32.CreateCompatibleDC(screen_dc)
        bits = ctypes.c_void_p()
        self._bitmap = self.gdi32.CreateDIBSection(
            screen_dc, ctypes.byref(bmi), DIB_RGB_COLORS,
            ctypes.byref(bits), None, 0)
        if not self._bitmap or not bits.value:
            self.user32.ReleaseDC(None, screen_dc)
            raise ctypes.WinError()
        ctypes.memmove(bits, bytes(pixels), len(pixels))
        self._old_bitmap = self.gdi32.SelectObject(self._memory_dc, self._bitmap)
        rect = wintypes.RECT()
        self.user32.GetWindowRect(self.hwnd, ctypes.byref(rect))
        destination = POINT(rect.left, rect.top)
        size = SIZE(self.size, self.size)
        source_point = POINT(0, 0)
        blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
        if not self.user32.UpdateLayeredWindow(
                self.hwnd, screen_dc, ctypes.byref(destination), ctypes.byref(size),
                self._memory_dc, ctypes.byref(source_point), 0,
                ctypes.byref(blend), ULW_ALPHA):
            self.user32.ReleaseDC(None, screen_dc)
            raise ctypes.WinError()
        self.user32.ReleaseDC(None, screen_dc)

    def _window_proc(self, hwnd, message, wparam, lparam):
        if message == WM_LBUTTONDOWN:
            cursor = POINT()
            rect = wintypes.RECT()
            self.user32.GetCursorPos(ctypes.byref(cursor))
            self.user32.GetWindowRect(hwnd, ctypes.byref(rect))
            self._drag_start = (cursor.x, cursor.y)
            self._window_start = (rect.left, rect.top)
            self._dragged = False
            self.user32.SetCapture(hwnd)
            return 0
        if message == WM_MOUSEMOVE and self._drag_start and self._window_start:
            cursor = POINT()
            self.user32.GetCursorPos(ctypes.byref(cursor))
            dx = cursor.x - self._drag_start[0]
            dy = cursor.y - self._drag_start[1]
            if abs(dx) + abs(dy) > 4:
                self._dragged = True
            self.user32.SetWindowPos(
                hwnd, -1, self._window_start[0] + dx, self._window_start[1] + dy,
                0, 0, 0x0001 | 0x0010)
            return 0
        if message == WM_LBUTTONUP:
            self.user32.ReleaseCapture()
            self._drag_start = None
            self._window_start = None
            if not self._dragged:
                self.actions["portal"]()
            return 0
        if message == WM_RBUTTONUP:
            self._show_menu()
            return 0
        if message == WM_APP_SHOW:
            self.show()
            return 0
        if message == WM_APP_ABOUT:
            self.actions["about"]()
            return 0
        if message == WM_APP_EXIT:
            self.user32.DestroyWindow(hwnd)
            return 0
        if message == WM_DESTROY:
            self.user32.PostQuitMessage(0)
            return 0
        return self.user32.DefWindowProcW(hwnd, message, wparam, lparam)

    def _show_menu(self) -> None:
        menu = self.user32.CreatePopupMenu()
        entries = [
            (101, "云见主页", "portal"), (102, "邮件提取", "email"),
            (103, "聊天记录提取", "chat"), (0, "", ""),
            (104, "打开日志目录", "logs"), (105, "检查更新", "update"),
            (106, "关于", "about"), (0, "", ""),
            (107, "隐藏悬浮图标", "hide"), (108, "退出", "exit"),
        ]
        action_by_id: dict[int, str] = {}
        for item_id, label, action in entries:
            if item_id:
                self.user32.AppendMenuW(menu, MF_STRING, item_id, label)
                action_by_id[item_id] = action
            else:
                self.user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        cursor = POINT()
        self.user32.GetCursorPos(ctypes.byref(cursor))
        self.user32.SetForegroundWindow(self.hwnd)
        selected = self.user32.TrackPopupMenu(
            menu, TPM_RIGHTBUTTON | TPM_RETURNCMD,
            cursor.x, cursor.y, 0, self.hwnd, None)
        self.user32.DestroyMenu(menu)
        self.user32.PostMessageW(self.hwnd, 0, 0, 0)
        action = action_by_id.get(selected)
        logger.info("floating menu action=%s command=%s", action or "dismiss", selected)
        if action == "hide":
            self.hide()
        elif action == "exit":
            self.user32.DestroyWindow(self.hwnd)
        elif action:
            self.actions[action]()

    def show(self) -> None:
        self.user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
        self.user32.SetWindowPos(self.hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
        logger.info("floating icon shown")

    def hide(self) -> None:
        self.user32.ShowWindow(self.hwnd, SW_HIDE)
        logger.info("floating icon hidden")

    def post(self, message: int) -> None:
        self.user32.PostMessageW(self.hwnd, message, 0, 0)

    def run(self) -> None:
        message = wintypes.MSG()
        while self.user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            self.user32.TranslateMessage(ctypes.byref(message))
            self.user32.DispatchMessageW(ctypes.byref(message))

    def close(self) -> None:
        if self.hwnd:
            self.post(WM_APP_EXIT)

    def dispose(self) -> None:
        if self._memory_dc and self._old_bitmap:
            self.gdi32.SelectObject(self._memory_dc, self._old_bitmap)
        if self._bitmap:
            self.gdi32.DeleteObject(self._bitmap)
        if self._memory_dc:
            self.gdi32.DeleteDC(self._memory_dc)
