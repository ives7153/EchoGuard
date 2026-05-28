"""本地规则报警。"""

from __future__ import annotations

from typing import Any

OFFLINE_SECONDS = 8.0
DEDUP_SECONDS = 5.0

_LAST_ALARM_AT: dict[tuple[int, str], float] = {}


def reset_alarm_state() -> None:
    """清空报警去重状态，主要用于测试或重新开始演示。"""

    _LAST_ALARM_AT.clear()


def evaluate_sample(
    sample: dict[str, Any] | None,
    node_states: dict[int, dict[str, Any]],
    now: float,
) -> list[dict[str, Any]]:
    """根据最新样本和节点状态返回报警事件列表。

    中文注释：这里不直接操作界面，便于后续换规则、写测试或接 AI 研判模块。
    """

    events: list[dict[str, Any]] = []

    if sample and sample.get("valid", True):
        node_id = int(sample.get("node_id") or 0)
        presence = float(sample.get("presence_score") or 0.0)
        confidence = float(sample.get("confidence") or 0.0)
        gas = float(sample.get("gas") or 0.0)

        if node_id > 0 and presence > 0.6 and confidence > 0.7:
            _append_alarm(events, now, node_id, "life_motion", "疑似生命微动")
        if node_id > 0 and gas > 550:
            _append_alarm(events, now, node_id, "gas", "气体异常")

    for node_id, state in node_states.items():
        last_received = state.get("last_received")
        if last_received is None:
            last_received = state.get("created_at", now)
        if now - float(last_received) > OFFLINE_SECONDS:
            _append_alarm(events, now, int(node_id), "offline", "节点离线")

    return events


def _append_alarm(
    events: list[dict[str, Any]],
    now: float,
    node_id: int,
    kind: str,
    message: str,
) -> None:
    key = (node_id, kind)
    last_at = _LAST_ALARM_AT.get(key, 0.0)
    if now - last_at < DEDUP_SECONDS:
        return

    _LAST_ALARM_AT[key] = now
    events.append(
        {
            "time": now,
            "node_id": node_id,
            "kind": kind,
            "level": "ALARM",
            "message": message,
        }
    )
