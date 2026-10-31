"""Offline native lifecycle/capture checks; no real screen, sound or shutdown."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
os.environ['QTWEBENGINE_CHROMIUM_FLAGS']='--no-sandbox --disable-gpu'
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from types import SimpleNamespace
from unittest.mock import Mock,patch
import tempfile
import base64
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QImage,QCloseEvent
from PyQt6.QtCore import QTimer,QRect
from PyQt6.QtTest import QTest
from src.desktop_ui import WebShell,DesktopUI
from Plugins.Apps.screenshots.native import NativeApp,png_data

print("Initializing native fixtures",flush=True)
app=QApplication(['pia-platform-smoke']);app.setQuitOnLastWindowClosed(False)
print("Creating shell",flush=True)
window=WebShell('about:blank','http://localhost:8762');window.show()
event=QCloseEvent();window.closeEvent(event)
assert not event.isAccepted() and not window.isVisible()
app.setProperty('pia_exiting',True)
event=QCloseEvent();window.closeEvent(event);assert event.isAccepted()
app.setProperty('pia_exiting',False);window.show()
print("Testing app exit",flush=True)
quits=[];app.aboutToQuit.connect(lambda:quits.append(True))
QTimer.singleShot(0,lambda:DesktopUI.request_exit(SimpleNamespace()))
assert app.exec()==0 and len(quits)==1 and app.property('pia_exiting')
print('Single exit with main window visible, normal close hides: OK')

with tempfile.TemporaryDirectory() as directory:
    root=Path(directory)
    ui=SimpleNamespace(url='http://localhost:8762',overlay=Mock(),controls=Mock(),composer=Mock(),main_action=Mock(),window=Mock())
    ui.main_action.isChecked.return_value=False
    image=QImage(32,32,QImage.Format.Format_ARGB32);image.fill(0xff7766cc)
    raw=base64.b64decode(png_data(image).split(',',1)[1])
    shell=Mock()
    shell.view.page.return_value.runJavaScript.side_effect=lambda code,callback=None:callback(True) if callback else None
    with patch('src.config_paths.BASE_DIR',root),patch('Plugins.Apps.screenshots.native.config',return_value={'prefill_url':False,'prefill_title':False}),patch('Plugins.Apps.screenshots.native.foreground',return_value=('', '', None)),patch('Plugins.Apps.screenshots.native.QGuiApplication.screens',return_value=[SimpleNamespace(geometry=lambda:QRect(0,0,32,32))]),patch('Plugins.Apps.screenshots.native.urlopen') as fetch,patch('Plugins.Apps.screenshots.native.CaptureShell.create',return_value=shell) as create:
        fetch.return_value.__enter__.return_value.read.return_value=raw
        native=NativeApp(ui,None)
        for _ in range(2):
            result=native.capture('selection')
            for _ in range(400):
                QTest.qWait(5)
                if result.done():break
            identity=result.result(timeout=1)['id']
            assert QImage(str(native.records[identity]['path'])).pixel(0,0)==image.pixel(0,0)
            assert native.handle('image',{'id':identity})['data'].startswith('data:image/png;base64,')
        assert create.call_count==2
        assert shell.present.call_count==2
        ui.overlay.hide.assert_not_called();ui.controls.menu.hide.assert_not_called();ui.composer.hide.assert_not_called()
        fetch.side_effect=RuntimeError('fixture failure')
        failed=native.capture('selection')
        for _ in range(400):
            QTest.qWait(5)
            if failed.done():break
        assert isinstance(failed.exception(timeout=1),RuntimeError)
        native.shutdown()
    fake=SimpleNamespace(request_exit=Mock())
    with patch('src.config_paths.CONFIG_DIR',root),patch('subprocess.Popen') as spawn,patch('src.desktop_ui.QTimer.singleShot') as timer:
        assert DesktopUI.command(fake,'restart',{})['ok']
        assert '--restart-pid' in spawn.call_args.args[0]
        assert timer.call_args.args[1]==fake.request_exit
print('Capture editor recreated and presented, visibility unchanged, restart scheduled: OK')
