"""CSV 导出、整窗截图与 CSI 曲线截图工具。

中文注释：本模块满足三项硬性需求：
1. CSV 导出（``utf-8-sig`` 让 Excel 直接打开中文表头）。
2. 整窗 / 任意控件截图（Qt ``grab()``，不依赖系统截图权限）。
3. CSI 曲线单独截图（pyqtgraph ``PlotWidget`` 也是 QWidget，可直接 grab）。
"""

from __future__ import annotations

import csv
import time
from pathlib import Path
from typing import Any

from PyQt6.QtWidgets import QWidget

try:
    from ..config import CSV_FIELDS, EXPORT_DIR
except ImportError:
    if __package__ and __package__.startswith("upper_computer"):
        raise
    from config import CSV_FIELDS, EXPORT_DIR


def export_samples_to_csv(
    samples: list[dict[str, Any]],
    export_dir: Path | None = None,
) -> Path:
    """导出历史样本为 CSV。

    中文注释：对每条样本补充人类可读时间列 ``datetime``，并按 CSV_FIELDS 顺序写出。
    缺失字段留空，保证不同来源（串口 / Demo）的样本都能落表。
    """

    target_dir = export_dir or EXPORT_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    file_path = target_dir / f"echoguard_data_{_timestamp()}.csv"

    with file_path.open("w", newline="", encoding="utf-8-sig") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for sample in samples:
            row = {field: sample.get(field, "") for field in CSV_FIELDS}
            ts = sample.get("timestamp")
            if ts and not row.get("datetime"):
                try:
                    row["datetime"] = time.strftime(
                        "%Y-%m-%d %H:%M:%S", time.localtime(float(ts))
                    )
                except (TypeError, ValueError):
                    row["datetime"] = ""
            writer.writerow(row)

    return file_path


def save_widget_screenshot(widget: QWidget, file_path: Path | None = None) -> Path:
    """保存任意 QWidget 当前画面为 PNG（用于整窗 / 控制台一键截图）。"""

    target = file_path or EXPORT_DIR / f"screenshot_{_timestamp()}.png"
    target.parent.mkdir(parents=True, exist_ok=True)

    pixmap = widget.grab()
    if not pixmap.save(str(target), "PNG"):
        raise RuntimeError(f"截图保存失败：{target}")
    return target


def save_csi_screenshot(widget: QWidget, file_path: Path | None = None) -> Path:
    """单独保存 CSI 曲线区域截图为 PNG。

    中文注释：传入 CSI 趋势卡片或其内部 PlotWidget 均可。文件名带 ``csi_`` 前缀，
    便于和整窗截图区分。
    """

    target = file_path or EXPORT_DIR / f"csi_curve_{_timestamp()}.png"
    target.parent.mkdir(parents=True, exist_ok=True)

    pixmap = widget.grab()
    if not pixmap.save(str(target), "PNG"):
        raise RuntimeError(f"CSI 曲线截图保存失败：{target}")
    return target


def _timestamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S")
