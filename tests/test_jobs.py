from datetime import datetime

from PySide6.QtWidgets import QTableWidget
from ql_editor.jobs import PrintHistoryDialog, PrintJob


def _job(outcome: str) -> PrintJob:
    return PrintJob(
        datetime(2026, 10, 18, 14, 2, 5),
        "50 mm",
        2,
        "QL-820NWB",
        "tcp://192.168.1.5:9100",
        outcome,
    )


def test_status_text_is_honest_about_network_sends():
    assert _job("sent").status_text() == "An Drucker gesendet"
    assert _job("printed").status_text() == "Gedruckt"
    assert _job("error").status_text() != _job("sent").status_text()
    assert _job("failed").status_text() == "Nicht gesendet"


def test_history_dialog_lists_newest_first(qapp):
    dialog = PrintHistoryDialog([_job("printed"), _job("sent")])
    table = dialog.findChildren(QTableWidget)[0]
    assert table.rowCount() == 2
    assert table.item(0, 4).text() == _job("sent").status_text()
