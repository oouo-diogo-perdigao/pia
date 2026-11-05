"""Voice adapter uses the PIA interpreter and this app, never another checkout."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('podcast_voice_controller', ROOT / 'voice/controller.py')
controller = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controller)


class VoiceAppTests(unittest.TestCase):
    def test_uses_current_python_and_app_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'src/podcast_automation').mkdir(parents=True)
            (root / 'src/podcast_automation/main.py').touch()
            (root / '.env').write_text('LLM_MODEL=app-model\n', encoding='utf-8')
            job = controller.PodcastJob(root)
            process = Mock()
            # A real stdout has close(); use a small StringIO instead of a provider or process.
            import io
            process.stdout = io.StringIO('@@CRAIG {"kind":"stage","index":0}\n')
            process.wait.return_value = 0
            process.poll.return_value = 0
            with patch.dict(os.environ, {'LLM_MODEL': 'pia-model', 'VIRTUAL_ENV': 'another-env'}), patch.object(controller.subprocess, 'Popen', return_value=process) as spawn:
                job.start()
                job.thread.join(timeout=2)
            command = spawn.call_args.args[0]
            self.assertEqual(command, [sys.executable, '-u', '-m', 'podcast_automation.main', '--once'])
            self.assertEqual(spawn.call_args.kwargs['cwd'], root)
            self.assertNotIn('PODCAST_ROOT',spawn.call_args.kwargs['env'])
            self.assertEqual(spawn.call_args.kwargs['env'].get('LLM_MODEL'),'pia-model')
            self.assertNotIn('VIRTUAL_ENV', spawn.call_args.kwargs['env'])
            self.assertEqual(job.snapshot()['state'], 'completed')
            self.assertEqual(job.snapshot()['stage'], 'Obter ZIP')

    def test_manifest_registers_voice_inside_app(self):
        import tomllib
        manifest = tomllib.loads((ROOT / 'plugin.toml').read_text(encoding='utf-8'))
        self.assertIn('podcast', manifest['voice']['commands'])
        self.assertTrue((ROOT / manifest['voice']['entrypoint']).is_file())
        for name in ('Dockerfile', 'Dockerfile.gpu', 'docker-compose.yml', 'docker-compose.gpu.yml', 'iniciar.py', 'pyproject.toml'):
            self.assertFalse((ROOT / name).exists(), name)


if __name__ == '__main__':
    unittest.main()
