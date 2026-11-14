"""Offline regressions for history branches and workspace mutations."""

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock
import sqlite3
import threading
import unittest

from src.workspace_store import WorkspaceStore
from src.pia.service import WorkspaceService
from Plugins.Bot.secretaria import Secretary


class ChatTreeTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "chat.db"
        self.store = WorkspaceStore(self.path)
        self.chat = self.store.new_chat()

    def test_migrates_linear_history_without_loss(self):
        old = Path(self.temp.name) / "old.db"
        with sqlite3.connect(old) as db:
            db.executescript(
                "CREATE TABLE chats(id TEXT PRIMARY KEY,title TEXT,created REAL); CREATE TABLE messages(id INTEGER PRIMARY KEY,chat TEXT,role TEXT,text TEXT); INSERT INTO chats VALUES('a','Old',1); INSERT INTO messages VALUES(1,'a','user','Hello'); INSERT INTO messages VALUES(2,'a','assistant','World');"
            )
        db.close()
        store = WorkspaceStore(old)
        self.assertEqual(
            [n["content"] for n in store.messages("a")], ["Hello", "World"]
        )
        self.assertEqual(store.message_records("a")[1]["parent"], 1)

    def test_branches_keep_old_descendants_and_only_selected_context(self):
        s = self.store
        c = self.chat
        for role, text in [
            ("user", "one"),
            ("assistant", "old"),
            ("user", "followup"),
            ("assistant", "old tail"),
        ]:
            s.append(c, role, text)
        original = s.message_records(c)
        s.select_message(c, original[0]["id"], descendants=False)
        s.append(c, "assistant", "new")
        s.append(c, "user", "new followup")
        alternative = s.message_records(c)
        self.assertEqual(
            [n["content"] for n in s.messages(c)], ["one", "new", "new followup"]
        )
        self.assertEqual(len(alternative[1]["alternatives"]), 2)
        s.select_message(c, original[1]["id"])
        self.assertEqual(
            [n["content"] for n in s.messages(c)],
            ["one", "old", "followup", "old tail"],
        )
        s = WorkspaceStore(self.path)
        self.assertEqual(len(s.messages(c)), 4)
        fork = s.fork(c, original[1]["id"])
        self.assertEqual(len(s.messages(fork)), 2)
        s.append(fork, "user", "independent")
        self.assertEqual(len(s.messages(c)), 4)

    def test_delete_selected_alternative_restores_remaining_branch(self):
        s = self.store
        c = self.chat
        s.append(c, "user", "first")
        s.append(c, "assistant", "old")
        original = s.message_records(c)
        s.select_message(c, original[0]["id"], descendants=False)
        s.append(c, "assistant", "new")
        s.remove_message(c, s.message_records(c)[1]["id"])
        self.assertEqual(s.messages(c)[-1]["content"], "old")

    def test_nested_branch_choice_survives_switching_ancestor(self):
        s = self.store
        c = self.chat
        s.append(c, "user", "first")
        s.append(c, "assistant", "old")
        original = s.message_records(c)
        s.select_message(c, original[0]["id"], descendants=False)
        s.append(c, "assistant", "nested")
        s.select_message(c, original[1]["id"])
        s.select_message(c, None, descendants=False)
        s.append(c, "user", "other root")
        s.select_message(c, original[0]["id"])
        self.assertEqual(s.messages(c)[-1]["content"], "old")

    def test_move_back_pin_archive_and_delete(self):
        s = self.store
        c = self.chat
        folder = s.save_folder("Work")
        s.update_chat(c, folder=folder, move=True)
        s.update_chat(c, folder=None, move=True, pinned=True, archived=True)
        record = s.chat_records()[0]
        self.assertIsNone(record["folder"])
        self.assertTrue(record["pinned"] and record["archived"])
        s.append(c, "user", "hi")
        s.append(c, "assistant", "reply")
        s.remove_message(c, s.message_records(c)[1]["id"])
        self.assertEqual(len(s.messages(c)), 1)
        s.delete_chat(c)
        self.assertEqual(s.chat_records(), [])

    def service(self):
        def reply(chat, text, on_delta):
            on_delta("new answer")
            self.store.append(chat, "assistant", "new answer")

        backend = SimpleNamespace(store=self.store, reply=reply, speak=Mock())
        return WorkspaceService(backend=backend)

    def wait(self, service, result):
        job = service.jobs[result["job"]]
        with job.changed:
            job.changed.wait_for(lambda: job.status != "running", timeout=5)
        self.assertEqual(job.status, "done", job.error)

    def test_retry_and_edit_preserve_alternatives_and_fork(self):
        s = self.store
        c = self.chat
        s.append(c, "user", "question")
        s.append(c, "assistant", "original")
        service = self.service()
        original = s.message_records(c)
        self.wait(
            service,
            service.dispatch(
                "POST",
                "/chat/message",
                dict(chat=c, id=original[1]["id"], action="retry"),
                {},
            ),
        )
        self.assertEqual(s.messages(c)[-1]["content"], "new answer")
        self.assertEqual(len(s.message_records(c)[1]["alternatives"]), 2)
        self.wait(
            service,
            service.dispatch(
                "POST",
                "/chat/message",
                dict(chat=c, id=original[0]["id"], action="edit", text="edited"),
                {},
            ),
        )
        self.assertEqual(s.messages(c)[0]["content"], "edited")
        self.assertEqual(len(s.message_records(c)[0]["alternatives"]), 2)
        service.dispatch(
            "POST",
            "/chat/message",
            dict(chat=c, id=original[0]["id"], action="select"),
            {},
        )
        self.assertEqual(s.messages(c)[0]["content"], "question")
        r = service.dispatch(
            "POST",
            "/chat/message",
            dict(chat=c, id=original[0]["id"], action="fork"),
            {},
        )
        self.assertEqual(len(s.messages(r["chat"])), 1)
        service.dispatch("POST", "/chat/delete-many", {"chats": [c, r["chat"]]}, {})
        self.assertFalse(s.chat_records())

    def test_mutation_during_generation_rejected(self):
        from src.pia.service import Job

        service = self.service()
        self.store.append(self.chat, "user", "question")
        node = self.store.message_records(self.chat)[0]
        job = Job(self.chat)
        service.jobs[job.id] = job
        with self.assertRaises(ValueError):
            service.dispatch(
                "POST",
                "/chat/message",
                dict(chat=self.chat, id=node["id"], action="delete"),
                {},
            )

    def test_secretary_meet_lead_time_validated_and_saved(self):
        resources = SimpleNamespace(accounts=lambda provider: [])
        bot = Secretary(
            resources, self.store, Mock(), config_path=Path(self.temp.name) / "bot.json"
        )
        self.assertEqual(bot.config()["meet_minutes"], 2)
        bot.configure({"meet_minutes": 7})
        self.assertEqual(bot.config()["meet_minutes"], 7)
        with self.assertRaises(ValueError):
            bot.configure({"meet_minutes": -1})


if __name__ == "__main__":
    unittest.main()
