"""Gateway 文本协议解析模块。"""

from __future__ import annotations

from typing import Any


def parse_gateway_frame(line: str) -> dict[str, Any]:
    """解析 Gateway 一行一帧的文本数据。

    中文注释：协议示例为
    NODE,1,CSI,0,RSSI,-55,TEMP,25.3,HUM,60.1
    """

    raw = line.strip()
    result: dict[str, Any] = {
        "type": "",
        "node_id": None,
        "fields": {},
        "raw": raw,
        "valid": False,
    }

    if not raw:
        return result

    parts = [part.strip() for part in raw.split(",")]
    if len(parts) < 2:
        result["type"] = parts[0]
        return result

    result["type"] = parts[0]
    result["node_id"] = _to_number(parts[1])

    fields: dict[str, Any] = {}
    valid_pairs = True
    payload = parts[2:]
    if len(payload) % 2 != 0:
        valid_pairs = False

    for index in range(0, len(payload) - 1, 2):
        key = payload[index]
        value = payload[index + 1]
        if key:
            fields[key] = _to_number(value)

    result["fields"] = fields
    result["valid"] = bool(result["type"] and result["node_id"] is not None and valid_pairs)
    return result


def _to_number(value: str) -> int | float | str:
    """中文注释：尽量把协议字段转为数字，便于后续绘图与规则判断。"""

    try:
        return int(value)
    except ValueError:
        pass

    try:
        return float(value)
    except ValueError:
        return value
