"""Tiny Qt-free thread/signal compatibility layer for legacy business workers."""
from __future__ import annotations

import threading


class _BoundSignal:
    def __init__(self):
        self._callbacks = []
        self._lock = threading.Lock()

    def connect(self, callback):
        with self._lock:
            self._callbacks.append(callback)

    def emit(self, *args):
        with self._lock:
            callbacks = list(self._callbacks)
        for callback in callbacks:
            try:
                callback(*args)
            except Exception:
                pass


class Signal:
    def __init__(self, *_types):
        self._name = ""

    def __set_name__(self, _owner, name):
        self._name = f"__signal_{name}"

    def __get__(self, instance, _owner):
        if instance is None:
            return self
        signal = instance.__dict__.get(self._name)
        if signal is None:
            signal = instance.__dict__[self._name] = _BoundSignal()
        return signal


class WorkerThread:
    """Subset of QThread used by the WeLink workers."""

    def __init__(self, *_args, **_kwargs):
        self._thread = None

    def start(self):
        if self.isRunning():
            return
        self._thread = threading.Thread(target=self.run, daemon=True)
        self._thread.start()

    def run(self):
        raise NotImplementedError

    def isRunning(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def wait(self, milliseconds: int | None = None):
        if self._thread:
            self._thread.join(None if milliseconds is None else milliseconds / 1000)


QThread = WorkerThread
pyqtSignal = Signal
