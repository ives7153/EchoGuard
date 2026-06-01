"""EchoGuard 上位机全局配置。

中文注释：本文件集中放置品牌文案、主题色、刷新节奏、节点常量、阈值默认值、
导出目录以及全局 QSS。界面层 / 数据层 / 工具层不再各自硬编码魔法数字，
后续接入真实硬件或调整演示参数时也更安全。

参考界面（两张设计稿）：
* 仪表盘页：WiFi CSI 振幅趋势 + 生命体征指标卡 + 环境/无线分组 + 右侧事件流 + 拓扑。
* 传感器页：活动节点矩阵表格 + 右侧系统核心配置（阈值滑条 / 开关 / 同步按钮）。
"""

from __future__ import annotations

from pathlib import Path


# ---------------------------------------------------------------------------
# 品牌与基础常量
# ---------------------------------------------------------------------------
BRAND_NAME = "EchoGuard"
BRAND_VERSION = "v2.4"
APP_TITLE = "EchoGuard v2.4 · WiFi-CSI + LoRa 感知救援控制台"
WINDOW_TITLE = "EchoGuard v2.4"
CONTROL_ID = "0xFF-AD-01"

BAUDRATE = 115200

# 中文注释：常见竞赛配置为 1..4，但上位机实际以 Gateway 串口帧中的 id 自动发现节点。
NODE_IDS = (1, 2, 3, 4)
GATEWAY_ID = "GW_01"

UI_REFRESH_MS = 60
AUTO_PORT_REFRESH_MS = 3000
OFFLINE_SECONDS = 8.0
MAX_HISTORY_ROWS = 6000
MAX_EVENT_ROWS = 240

EXPORT_DIR = Path(__file__).resolve().parent / "exports"


# ---------------------------------------------------------------------------
# 主题色：贴近设计稿的近黑工业风，蓝色为主强调色
# ---------------------------------------------------------------------------
THEME = {
    "bg": "#0E0F12",
    "bg_deep": "#08090B",
    "topbar": "#0B0C0F",
    "panel": "#121317",
    "rail": "#101115",
    "card": "#191A1F",
    "card_alt": "#1F2128",
    "card_hover": "#23252D",
    "row_hover": "#1C1E24",
    "border": "#2A2C33",
    "border_soft": "#22242A",
    "divider": "#26282F",
    "text": "#F4F5F7",
    "text_soft": "#D7DBE3",
    "muted": "#9097A3",
    "muted_2": "#6C7280",
    "muted_3": "#565B66",
    "blue": "#2F80FF",
    "blue_bright": "#4C97FF",
    "blue_soft": "#A8C7FF",
    "green": "#34C759",
    "green_soft": "#5BE07E",
    "yellow": "#FFD166",
    "orange": "#FF9F0A",
    "red": "#FF453A",
    "red_soft": "#FF8A80",
    "cyan": "#64D2FF",
    "tag_bg": "#23252C",
    "tag_border": "#34373F",
}


# ---------------------------------------------------------------------------
# 左侧导航：five 页面（含占位 / 功能页）
# 中文注释：key 用于 QStackedWidget 路由，icon 为简单字形避免外部资源依赖。
# ---------------------------------------------------------------------------
NAV_ITEMS = (
    {"key": "dashboard", "text": "仪表盘", "icon": "▥"},
    {"key": "sensors", "text": "节点管理", "icon": "◎"},
    {"key": "analysis", "text": "数据分析", "icon": "⌁"},
    {"key": "diagnostics", "text": "技术诊断", "icon": "＋"},
    {"key": "history", "text": "历史记录", "icon": "↺"},
)


# ---------------------------------------------------------------------------
# 仪表盘页：4 个生命体征感知节点
# ---------------------------------------------------------------------------
NODE_LABELS = {
    1: "node1",
    2: "node2",
    3: "node3",
    4: "node4",
}

# 中文注释：拓扑图使用归一化坐标，绘制时按控件尺寸映射到圆形轨道。
TOPOLOGY_NODE_POSITIONS = {
    1: (-0.62, -0.42),
    2: (0.66, 0.40),
    3: (0.52, -0.50),
    4: (-0.40, 0.60),
}


