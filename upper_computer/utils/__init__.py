"""Legacy utility namespace.

The active PyQt upper computer uses :mod:`upper_computer.core.exporter` for
CSV export and screenshots. This package stays importable for compatibility
without pulling in the removed DearPyGui-based helpers during packaging.
"""

__all__: list[str] = []
