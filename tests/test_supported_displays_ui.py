import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from thermalright_lcd.gui import SupportedDisplaysDialog
from thermalright_lcd.devices.catalog import catalog_models


def app():
    return QApplication.instance() or QApplication([])


def test_catalog_search_and_truthful_status_categories():
    app()
    dialog = SupportedDisplaysDialog()
    all_rows = [dialog.models.item(i).text() for i in range(dialog.models.count())]
    assert any("Trofeo Vision 9.16" in row and "Verified" in row for row in all_rows)
    assert any("BeadaPanel" in row and "Experimental" in row for row in all_rows)
    assert any("Jonsbo DS339" in row and "Unsupported / Incomplete" in row for row in all_rows)
    assert all("Detection Only" not in row for row in all_rows)
    dialog.search.setText("DS916")
    assert dialog.models.count() == 1
    assert "Jonsbo DS916" in dialog.models.item(0).text()
    dialog.search.setText("0416:5408")
    assert dialog.models.count() >= 1
    assert all("Thermalright" in dialog.models.item(i).text() for i in range(dialog.models.count()))
    dialog.close()


def test_catalog_is_read_only_and_does_not_create_connected_displays():
    app()
    dialog = SupportedDisplaysDialog()
    assert not hasattr(dialog, "display_lifecycle")
    assert not hasattr(dialog, "cards")
    dialog.close()


def test_verified_identifiers_are_model_specific_and_unique():
    verified=[item for item in catalog_models() if item.status=="Verified"]
    assert [(item.model,item.identifiers) for item in verified]==[
        ("Trofeo Vision 9.16 LCD",("0416:5408",)),
        ("Trofeo Vision 6.86 LCD",("0416:5302",)),
    ]


def test_experimental_means_runtime_output_enabled_and_incomplete_stays_closed():
    rows=catalog_models();experimental=[item for item in rows if item.status=="Experimental"]
    assert experimental and all(item.output_enabled for item in experimental)
    for expected in ("BeadaPanel","JL LCD Device Family","Jonsbo DS916",'Thermaltake 6" LCD',"Phantom Gaming 360 LCD",'Universal Screen 8.8"'):
        assert any(expected in item.model and item.status=="Experimental" for item in rows)
    incomplete=[item for item in rows if item.status=="Unsupported / Incomplete"]
    assert incomplete and all(not item.output_enabled for item in incomplete)
    assert any("Jonsbo DS339" in item.model for item in incomplete)
    assert not any("Detection Only" in item.status for item in rows)