# ---------------------------------------------------------------------------
# 传感器页：活动节点矩阵（LoRa 节点）
# 中文注释：节点矩阵由真实 Gateway 串口帧自动发现，本常量保留为空元组仅作历史兼容。
# ---------------------------------------------------------------------------
OPERATING_MODES = ("POWER_SAVE", "HIGH_PERF", "SLEEP", "DEBUG_MODE", "NORMAL")

NODE_MATRIX: tuple[dict[str, object], ...] = ()

# 运行健康度等级（设计稿：极佳 / 良好 / 未激活 / 严重错误）
HEALTH_EXCELLENT = "极佳"
HEALTH_GOOD = "良好"
HEALTH_INACTIVE = "未激活"
HEALTH_CRITICAL = "严重错误"

HEALTH_COLORS = {
    HEALTH_EXCELLENT: THEME["blue_soft"],
    HEALTH_GOOD: THEME["blue_soft"],
    HEALTH_INACTIVE: THEME["muted_2"],
    HEALTH_CRITICAL: THEME["red"],
}


# ---------------------------------------------------------------------------
# 阈值默认值（传感器页右侧配置 + 报警规则共享）
# ---------------------------------------------------------------------------
PRESENCE_THRESHOLD = 0.42       # 存在感应阈值（0~1，对应设计稿 42%）
GAS_THRESHOLD_RAW = 280.0       # MQ-135 原始值 / 有害气体指数阈值，未做 ppm 标定
GAS_ALARM_RAW = 550.0           # 触发系统警告的气体原始值上限
GAS_THRESHOLD_PPM = GAS_THRESHOLD_RAW  # 兼容旧导入名；UI 不再按 ppm 展示
GAS_ALARM_PPM = GAS_ALARM_RAW          # 兼容旧导入名；规则仍比较原始值
CONFIDENCE_THRESHOLD = 0.75     # 生命微动报警的置信度门限
ALARM_DEDUP_SECONDS = 5.0       # 同类报警去重窗口

DEFAULT_AFH_ENABLED = True      # 自动频率跳变
DEFAULT_MESH_ENABLED = False    # 多级网格中继


# ---------------------------------------------------------------------------
# CSV 导出字段
# ---------------------------------------------------------------------------
CSV_FIELDS = [
    "timestamp",
    "datetime",
    "node_id",
    "node_code",
    "seq",
    "presence_score",
    "motion_score",
    "breath_bpm",
    "confidence",
    "gas",
    "temperature",
    "humidity",
    "rssi",
    "wifi_rssi",
    "snr",
    "packet_loss",
    "battery",
    "mode",
    "source",
    "raw",
]


