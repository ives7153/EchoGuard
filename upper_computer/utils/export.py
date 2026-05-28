"""CSV 导出与截图工具。"""

from __future__ import annotations

import csv
import time
from pathlib import Path
from typing import Any

import dearpygui.dearpygui as dpg


DEFAULT_EXPORT_DIR = Path(__file__).resolve().parents[1] / "exports"


def export_samples_to_csv(
    samples: list[dict[str, Any]],
    export_dir: Path | None = None,
) -> Path:
    """把当前缓存样本导出为 CSV 文件。"""

    target_dir = export_dir or DEFAULT_EXPORT_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    file_path = target_dir / f"rescue_data_{_timestamp()}.csv"

    fieldnames = [
        "timestamp",
        "node_id",
        "seq",
        "presence_score",
        "motion_score",
        "breath_bpm",
        "confidence",
        "gas",
        "temperature",
        "humidity",
        "rssi",
        "source",
        "raw",
    ]

    with file_path.open("w", newline="", encoding="utf-8-sig") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        for sample in samples:
            writer.writerow({name: sample.get(name, "") for name in fieldnames})

    return file_path


def take_screenshot(file_path: Path | None = None) -> Path:
    """保存 Dear PyGui 当前帧为 PNG 截图。"""

    target = file_path or DEFAULT_EXPORT_DIR / f"screenshot_{_timestamp()}.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    dpg.output_frame_buffer(str(target))
    return target


def _timestamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S")
