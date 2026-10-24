import importlib.util
from pathlib import Path
import threading
import unittest
from unittest.mock import Mock

spec = importlib.util.spec_from_file_location('example_skill', Path(__file__).resolve().parents[1] / 'plugin.py')
plugin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plugin)


class ExampleTests(unittest.TestCase):
    def test_injected_apis_and_listener(self):
        close, stt, tts, interface, view = Mock(), Mock(), Mock(), Mock(), Mock()
        plugin.execute(close, stt, tts, interface, view, threading.Event())
        listener = stt.call_args.args[0]
        listener('imagem')
        self.assertTrue(view.call_args.args[0].is_file())
        listener('piscar')
        interface.assert_called_with('blink')
        listener('fechar')
        close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
