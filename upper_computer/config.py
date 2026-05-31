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

# 中文注释：固件 id 字段范围 1..4，对应 4 个生命体征感知节点（仪表盘页使用）。
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
    {"key": "dashboard", "text": "仪表盘", "icon": "▦"},
    {"key": "sensors", "text": "传感器", "icon": "((·))"},
    {"key": "analysis", "text": "数据分析", "icon": "▣"},
    {"key": "diagnostics", "text": "技术诊断", "icon": "✚"},
    {"key": "history", "text": "历史记录", "icon": "↺"},
)


# ---------------------------------------------------------------------------
# 仪表盘页：4 个生命体征感知节点
# ---------------------------------------------------------------------------
NODE_LABELS = {
    1: "SENS_01",
    2: "SENS_02",
    3: "SENS_03",
    4: "SENS_04",
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
# 中文注释：matrix_id 是固件没有覆盖到的扩展节点，用于把表格填满成设计稿中的
# “14 个连接的 LoRa 节点”观感；前 4 个绑定真实固件 id（1..4），其余由 Demo 注入。
# 每个节点的 RSSI / 电池 / 健康度 / 运行模式都来自数据管线 NodeState，而不是写死的常量。
# ---------------------------------------------------------------------------
OPERATING_MODES = ("POWER_SAVE", "HIGH_PERF", "SLEEP", "DEBUG_MODE", "NORMAL")

NODE_MATRIX = (
    {"matrix_id": 1, "code": "NODE-AX-772", "mode": "POWER_SAVE", "bound_node": 1, "battery": 82},
    {"matrix_id": 2, "code": "NODE-BX-104", "mode": "HIGH_PERF", "bound_node": 2, "battery": 31},
    {"matrix_id": 3, "code": "NODE-AX-991", "mode": "SLEEP", "bound_node": 3, "battery": 100},
    {"matrix_id": 4, "code": "NODE-CZ-012", "mode": "DEBUG_MODE", "bound_node": None, "battery": 56},
    {"matrix_id": 5, "code": "NODE-AX-102", "mode": "POWER_SAVE", "bound_node": 4, "battery": 75},
    {"matrix_id": 6, "code": "NODE-BX-233", "mode": "HIGH_PERF", "bound_node": None, "battery": 64},
    {"matrix_id": 7, "code": "NODE-DX-318", "mode": "NORMAL", "bound_node": None, "battery": 88},
    {"matrix_id": 8, "code": "NODE-AX-540", "mode": "POWER_SAVE", "bound_node": None, "battery": 47},
    {"matrix_id": 9, "code": "NODE-CZ-077", "mode": "NORMAL", "bound_node": None, "battery": 72},
    {"matrix_id": 10, "code": "NODE-BX-861", "mode": "NORMAL", "bound_node": None, "battery": 90},
    {"matrix_id": 11, "code": "NODE-AX-405", "mode": "SLEEP", "bound_node": None, "battery": 100},
    {"matrix_id": 12, "code": "NODE-DX-690", "mode": "HIGH_PERF", "bound_node": None, "battery": 53},
    {"matrix_id": 13, "code": "NODE-AX-219", "mode": "POWER_SAVE", "bound_node": None, "battery": 79},
    {"matrix_id": 14, "code": "NODE-BX-948", "mode": "NORMAL", "bound_node": None, "battery": 68},
)

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
GAS_THRESHOLD_PPM = 280.0       # 气体检测阈值（ppm，设计稿 280 ppm）
GAS_ALARM_PPM = 550.0           # 触发系统警告的气体上限
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
