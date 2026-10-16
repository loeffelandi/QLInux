"""Kleine Widget-Helfer.

* :func:`install_wheel_guard` verhindert, dass ein Steuerelement (Spinbox,
  Combobox, ...) seinen Wert aendert, waehrend man nur mit dem Mausrad
  darueber faehrt. Geaendert wird nur, wenn das Feld den Fokus hat - das ist
  das uebliche, wenig ueberraschende Verhalten in Desktop-Apps.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt


class _WheelGuard(QObject):
    """Event-Filter: schluckt Rad-Ereignisse ohne Fokus."""

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.Wheel and not obj.hasFocus():
            return True  # nicht an das Widget weiterreichen -> Wert bleibt
        return super().eventFilter(obj, event)


_guard: _WheelGuard | None = None


def _get_guard() -> _WheelGuard:
    # Lazy, damit kein QObject vor der QApplication entsteht.
    global _guard
    if _guard is None:
        _guard = _WheelGuard()
    return _guard


def install_wheel_guard(widget):
    """Rad-Ereignisse nur bei Fokus zulassen (z. B. fuer Spinboxen)."""
    widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    widget.installEventFilter(_get_guard())
    return widget


def install_wheel_guard_recursive(root) -> None:
    """Wendet den Guard auf alle Spinboxen/Comboboxen unter ``root`` an."""
    from PySide6.QtWidgets import QAbstractSpinBox, QComboBox

    targets = list(root.findChildren(QAbstractSpinBox)) + list(root.findChildren(QComboBox))
    for widget in targets:
        install_wheel_guard(widget)


__all__ = ["install_wheel_guard", "install_wheel_guard_recursive"]
