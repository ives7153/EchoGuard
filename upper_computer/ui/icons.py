"""Lightweight SVG icon helpers for the PyQt UI.

The project remains a PyQt application. These helpers bring a LobeHub-like
linear icon language into Qt without adding React/WebView/npm dependencies.
"""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QByteArray, QSize, Qt
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QLabel, QPushButton, QWidget

try:
    from ..config import THEME
except ImportError:
    if __package__ and __package__.startswith("upper_computer"):
        raise
    from config import THEME


ICON_PATHS: dict[str, str] = {
    "layout-dashboard": (
        '<rect x="3" y="3" width="7" height="9" rx="1.5"/>'
        '<rect x="14" y="3" width="7" height="5" rx="1.5"/>'
        '<rect x="14" y="12" width="7" height="9" rx="1.5"/>'
        '<rect x="3" y="16" width="7" height="5" rx="1.5"/>'
    ),
    "radio": (
        '<circle cx="12" cy="12" r="2.4"/>'
        '<path d="M7.2 7.2a6.8 6.8 0 0 0 0 9.6"/>'
        '<path d="M16.8 7.2a6.8 6.8 0 0 1 0 9.6"/>'
        '<path d="M4.2 4.2a11 11 0 0 0 0 15.6"/>'
        '<path d="M19.8 4.2a11 11 0 0 1 0 15.6"/>'
    ),
    "chart-line": '<path d="M3 19h18"/><path d="M5 15l4-4 4 3 6-8"/>',
    "brain-circuit": (
        '<path d="M9 3a3 3 0 0 0-3 3 3 3 0 0 0-2 5.5A3.5 3.5 0 0 0 7.5 17H9"/>'
        '<path d="M15 3a3 3 0 0 1 3 3 3 3 0 0 1 2 5.5A3.5 3.5 0 0 1 16.5 17H15"/>'
        '<path d="M9 3v18"/><path d="M15 3v18"/><path d="M9 8h6"/><path d="M9 13h6"/>'
        '<circle cx="6" cy="20" r="1.4"/><circle cx="18" cy="20" r="1.4"/>'
        '<path d="M9 18l-2 2"/><path d="M15 18l2 2"/>'
    ),
    "wrench": (
        '<path d="M14.7 5.3a5 5 0 0 0 5 6.6l-8.6 8.6a2.2 2.2 0 0 1-3.1-3.1l8.6-8.6a5 5 0 0 0-6.6-5z"/>'
    ),
    "history": '<path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 4v5h5"/><path d="M12 7v5l3 2"/>',
    "sun": (
        '<circle cx="12" cy="12" r="4"/>'
        '<path d="M12 2v2"/><path d="M12 20v2"/><path d="M4.93 4.93l1.41 1.41"/>'
        '<path d="M17.66 17.66l1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/>'
        '<path d="M4.93 19.07l1.41-1.41"/><path d="M17.66 6.34l1.41-1.41"/>'
    ),
    "moon": '<path d="M20.5 14.5A8.5 8.5 0 0 1 9.5 3.5 7 7 0 1 0 20.5 14.5z"/>',
}


def icon_pixmap(name: str, color: str, size: int = 18) -> QPixmap:
    """Render an SVG icon to a pixmap."""

    path = ICON_PATHS.get(name) or ICON_PATHS["layout-dashboard"]
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" '
        f'stroke-linecap="round" stroke-linejoin="round">{path}</svg>'
    )
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return pixmap


def icon(name: str, color: str, size: int = 18) -> QIcon:
    return QIcon(icon_pixmap(name, color, size))


class SvgIcon(QLabel):
    """Theme-aware SVG icon label."""

    def __init__(
        self,
        name: str,
        size: int = 18,
        color: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._icon_name = name
        self._icon_size = size
        self._icon_color = color
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedSize(size, size)
        self.refresh_theme()

    def set_icon_name(self, name: str) -> None:
        self._icon_name = name
        self.refresh_theme()

    def set_icon_color(self, color: str | None) -> None:
        self._icon_color = color
        self.refresh_theme()

    def refresh_theme(self) -> None:
        color = self._icon_color or THEME["text_soft"]
        self.setPixmap(icon_pixmap(self._icon_name, color, self._icon_size))


class IconButton(QPushButton):
    """QPushButton with a refreshable SVG icon."""

    def __init__(
        self,
        icon_name: str,
        text: str = "",
        icon_size: int = 18,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text, parent)
        apply_button_icon(self, icon_name, icon_size=icon_size)

    def set_icon_name(self, icon_name: str) -> None:
        apply_button_icon(self, icon_name, icon_size=int(getattr(self, "_eg_icon_size", 18)))

    def refresh_theme(self) -> None:
        refresh_button_icon(self)


def apply_button_icon(button: QPushButton, icon_name: str, icon_size: int = 16) -> None:
    button._eg_icon_name = icon_name  # type: ignore[attr-defined]
    button._eg_icon_size = icon_size  # type: ignore[attr-defined]
    refresh_button_icon(button)


def refresh_button_icon(button: QPushButton) -> None:
    icon_name = getattr(button, "_eg_icon_name", None)
    if not icon_name:
        return
    icon_size = int(getattr(button, "_eg_icon_size", 16))
    button.setIcon(icon(str(icon_name), _button_icon_color(button), icon_size))
    button.setIconSize(QSize(icon_size, icon_size))


def refresh_widget_icons(widget: QWidget) -> None:
    if isinstance(widget, SvgIcon):
        widget.refresh_theme()
    if isinstance(widget, QPushButton):
        refresh_button_icon(widget)
    for child in widget.findChildren(SvgIcon):
        child.refresh_theme()
    for button in widget.findChildren(QPushButton):
        refresh_button_icon(button)


def _button_icon_color(button: QPushButton) -> str:
    if not button.isEnabled():
        return THEME["muted_2"]
    object_name = button.objectName()
    if object_name == "PrimaryButton":
        return THEME["selection_text"]
    if object_name == "DangerButton":
        return THEME["red_soft"]
    return THEME["text_soft"]


def icon_names() -> tuple[str, ...]:
    return tuple(sorted(ICON_PATHS))
