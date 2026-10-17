"""Undo/Redo fuer Etikett-Designs (Medienwerte + Objekte).

Ein Befehl ist ein Schnappschuss - kein erneutes Abspielen von Gesten.
Zuruecksetzen laeuft unter ``_adjusting`` in der App, damit die
Randverschiebung nicht ein zweites Mal zuschlaegt.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable, Mapping

from PySide6.QtGui import QUndoCommand, QUndoStack


def design_snapshot(
    media: Mapping[str, Any],
    items: list[Mapping[str, Any]],
    selection: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Unveraenderlicher Schnappschuss von Band/Design und Objekten."""
    return {
        "media": deepcopy(dict(media)),
        "items": deepcopy(list(items)),
        "selection": deepcopy(list(selection or [])),
    }


def snapshots_equal(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    """Vergleich ohne Auswahl - die Auswahl ist nur fuer die Wiederherstellung."""
    return a.get("media") == b.get("media") and a.get("items") == b.get("items")


class DesignCommand(QUndoCommand):
    """Wechselt zwischen zwei Design-Schnappschuessen.

    Die Aenderung ist beim Ablegen schon angewendet. ``QUndoStack.push`` ruft
    sofort ``redo()`` auf - der erste Aufruf darf die Szene deshalb nicht neu
    laden (sonst sterben Live-Objekte, z. B. ein offenes Textfeld).
    """

    def __init__(
        self,
        before: Mapping[str, Any],
        after: Mapping[str, Any],
        restore: Callable[[Mapping[str, Any]], None],
        text: str = "",
    ) -> None:
        super().__init__(text)
        self._before = design_snapshot(
            before["media"], before["items"], before.get("selection")
        )
        self._after = design_snapshot(
            after["media"], after["items"], after.get("selection")
        )
        self._restore = restore
        self._skip_first_redo = True

    def undo(self) -> None:
        self._restore(self._before)

    def redo(self) -> None:
        if self._skip_first_redo:
            self._skip_first_redo = False
            return
        self._restore(self._after)


def push_if_changed(
    stack: QUndoStack,
    before: Mapping[str, Any] | None,
    after: Mapping[str, Any],
    restore: Callable[[Mapping[str, Any]], None],
    text: str = "",
) -> bool:
    """Befehl ablegen, wenn sich Medien oder Objekte geaendert haben."""
    if before is None or snapshots_equal(before, after):
        return False
    stack.push(DesignCommand(before, after, restore, text))
    return True


__all__ = [
    "DesignCommand",
    "design_snapshot",
    "push_if_changed",
    "snapshots_equal",
]
