"""EchoGuard · WiFi-CSI + LoRa 感知救援系统 PyQt6 上位机入口。

中文注释：启动 QApplication、加载全局 QSS，并把 MainWindow 的用户操作信号连接到
DataManager 的业务槽函数，再把 DataManager 的数据信号连回界面刷新。所有串口数据
最终都以快照形式驱动界面，主线程不做阻塞 I/O。

运行方式：
    python -m upper_computer.main            # 包内运行（推荐）
    cd upper_computer && python main.py      # 目录内直接运行
"""

from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication

try:
    from .config import APP_TITLE, WINDOW_TITLE, build_qss
    from .core import DataManager
    from .ui import MainWindow
except ImportError:  # 兼容 cd upper_computer 后直接 python main.py
    from config import APP_TITLE, WINDOW_TITLE, build_qss
    from core import DataManager
    from ui import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    app.setApplicationDisplayName(APP_TITLE)
    app.setStyleSheet(build_qss())

    manager = DataManager()
    window = MainWindow()
    window.setWindowTitle(WINDOW_TITLE)

    # ---------------- UI -> DataManager ----------------
    window.refresh_ports_requested.connect(manager.refresh_ports)
    window.connect_requested.connect(manager.connect_to_port)
    window.disconnect_requested.connect(manager.disconnect_serial)
    window.export_csv_requested.connect(manager.export_csv)
    window.export_filtered_csv_requested.connect(manager.export_filtered_csv)
    window.screenshot_requested.connect(manager.save_screenshot)
    window.csi_shot_requested.connect(manager.save_csi_image)
    window.analysis_shot_requested.connect(manager.save_analysis_image)
    window.active_node_changed.connect(manager.set_active_node)
    window.pause_toggled.connect(manager.set_paused)
    window.clear_events_requested.connect(manager.clear_events)
    window.clear_history_requested.connect(manager.clear_history)
    window.presence_threshold_changed.connect(manager.set_presence_threshold)
    window.gas_threshold_changed.connect(manager.set_gas_threshold)
    window.afh_toggled.connect(manager.set_afh_enabled)
    window.mesh_toggled.connect(manager.set_mesh_enabled)
    window.sync_requested.connect(manager.sync_global_config)
    window.matrix_filter_changed.connect(manager.set_matrix_filter)
    window.add_node_requested.connect(manager.add_local_matrix_node)
    window.matrix_remove_requested.connect(manager.remove_local_matrix_node)
    window.matrix_maintenance_requested.connect(manager.toggle_matrix_maintenance)
    window.diagnostics_requested.connect(manager.generate_diagnostics_report)

    # ---------------- DataManager -> UI ----------------
    manager.ports_changed.connect(window.update_ports)
    manager.status_changed.connect(window.set_status)
    manager.latest_frame_changed.connect(window.set_latest_frame)
    manager.export_message_changed.connect(window.show_export_message)
    manager.snapshot_changed.connect(window.update_snapshot)

    app.aboutToQuit.connect(manager.shutdown)

    window.show()
    manager.start()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
