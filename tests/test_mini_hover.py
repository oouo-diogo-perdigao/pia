"""Deterministic native hover geometry and timers, without moving the real pointer."""
from types import SimpleNamespace
from unittest.mock import Mock,patch
import unittest
from PyQt6.QtCore import QPoint,QRect
from src.piamini.controls import MiniControls,RadialMenu

class MiniHoverTests(unittest.TestCase):
    def test_transparent_corners_do_not_open_menu(self):
        controls=SimpleNamespace(overlay=Mock())
        controls.overlay.frameGeometry.return_value=QRect(0,0,150,150)
        self.assertTrue(MiniControls._over_mini(controls,QPoint(75,75)))
        self.assertFalse(MiniControls._over_mini(controls,QPoint(0,0)))

    def test_windows_waits_three_seconds_before_retracting(self):
        controls=SimpleNamespace(overlay=Mock(),menu=Mock(),ui=SimpleNamespace(composer=Mock()),blink=Mock(),dragging=False,_last_menu_hover=10)
        controls.overlay.isVisible.return_value=True
        controls.ui.composer.isVisible.return_value=False
        controls._over_mini=Mock(return_value=False)
        controls.blink.update.return_value=False
        controls.menu.hits.return_value=False
        controls.menu.isVisible.return_value=True
        with patch('src.piamini.controls.sys.platform','win32'),patch('src.piamini.controls.QCursor.pos',return_value=QPoint(500,500)),patch('src.piamini.controls.time.monotonic',return_value=12.9):
            MiniControls.tick(controls)
            controls.menu.collapse.assert_not_called()
        with patch('src.piamini.controls.sys.platform','win32'),patch('src.piamini.controls.QCursor.pos',return_value=QPoint(500,500)),patch('src.piamini.controls.time.monotonic',return_value=13):
            MiniControls.tick(controls)
            controls.menu.collapse.assert_called_once()

    def test_suppression_blocks_reappearance_and_phantom_enter(self):
        controls=SimpleNamespace(overlay=Mock(),menu=Mock(),ui=SimpleNamespace(composer=Mock()),_suppress_until=13)
        controls.ui.composer.isVisible.return_value=False
        controls.overlay.isVisible.return_value=True
        controls.menu.isVisible.return_value=False
        controls.menu.hits.return_value=False
        controls._over_mini=Mock(return_value=True)
        with patch('src.piamini.controls.time.monotonic',return_value=12.9):
            MiniControls._present_menu(controls)
            controls.menu.expand.assert_not_called()
        with patch('src.piamini.controls.time.monotonic',return_value=13):
            MiniControls._present_menu(controls)
            controls.menu.expand.assert_called_once()
            controls.menu.expand.reset_mock();controls._over_mini.return_value=False
            MiniControls._present_menu(controls)
            controls.menu.expand.assert_not_called()
