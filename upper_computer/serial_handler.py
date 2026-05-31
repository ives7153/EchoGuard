"""串口读取模块。

中文注释：后台线程按行读取 Gateway 串口数据，并通过回调交给上位机数据层。
本模块不依赖 PyQt，DataManager 会在 QThread 中复用它，再把回调转成 Qt 信号，
保证主线程不会被串口 I/O 阻塞。
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any


class SerialReader:
    """后台线程按行读取 Gateway 串口数据，并交给上位机数据层处理。"""

    def __init__(self) -> None:
        self._serial: Any | None = None
        self._thread: threading.Thread | None = None
        self._running = threading.Event()
        self._port = ""
        self._last_error = ""

    @property
    def is_running(self) -> bool:
        return self._running.is_set()

    @property
    def is_alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    @property
    def port(self) -> str:
        return self._port

    @property
    def last_error(self) -> str:
        return self._last_error

    def start(
        self,
        port: str,
        baudrate: int,
        on_line: Callable[[str], None],
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        """打开串口并启动后台读取线程。"""

        if self.is_running:
            return

        import serial  # 延迟导入，便于无依赖环境下仍可做语法检查。

        self._serial = serial.Serial(port=port, baudrate=baudrate, timeout=0.2)
        self._port = port
        self._last_error = ""
        self._running.set()
        self._thread = threading.Thread(
            target=self._read_loop,
            args=(on_line, on_error),
            name="gateway-serial-reader",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """停止读取线程并关闭串口。"""

        self._running.clear()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)

        if self._serial is not None:
            try:
                if self._serial.is_open:
                    self._serial.close()
            except Exception:  # noqa: BLE001 - 关闭异常不应阻断退出流程。
                pass

        self._thread = None
        self._serial = None
        self._port = ""

    def write_line(self, text: str) -> None:
        """向下位机写入一行（预留下发指令能力）。"""

        if not self._serial or not self._serial.is_open:
            raise RuntimeError("串口未连接")

        payload = f"{text.rstrip()}\n".encode("utf-8")
        self._serial.write(payload)

    def _read_loop(
        self,
        on_line: Callable[[str], None],
        on_error: Callable[[str], None] | None,
    ) -> None:
        while self._running.is_set() and self._serial is not None:
            try:
                raw = self._serial.readline()
            except Exception as exc:  # noqa: BLE001 - 拔出串口时不同平台抛不同异常。
                self._last_error = str(exc)
                if on_error:
                    on_error(self._last_error)
                self._running.clear()
                break

            if not raw:
                continue

            line = raw.decode("utf-8", errors="replace").strip()
            if line:
                on_line(line)
