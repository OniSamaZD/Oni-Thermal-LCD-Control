from thermalright_lcd.device_discovery import DiscoveredDisplay, DisplayLifecycle

def wait_scan(window,app,timeout=2):
    import time
    deadline=time.monotonic()+timeout
    while getattr(window,"_display_scan_thread",None) is not None and time.monotonic()<deadline:app.processEvents();time.sleep(.005)
    app.processEvents();assert getattr(window,"_display_scan_thread",None) is None


def test_main_window_dynamic_zero_one_two_three_and_hotplug_cleanup():
    import os,tempfile
    from unittest.mock import patch
    os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
    from PySide6.QtWidgets import QApplication
    from thermalright_lcd.gui import MainWindow
    class Sender:
        enabled=False
        def __init__(self):self.closed=0
        def close(self):self.closed+=1
    app=QApplication.instance() or QApplication([]);current=[];senders=[]
    def sender(_device):value=Sender();senders.append(value);return value
    with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{"LOCALAPPDATA":folder}),patch("thermalright_lcd.gui.build_gui_sender",side_effect=sender):
        window=MainWindow(discovery_provider=lambda:tuple(current));assert window.cards==[];assert window.display_splitter.isHidden();assert not window.display_empty_state.isHidden()
        current[:]=[observation("wide","0416:5408")];assert window.scan_for_displays();wait_scan(window,app);assert len(window.cards)==1;assert window.display_splitter.count()==1;assert not window.layout_buttons["side_by_side"].isEnabled()
        current.append(observation("small","0416:5302"));window.scan_for_displays();wait_scan(window,app);assert len(window.cards)==2;assert window.layout_buttons["side_by_side"].isEnabled()
        current.append(observation("third","0416:5408"));window.scan_for_displays();wait_scan(window,app);assert len(window.cards)==3;assert len({id(card.session) for card in window.cards})==3
        third=window.card_by_physical_id["third"];third_session=third.session;window.scan_for_displays();wait_scan(window,app);assert window.card_by_physical_id["third"].session is third_session
        current[:]=[observation("small","0416:5302")];window.scan_for_displays();wait_scan(window,app);assert len(window.cards)==1;assert senders[0].closed>=1 and senders[2].closed>=1
        current.insert(0,observation("wide","0416:5408"));window.scan_for_displays();wait_scan(window,app);assert len(window.cards)==2;assert len({id(card.session) for card in window.cards})==2
        window.shutdown()


def observation(key, device="0416:5408", status="connected"):
    return DiscoveredDisplay(key, device, status)


def test_zero_one_two_three_hotplug_reconnect_and_order_are_stable():
    created=[];destroyed=[]
    lifecycle=DisplayLifecycle(lambda item:created.append(item.stable_id) or {"id":item.stable_id},lambda runtime:destroyed.append(runtime["id"]))
    assert lifecycle.reconcile([])==((),())
    assert lifecycle.reconcile([observation("a")])==(("a",),())
    assert lifecycle.reconcile([observation("b","0416:5302"),observation("a")])==(("b",),())
    assert lifecycle.reconcile([observation("c"),observation("b","0416:5302"),observation("a")])==(("c",),())
    assert lifecycle.reconcile([observation("c"),observation("a")])==((),("b",))
    assert lifecycle.reconcile([observation("b","0416:5302"),observation("a"),observation("c")])==(("b",),())
    assert created==["a","b","c","b"];assert destroyed==["b"]
    assert set(lifecycle.runtimes)=={"a","b","c"}


def test_blocked_and_duplicate_observations_never_create_duplicate_runtime():
    created=[];destroyed=[];lifecycle=DisplayLifecycle(lambda item:created.append(item.stable_id) or item,lambda item:destroyed.append(item.stable_id))
    lifecycle.reconcile([observation("blocked","0416:5408","blocked"),observation("a"),observation("a")])
    lifecycle.reconcile([observation("a")]);assert created==["a"];assert destroyed==[]
    lifecycle.clear();assert destroyed==["a"]
