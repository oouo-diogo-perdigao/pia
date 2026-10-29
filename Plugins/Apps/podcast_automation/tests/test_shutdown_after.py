"""Power actions are mocked in every test; never shut down the test machine."""
import io
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from Plugins.Apps.podcast_automation import web_api,power

class ShutdownAfterTests(unittest.TestCase):
    def setUp(self):
        for target,value in (('_latest',None),('_tasks',{})):
            patcher=patch.object(web_api,target,value);patcher.start();self.addCleanup(patcher.stop)
        patcher=patch.object(power,'shutdown');self.shutdown=patcher.start();self.addCleanup(patcher.stop)
        patcher=patch.object(power,'cancel');self.cancel=patcher.start();self.addCleanup(patcher.stop)
        self.context=SimpleNamespace(backend=Mock(),jobs={})

    def run_task(self,code=0,options=None,lines='',cancelled=False):
        self.context.jobs.clear()
        process=Mock(stdout=io.StringIO(lines))
        def finish():
            if cancelled:next(iter(self.context.jobs.values())).cancelled.set()
            return code
        process.wait.side_effect=finish
        self.context.backend.start_podcast_task.return_value=process
        result=web_api.handle('start',{'task':'process','shutdown_after':True,**(options or {})},self.context)
        job=self.context.jobs[result['job']]
        with job.changed:self.assertTrue(job.changed.wait_for(lambda:job.status!='running',timeout=3))
        return job

    def test_success_schedules_once_and_can_be_cancelled(self):
        job=self.run_task()
        self.shutdown.assert_called_once_with()
        self.assertEqual(job.status,'done')
        self.context.backend.start_podcast_task.assert_called_once_with('podcast_automation.main','--once')
        self.assertTrue(web_api.handle('status',{},self.context)['shutdown_pending'])
        with self.assertRaisesRegex(ValueError,'Cancele'):
            web_api.handle('start',{'task':'process'},self.context)
        web_api.handle('cancel-shutdown',{},self.context)
        self.cancel.assert_called_once()
        self.assertFalse(web_api.handle('status',{},self.context)['shutdown_pending'])

    def test_failed_cancelled_or_structurally_failed_batch_never_shuts_down(self):
        for options in ({'code':1},{'cancelled':True},{'lines':'@@CRAIG {"kind":"failed","error":"fixture"}\n'}):
            with self.subTest(options=options):
                self.run_task(**options)
                self.shutdown.assert_not_called()

    def test_monitor_mode_and_other_utilities_cannot_arm_shutdown(self):
        for options in ({'monitor':True,'shutdown_after':True},{'task':'rebuild','shutdown_after':True},{'shutdown_after':'true'}):
            with self.subTest(options=options),self.assertRaises(ValueError):
                web_api.handle('start',{'task':'process',**options},self.context)
        self.context.backend.start_podcast_task.assert_not_called()
        self.shutdown.assert_not_called()

    def test_monitor_without_shutdown_preserves_existing_behavior(self):
        self.run_task(options={'monitor':True,'shutdown_after':False})
        self.context.backend.start_podcast_task.assert_called_once_with('podcast_automation.main')
        self.shutdown.assert_not_called()

    def test_power_permission_failure_does_not_report_shutdown_as_scheduled(self):
        self.shutdown.side_effect=PermissionError('fixture')
        job=self.run_task()
        self.assertEqual(job.status,'error')
        self.assertIn('não permitiu',job.error)
        self.assertFalse(web_api.handle('status',{},self.context)['shutdown_pending'])

class PowerCommandTests(unittest.TestCase):
    def test_windows_and_linux_commands_are_delayed_and_not_forced(self):
        for platform,expected in (('win32',['shutdown','/s','/t','60']),('linux',['shutdown','-h','+1'])):
            with self.subTest(platform=platform),patch.object(power.sys,'platform',platform),patch.object(power.subprocess,'CREATE_NO_WINDOW',0x08000000,create=True),patch.object(power.subprocess,'run') as run:
                power.shutdown()
                self.assertEqual(run.call_args.args[0],expected)
                self.assertTrue(run.call_args.kwargs['check'])
                self.assertNotIn('/f',run.call_args.args[0])
