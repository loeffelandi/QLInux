"""Undo/Redo fuer Etikett-Designs (Medienwerte + Objekte).

Ein Befehl ist ein Schnappschuss - kein erneutes Abspielen von Gesten.
Zuruecksetzen laeuft unter ``_adjusting`` in der App, damit die
Randverschiebung nicht ein zweites Mal zuschlaegt.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable, Mapping, Sequence

from PySide6.QtGui import QUndoCommand, QUndoStack


def design_snapshot(
    media: Mapping[str, Any],
    items: list[Mapping[str, Any]],
    selection: list[Mapping[str, Any]] | None = None,
    serial: Mapping[str, Any] | None = None,
    guides: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Unveraenderlicher Schnappschuss von Band/Design, Objekten und Hilfslinien.

    ``serial`` gehoert dazu, sobald die App es uebergibt: Anzahl und Start
    aendern sonst kein Objekt und waeren nicht rueckgaengig zu machen.
    ``guides`` ist immer eine Liste, auch leer, damit ein geloeschter Satz
    Linien beim Rueckgaengigmachen wiederkommt.
    """
    snapshot: dict[str, Any] = {
        "media": deepcopy(dict(media)),
        "items": deepcopy(list(items)),
        "selection": deepcopy(list(selection or [])),
        "guides": deepcopy(list(guides or [])),
    }
    if serial is not None:
        snapshot["serial"] = deepcopy(dict(serial))
    return snapshot


def snapshots_equal(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    """Vergleich ohne Auswahl - die Auswahl ist nur fuer die Wiederherstellung."""
    return (
        a.get("media") == b.get("media")
        and a.get("items") == b.get("items")
        and a.get("serial") == b.get("serial")
        and a.get("guides") == b.get("guides")
    )


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
            before["media"],
            before["items"],
            before.get("selection"),
            serial=before.get("serial"),
            guides=before.get("guides"),
        )
        self._after = design_snapshot(
            after["media"],
            after["items"],
            after.get("selection"),
            serial=after.get("serial"),
            guides=after.get("guides"),
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
    """Befehl ablegen, wenn sich Medien, Objekte oder Hilfslinien geaendert haben."""
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
