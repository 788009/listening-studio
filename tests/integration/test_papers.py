from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

import httpx
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy.exc import IntegrityError

from backend.app.core.config import Settings
from backend.app.db.models.audio import (
    Audio,
    AudioSourceType,
    AudioStatus,
    AudioVisibility,
)
from backend.app.db.models.paper import Paper, PaperItem, PaperPreset
from backend.app.factory import create_app
from backend.app.integrations.cosyvoice import FakeCosyVoiceIntegration
from backend.app.integrations.identity import DEBUG_ISSUER_HEADER, DEBUG_SUBJECT_HEADER
from backend.app.repositories.users import UserRepository
from backend.app.services.audio_storage import AudioStorage
from backend.app.services.audios import AudioService


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class PaperIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_dir.name)
        database_url = f"sqlite:///{self.root / 'papers.sqlite3'}"
        config = Config(PROJECT_ROOT / "alembic.ini")
        config.set_main_option("sqlalchemy.url", database_url)
        command.upgrade(config, "head")
        self.settings = Settings(
            _env_file=None,
            environment="test",
            debug_auth_enabled=True,
            auth_session_secret="test-session-secret-with-32-characters",
            cosyvoice_model_dir=self.root / "model",
            database_url=database_url,
            data_dir=self.root / "data",
            log_dir=self.root / "logs",
        )
        self.app = create_app(self.settings)
        self.storage = AudioStorage(self.settings.data_dir)
        self.profile("first", "TeacherOne")
        self.profile("second", "TeacherTwo")

    def tearDown(self) -> None:
        self.app.state.db_engine.dispose()
        self.temporary_dir.cleanup()

    @staticmethod
    def headers(subject: str) -> dict[str, str]:
        return {
            DEBUG_ISSUER_HEADER: "https://issuer.example",
            DEBUG_SUBJECT_HEADER: subject,
        }

    @staticmethod
    async def request(
        app: FastAPI,
        method: str,
        path: str,
        **kwargs: object,
    ) -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return await client.request(method, path, **kwargs)

    def send(self, method: str, path: str, **kwargs: object) -> httpx.Response:
        return asyncio.run(self.request(self.app, method, path, **kwargs))

    def profile(self, subject: str, user_id: str) -> None:
        response = self.send(
            "POST",
            "/api/users/me/profile",
            headers=self.headers(subject),
            json={"userId": user_id, "username": user_id},
        )
        self.assertEqual(response.status_code, 200)

    def ready_audio(
        self,
        user_id: str,
        title: str,
        visibility: AudioVisibility,
    ) -> int:
        with self.app.state.session_factory() as session:
            user = UserRepository().get_by_user_id(session, user_id)
            assert user is not None
            service = AudioService(self.storage)
            audio = service.create_audio(
                session,
                author=user,
                title=title,
                source_type=AudioSourceType.CORPUS,
                text="Listening text",
            )
            service.transition_status(session, audio, AudioStatus.PROCESSING)
            voice_file = self.root / f"source-{audio.id}.pt"
            voice_file.write_bytes(b"voice")
            FakeCosyVoiceIntegration().synthesize(
                voice_file,
                "text",
                self.storage.temporary_audio_path(audio.id),
            )
            self.storage.atomic_replace(audio.id, audio.id)
            service.record_file_metadata(session, audio)
            service.transition_status(session, audio, AudioStatus.READY)
            service.set_visibility(session, audio, visibility)
            session.commit()
            return audio.id

    def pending_audio(self, user_id: str) -> int:
        with self.app.state.session_factory() as session:
            user = UserRepository().get_by_user_id(session, user_id)
            assert user is not None
            audio = AudioService(self.storage).create_audio(
                session,
                author=user,
                title="Pending audio",
                source_type=AudioSourceType.CORPUS,
                text="Text",
            )
            session.commit()
            return audio.id

    @staticmethod
    def preset_payload(name: str = "Exam preset") -> dict[str, object]:
        return {
            "name": name,
            "introSilenceMilliseconds": 1500,
            "interItemSilenceMilliseconds": 2500,
            "repeatCount": 2,
            "outroSilenceMilliseconds": 3500,
        }

    def test_builtin_and_custom_presets_are_scoped_and_read_only(self) -> None:
        builtins = self.send(
            "GET",
            "/api/paper-presets",
            headers=self.headers("first"),
        )
        created = self.send(
            "POST",
            "/api/paper-presets",
            headers=self.headers("first"),
            json=self.preset_payload(),
        )
        other_list = self.send(
            "GET",
            "/api/paper-presets",
            headers=self.headers("second"),
        )

        self.assertEqual(builtins.status_code, 200)
        self.assertEqual(
            [(item["name"], item["isBuiltin"]) for item in builtins.json()],
            [("Standard", True), ("Review", True)],
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(len(other_list.json()), 2)

        custom_id = created.json()["id"]
        hidden_update = self.send(
            "PUT",
            f"/api/paper-presets/{custom_id}",
            headers=self.headers("second"),
            json=self.preset_payload("Other edit"),
        )
        builtin_update = self.send(
            "PUT",
            f"/api/paper-presets/{builtins.json()[0]['id']}",
            headers=self.headers("first"),
            json=self.preset_payload("Builtin edit"),
        )
        updated = self.send(
            "PUT",
            f"/api/paper-presets/{custom_id}",
            headers=self.headers("first"),
            json=self.preset_payload("Updated preset"),
        )

        self.assertEqual(hidden_update.status_code, 404)
        self.assertEqual(builtin_update.status_code, 409)
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["name"], "Updated preset")

    def test_paper_preserves_order_and_preset_snapshot(self) -> None:
        first_audio = self.ready_audio(
            "TeacherOne", "First", AudioVisibility.PRIVATE
        )
        second_audio = self.ready_audio(
            "TeacherTwo", "Second", AudioVisibility.PUBLIC
        )
        preset = self.send(
            "POST",
            "/api/paper-presets",
            headers=self.headers("first"),
            json=self.preset_payload(),
        ).json()

        created = self.send(
            "POST",
            "/api/papers",
            headers=self.headers("first"),
            json={
                "title": "  Ｍidterm Paper  ",
                "presetId": preset["id"],
                "audioIds": [second_audio, first_audio, second_audio],
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["title"], "Midterm Paper")
        self.assertEqual(
            [item["audioId"] for item in created.json()["items"]],
            [second_audio, first_audio, second_audio],
        )
        self.assertEqual(
            [item["position"] for item in created.json()["items"]],
            [0, 1, 2],
        )

        changed_payload = self.preset_payload("Changed")
        changed_payload["repeatCount"] = 5
        changed_payload["interItemSilenceMilliseconds"] = 9000
        self.send(
            "PUT",
            f"/api/paper-presets/{preset['id']}",
            headers=self.headers("first"),
            json=changed_payload,
        )
        detail = self.send(
            "GET",
            f"/api/papers/{created.json()['id']}",
            headers=self.headers("first"),
        )
        hidden = self.send(
            "GET",
            f"/api/papers/{created.json()['id']}",
            headers=self.headers("second"),
        )

        self.assertEqual(detail.json()["repeatCount"], 2)
        self.assertEqual(detail.json()["interItemSilenceMilliseconds"], 2500)
        self.assertEqual(hidden.status_code, 404)

    def test_inaccessible_and_unready_audio_are_rejected(self) -> None:
        private_other = self.ready_audio(
            "TeacherTwo", "Private other", AudioVisibility.PRIVATE
        )
        pending = self.pending_audio("TeacherOne")
        presets = self.send(
            "GET",
            "/api/paper-presets",
            headers=self.headers("first"),
        ).json()
        preset_id = presets[0]["id"]

        inaccessible = self.send(
            "POST",
            "/api/papers",
            headers=self.headers("first"),
            json={
                "title": "Hidden",
                "presetId": preset_id,
                "audioIds": [private_other],
            },
        )
        unready = self.send(
            "POST",
            "/api/papers",
            headers=self.headers("first"),
            json={"title": "Pending", "presetId": preset_id, "audioIds": [pending]},
        )
        invalid_preset = self.send(
            "POST",
            "/api/paper-presets",
            headers=self.headers("first"),
            json={**self.preset_payload(), "repeatCount": 11},
        )

        self.assertEqual(inaccessible.status_code, 404)
        self.assertEqual(unready.status_code, 409)
        self.assertEqual(invalid_preset.status_code, 422)

    def test_paper_references_prevent_visibility_loss_and_deletion(self) -> None:
        source = self.ready_audio(
            "TeacherTwo", "Shared source", AudioVisibility.PUBLIC
        )
        own_source = self.ready_audio(
            "TeacherOne", "Own source", AudioVisibility.PUBLIC
        )
        preset_id = self.send(
            "GET",
            "/api/paper-presets",
            headers=self.headers("first"),
        ).json()[0]["id"]
        paper = self.send(
            "POST",
            "/api/papers",
            headers=self.headers("first"),
            json={
                "title": "References",
                "presetId": preset_id,
                "audioIds": [source, own_source],
            },
        )
        self.assertEqual(paper.status_code, 201)

        foreign_private = self.send(
            "PATCH",
            f"/api/audios/{source}",
            headers=self.headers("second"),
            json={"visibility": "private"},
        )
        own_private = self.send(
            "PATCH",
            f"/api/audios/{own_source}",
            headers=self.headers("first"),
            json={"visibility": "private"},
        )
        source_delete = self.send(
            "DELETE",
            f"/api/audios/{source}",
            headers=self.headers("second"),
        )

        self.assertEqual(foreign_private.status_code, 409)
        self.assertEqual(
            foreign_private.json()["error"]["details"]["paperReferenceCount"],
            1,
        )
        self.assertEqual(own_private.status_code, 200)
        self.assertEqual(source_delete.status_code, 409)
        self.assertEqual(
            source_delete.json()["error"]["details"]["paperItemCount"],
            1,
        )

    def test_database_constraints_reject_invalid_order_and_parameters(self) -> None:
        with self.app.state.session_factory() as session:
            first_preset = session.get(PaperPreset, 1)
            assert first_preset is not None
            first_preset.repeat_count = 0
            with self.assertRaises(IntegrityError):
                session.flush()
            session.rollback()

            user = UserRepository().get_by_user_id(session, "TeacherOne")
            assert user is not None
            paper = Paper(
                owner=user,
                title="Constraint",
                normalized_title="constraint",
                intro_silence_milliseconds=0,
                inter_item_silence_milliseconds=0,
                repeat_count=1,
                outro_silence_milliseconds=0,
            )
            session.add(paper)
            session.flush()
            session.add(PaperItem(paper=paper, audio_id=999, position=-1))
            with self.assertRaises(IntegrityError):
                session.flush()


if __name__ == "__main__":
    unittest.main()
