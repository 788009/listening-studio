from __future__ import annotations

import unittest

from backend.app.core.auth import Principal, STUDENT_PRINCIPAL
from backend.app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from backend.app.db.models.user import User
from backend.app.services.authorization import (
    AuthorizationService,
    ResourceDescriptor,
    ResourceKind,
    ResourceStatus,
    ResourceVisibility,
)


class AuthorizationServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = AuthorizationService()
        self.owner = Principal(User(id=1))
        self.other_teacher = Principal(User(id=2))

    @staticmethod
    def resource(
        *,
        kind: ResourceKind = ResourceKind.AUDIO,
        visibility: ResourceVisibility = ResourceVisibility.PRIVATE,
        status: ResourceStatus = ResourceStatus.READY,
        author_id: int = 1,
        file_exists: bool = True,
    ) -> ResourceDescriptor:
        return ResourceDescriptor(
            kind=kind,
            author_id=author_id,
            visibility=visibility,
            status=status,
            file_exists=file_exists,
        )

    def test_view_permission_matrix(self) -> None:
        principals = {
            "student": STUDENT_PRINCIPAL,
            "owner": self.owner,
            "other_teacher": self.other_teacher,
        }
        statuses = list(ResourceStatus)

        for kind in ResourceKind:
            for visibility in ResourceVisibility:
                for status in statuses:
                    resource = self.resource(
                        kind=kind,
                        visibility=visibility,
                        status=status,
                    )
                    for principal_name, principal in principals.items():
                        with self.subTest(
                            kind=kind,
                            visibility=visibility,
                            status=status,
                            principal=principal_name,
                        ):
                            expected = self._expected_view(
                                principal_name,
                                kind,
                                visibility,
                                status,
                            )
                            self.assertEqual(
                                self.service.can_view(principal, resource),
                                expected,
                            )
                            if expected:
                                self.service.require_view(principal, resource)
                            else:
                                with self.assertRaises(NotFoundError):
                                    self.service.require_view(principal, resource)

    @staticmethod
    def _expected_view(
        principal_name: str,
        kind: ResourceKind,
        visibility: ResourceVisibility,
        status: ResourceStatus,
    ) -> bool:
        if principal_name == "owner":
            return True
        if visibility is not ResourceVisibility.PUBLIC:
            return False
        if status is not ResourceStatus.READY:
            return False
        if principal_name == "other_teacher":
            return True
        return kind is ResourceKind.AUDIO

    def test_missing_file_blocks_public_view_but_not_owner_metadata(self) -> None:
        resource = self.resource(
            visibility=ResourceVisibility.PUBLIC,
            file_exists=False,
        )

        self.assertTrue(self.service.can_view(self.owner, resource))
        self.assertFalse(self.service.can_view(self.other_teacher, resource))
        self.assertFalse(self.service.can_view(STUDENT_PRINCIPAL, resource))

    def test_edit_and_delete_are_owner_only(self) -> None:
        for visibility in ResourceVisibility:
            for status in ResourceStatus:
                resource = self.resource(visibility=visibility, status=status)
                with self.subTest(visibility=visibility, status=status):
                    for operation in (
                        self.service.require_edit,
                        self.service.require_delete,
                    ):
                        operation(self.owner, resource)
                        expected_error = (
                            ForbiddenError
                            if visibility is ResourceVisibility.PUBLIC
                            else NotFoundError
                        )
                        with self.assertRaises(expected_error):
                            operation(self.other_teacher, resource)

                    self.assertTrue(self.service.can_edit(self.owner, resource))
                    self.assertTrue(self.service.can_delete(self.owner, resource))
                    self.assertFalse(
                        self.service.can_edit(self.other_teacher, resource)
                    )

    def test_publish_requires_owner_ready_status_and_file(self) -> None:
        ready = self.resource()
        processing = self.resource(status=ResourceStatus.PROCESSING)
        missing_file = self.resource(file_exists=False)

        self.assertTrue(self.service.can_publish(self.owner, ready))
        self.service.require_publish(self.owner, ready)
        for unavailable in (processing, missing_file):
            self.assertFalse(self.service.can_publish(self.owner, unavailable))
            with self.assertRaises(ConflictError):
                self.service.require_publish(self.owner, unavailable)
        with self.assertRaises(NotFoundError):
            self.service.require_publish(self.other_teacher, ready)
        with self.assertRaises(ForbiddenError):
            self.service.require_publish(
                self.other_teacher,
                self.resource(visibility=ResourceVisibility.PUBLIC),
            )

    def test_example_audio_must_be_public_ready_and_used_by_teacher(self) -> None:
        public_audio = self.resource(visibility=ResourceVisibility.PUBLIC)
        private_audio = self.resource()
        failed_audio = self.resource(
            visibility=ResourceVisibility.PUBLIC,
            status=ResourceStatus.FAILED,
        )
        public_voice = self.resource(
            kind=ResourceKind.VOICE,
            visibility=ResourceVisibility.PUBLIC,
        )

        self.assertTrue(
            self.service.can_use_as_example(self.other_teacher, public_audio)
        )
        for unavailable in (private_audio, failed_audio, public_voice):
            self.assertFalse(
                self.service.can_use_as_example(self.other_teacher, unavailable)
            )
        with self.assertRaises(NotFoundError):
            self.service.require_use_as_example(self.other_teacher, private_audio)
        with self.assertRaises(ConflictError):
            self.service.require_use_as_example(self.other_teacher, failed_audio)
        with self.assertRaises(ForbiddenError):
            self.service.require_use_as_example(STUDENT_PRINCIPAL, public_audio)

    def test_synthesis_voice_must_be_accessible_and_ready(self) -> None:
        own_private_voice = self.resource(kind=ResourceKind.VOICE)
        public_voice = self.resource(
            kind=ResourceKind.VOICE,
            visibility=ResourceVisibility.PUBLIC,
        )
        other_private_voice = self.resource(
            kind=ResourceKind.VOICE,
            author_id=2,
        )
        failed_voice = self.resource(
            kind=ResourceKind.VOICE,
            visibility=ResourceVisibility.PUBLIC,
            status=ResourceStatus.FAILED,
        )

        self.assertTrue(
            self.service.can_use_for_synthesis(self.owner, own_private_voice)
        )
        self.assertTrue(
            self.service.can_use_for_synthesis(self.other_teacher, public_voice)
        )
        self.assertFalse(
            self.service.can_use_for_synthesis(self.owner, other_private_voice)
        )
        with self.assertRaises(NotFoundError):
            self.service.require_use_for_synthesis(
                self.owner,
                other_private_voice,
            )
        with self.assertRaises(ConflictError):
            self.service.require_use_for_synthesis(self.other_teacher, failed_voice)
        with self.assertRaises(ForbiddenError):
            self.service.require_use_for_synthesis(
                STUDENT_PRINCIPAL,
                public_voice,
            )


if __name__ == "__main__":
    unittest.main()
