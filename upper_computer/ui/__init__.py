"""EchoGuard 上位机 UI 层。"""

try:
    from .main_window import MainWindow
except ImportError:  # 兼容 cd upper_computer 后直接 python main.py
    if __package__ and __package__.startswith("upper_computer"):
        raise
    from main_window import MainWindow  # type: ignore

__all__ = ["MainWindow"]