def build_qss() -> str:
    """返回全局 QSS。

    中文注释：卡片、按钮、导航、状态胶囊、滑条、开关轨道和滚动条都在这里统一
    定义。阴影由 QGraphicsDropShadowEffect 负责，QSS 只管边框、圆角和配色。
    """

    t = THEME
    return f"""
    * {{
        font-family: "Microsoft YaHei", "Segoe UI", "PingFang SC", Arial, sans-serif;
        font-size: 14px;
        color: {t["text"]};
        selection-background-color: {t["blue"]};
        selection-color: #FFFFFF;
    }}

    QMainWindow, QWidget#Root {{
        background: {t["bg"]};
    }}

    /* ---------------- 顶部栏 ---------------- */
    QFrame#TopBar {{
        background: {t["topbar"]};
        border-bottom: 1px solid {t["border_soft"]};
    }}

    QLabel#AppTitle {{
        font-size: 16px;
        font-weight: 700;
        color: {t["text"]};
    }}

    QLabel#TopSubtitle {{
        font-size: 14px;
        color: {t["muted"]};
        font-weight: 600;
    }}

    QLabel#TopIcon {{
        font-size: 17px;
        color: {t["muted"]};
        padding: 4px;
    }}

    /* ---------------- 左侧导航 ---------------- */
    QFrame#LeftNav {{
        background: {t["bg_deep"]};
        border-right: 1px solid {t["border_soft"]};
    }}

    QLabel#NavCaption {{
        font-size: 13px;
        font-weight: 700;
        color: {t["muted"]};
        letter-spacing: 1px;
    }}

    QLabel#NavSession {{
        font-size: 12px;
        color: {t["muted_2"]};
    }}

    QFrame#NavItem {{
        background: transparent;
        border-radius: 10px;
        border: 1px solid transparent;
    }}

    QFrame#NavItem:hover {{
        background: {t["card"]};
    }}

    QFrame#NavItem[selected="true"] {{
        background: #102A4D;
        border: 1px solid #1C406F;
        border-left: 3px solid {t["blue_bright"]};
    }}

    QLabel#NavIcon {{
        font-size: 15px;
        color: {t["text_soft"]};
    }}

    QLabel#NavIcon[selected="true"] {{
        color: {t["blue_bright"]};
    }}

    QLabel#NavText {{
        font-size: 15px;
        font-weight: 600;
        color: {t["text_soft"]};
    }}

    QLabel#NavText[selected="true"] {{
        color: #FFFFFF;
        font-weight: 700;
    }}

    /* ---------------- 右侧栏 ---------------- */
    QFrame#RightRail {{
        background: {t["rail"]};
        border-left: 1px solid {t["border_soft"]};
    }}

    /* ---------------- 卡片 ---------------- */
    QFrame[card="true"] {{
        background: {t["card"]};
        border: 1px solid {t["border"]};
        border-radius: 12px;
    }}

    QFrame[cardAlt="true"] {{
        background: {t["card_alt"]};
        border: 1px solid {t["border"]};
        border-radius: 10px;
    }}

    QFrame[plain="true"] {{
        background: transparent;
        border: 0;
    }}

    /* ---------------- 文案 ---------------- */
    QLabel#SectionTitle {{
        font-size: 16px;
        font-weight: 700;
        color: {t["text"]};
    }}

    QLabel#SectionSub {{
        font-size: 13px;
        color: {t["muted"]};
    }}

    QLabel#SubtleText {{
        color: {t["muted"]};
        font-size: 12px;
    }}

    QLabel#MetricTitle {{
        color: {t["muted"]};
        font-size: 12px;
        font-weight: 600;
    }}

    QLabel#MetricValue {{
        color: {t["text"]};
        font-size: 24px;
        font-weight: 700;
    }}

    QLabel#MetricHint {{
        color: {t["blue_soft"]};
        font-size: 12px;
        font-weight: 600;
    }}

    QLabel#ColHeader {{
        color: {t["muted"]};
        font-size: 12px;
        font-weight: 700;
    }}

    QLabel#NodeCode {{
        font-size: 14px;
        font-weight: 700;
        color: {t["text"]};
    }}

    /* ---------------- 按钮 ---------------- */
    QPushButton {{
        background: {t["card_alt"]};
        border: 1px solid {t["border"]};
        border-radius: 9px;
        padding: 8px 14px;
        font-weight: 600;
        color: {t["text_soft"]};
    }}

    QPushButton:hover {{
        background: {t["card_hover"]};
        border-color: #3C3F48;
    }}

    QPushButton:pressed {{
        background: #16171C;
    }}

    QPushButton#PrimaryButton {{
        background: {t["blue"]};
        border: 1px solid {t["blue"]};
        color: #FFFFFF;
    }}

    QPushButton#PrimaryButton:hover {{
        background: {t["blue_bright"]};
        border-color: {t["blue_bright"]};
    }}

    QPushButton#GhostButton {{
        background: transparent;
        border: 1px solid {t["border"]};
        color: {t["text_soft"]};
    }}

    QPushButton#GhostButton:hover {{
        background: {t["card"]};
    }}

    QPushButton#DangerButton {{
        background: #36181A;
        border: 1px solid #5A2A2C;
        color: {t["red_soft"]};
    }}

    QPushButton#SyncButton {{
        background: {t["card_alt"]};
        border: 1px solid {t["border"]};
        border-radius: 10px;
        padding: 14px 14px;
        font-size: 14px;
        font-weight: 700;
        color: {t["text"]};
    }}

    QPushButton#SyncButton:hover {{
        background: {t["card_hover"]};
    }}

    QPushButton#RowMenu {{
        background: transparent;
        border: 0;
        color: {t["muted"]};
        font-size: 18px;
        padding: 2px 8px;
    }}

    QPushButton#RowMenu:hover {{
        color: {t["text"]};
    }}

    QPushButton#IconClose {{
        background: transparent;
        border: 0;
        color: {t["muted"]};
        font-size: 18px;
    }}

    QPushButton#IconClose:hover {{
        color: {t["text"]};
    }}

    /* ---------------- 下拉框 ---------------- */
    QComboBox {{
        background: {t["card_alt"]};
        border: 1px solid {t["border"]};
        border-radius: 8px;
        padding: 6px 10px;
        min-width: 120px;
        color: {t["text_soft"]};
    }}

    QComboBox:hover {{
        border-color: #3C3F48;
    }}

    QComboBox::drop-down {{
        border: 0;
        width: 18px;
    }}

    QComboBox QAbstractItemView {{
        background: {t["card_alt"]};
        border: 1px solid {t["border"]};
        outline: 0;
        selection-background-color: {t["blue"]};
        color: {t["text_soft"]};
    }}

    QMenu {{
        background: {t["card_alt"]};
        border: 1px solid {t["border"]};
        border-radius: 8px;
        padding: 6px;
    }}

    QMenu::item {{
        color: {t["text_soft"]};
        padding: 8px 24px 8px 12px;
        border-radius: 6px;
    }}

    QMenu::item:selected {{
        background: {t["blue"]};
        color: #FFFFFF;
    }}

    QMenu::item:disabled {{
        color: {t["muted_2"]};
    }}

    QLineEdit {{
        background: {t["card_alt"]};
        border: 1px solid {t["border"]};
        border-radius: 8px;
        padding: 7px 10px;
        color: {t["text_soft"]};
    }}

    QLineEdit:hover {{
        border-color: #3C3F48;
    }}

    QLineEdit:focus {{
        border-color: {t["blue"]};
    }}

    QCheckBox {{
        color: {t["text_soft"]};
        spacing: 8px;
        font-weight: 600;
    }}

    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border-radius: 4px;
        border: 1px solid {t["border"]};
        background: {t["card_alt"]};
    }}

    QCheckBox::indicator:checked {{
        background: {t["blue"]};
        border-color: {t["blue"]};
    }}

    /* ---------------- 进度/电量条 ---------------- */
    QProgressBar {{
        background: #2B2D34;
        border: 0;
        border-radius: 4px;
        height: 7px;
        text-align: right;
    }}

    QProgressBar::chunk {{
        background: {t["blue_soft"]};
        border-radius: 4px;
    }}

    /* ---------------- 滑条 ---------------- */
    QSlider::groove:horizontal {{
        height: 5px;
        background: #2B2D34;
        border-radius: 3px;
    }}

    QSlider::sub-page:horizontal {{
        background: {t["blue"]};
        border-radius: 3px;
    }}

    QSlider::handle:horizontal {{
        width: 16px;
        height: 16px;
        margin: -6px 0;
        border-radius: 8px;
        background: #FFFFFF;
        border: 2px solid {t["blue"]};
    }}

    QSlider::handle:horizontal:hover {{
        background: {t["blue_soft"]};
    }}

    /* ---------------- 滚动条 ---------------- */
    QScrollArea {{
        background: transparent;
        border: 0;
    }}

    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 2px;
    }}

    QScrollBar::handle:vertical {{
        background: #3A3D45;
        border-radius: 5px;
        min-height: 30px;
    }}

    QScrollBar::handle:vertical:hover {{
        background: #4A4D56;
    }}

    QScrollBar::add-line:vertical,
    QScrollBar::sub-line:vertical {{
        height: 0px;
    }}

    QScrollBar:horizontal {{
        background: transparent;
        height: 10px;
        margin: 2px;
    }}

    QScrollBar::handle:horizontal {{
        background: #3A3D45;
        border-radius: 5px;
        min-width: 30px;
    }}

    QScrollBar::add-line:horizontal,
    QScrollBar::sub-line:horizontal {{
        width: 0px;
    }}

    /* ---------------- 表格（QTableWidget，用于历史记录页） ---------------- */
    QTableWidget {{
        background: {t["card"]};
        border: 1px solid {t["border"]};
        border-radius: 10px;
        gridline-color: {t["border_soft"]};
    }}

    QHeaderView::section {{
        background: {t["card_alt"]};
        color: {t["muted"]};
        border: 0;
        border-bottom: 1px solid {t["border"]};
        padding: 8px;
        font-weight: 700;
    }}

    QTableWidget::item {{
        padding: 6px;
        border-bottom: 1px solid {t["border_soft"]};
    }}
    """
