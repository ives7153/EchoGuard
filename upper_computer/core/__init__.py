"""EchoGuard 上位机核心层。"""

try:
    from .alarm_rules import AlarmEngine
    from .data_manager import DataManager, EventRecord, MatrixNodeState, NodeState
except ImportError:  # 兼容 cd upper_computer 后直接 python main.py
    if __package__ and __package__.startswith("upper_computer"):
        raise
    from alarm_rules import AlarmEngine  # type: ignore
    from data_manager import DataManager, EventRecord, MatrixNodeState, NodeState  # type: ignore

__all__ = [
    "AlarmEngine",
    "DataManager",
    "EventRecord",
    "MatrixNodeState",
    "NodeState",
]
