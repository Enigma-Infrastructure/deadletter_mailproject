from itertools import product

from django.test import SimpleTestCase

from .access_policy import (
    ContentAccess, ParticipantStatus, Viewer, Visibility,
    can_read_body, can_read_request, can_read_social_address,
)


class AccessPolicyTests(SimpleTestCase):
    def test_request_and_body_access_matrix(self):
        for authenticated, active, status, request_visibility, body_visibility, request_restricted, body_restricted in product(
            (False, True), (False, True), tuple(ParticipantStatus),
            tuple(Visibility), tuple(Visibility), (False, True), (False, True),
        ):
            with self.subTest(
                authenticated=authenticated, active=active, status=status,
                request_visibility=request_visibility, body_visibility=body_visibility,
                request_restricted=request_restricted, body_restricted=body_restricted,
            ):
                viewer = Viewer(authenticated, active, status)
                request = ContentAccess(request_visibility, request_restricted)
                body = ContentAccess(body_visibility, body_restricted)
                approved = authenticated and active and status == ParticipantStatus.APPROVED
                public_request = request_visibility == Visibility.PUBLIC and not request_restricted
                public_body = body_visibility == Visibility.PUBLIC and not body_restricted
                self.assertEqual(can_read_request(viewer, request), approved or public_request)
                self.assertEqual(can_read_social_address(viewer, request), approved)
                self.assertEqual(can_read_body(viewer, request, body), approved or (public_request and public_body))

    def test_unpublished_request_is_hidden_even_from_approved_participant(self):
        request = ContentAccess(Visibility.PUBLIC, published=False)
        for viewer in (Viewer(), Viewer(True, True, ParticipantStatus.APPROVED)):
            self.assertFalse(can_read_request(viewer, request))
            self.assertFalse(can_read_social_address(viewer, request))
            self.assertFalse(can_read_body(viewer, request, ContentAccess(Visibility.PUBLIC)))

    def test_unpublished_body_does_not_hide_public_request(self):
        request = ContentAccess(Visibility.PUBLIC)
        body = ContentAccess(Visibility.PUBLIC, published=False)
        for viewer in (Viewer(), Viewer(True, True, ParticipantStatus.APPROVED)):
            self.assertTrue(can_read_request(viewer, request))
            self.assertFalse(can_read_body(viewer, request, body))

    def test_unknown_visibility_fails_closed(self):
        viewer = Viewer(True, True, ParticipantStatus.APPROVED)
        unknown = ContentAccess("selected_groups_not_implemented")
        public = ContentAccess(Visibility.PUBLIC)
        self.assertFalse(can_read_request(viewer, unknown))
        self.assertFalse(can_read_social_address(viewer, unknown))
        self.assertFalse(can_read_body(viewer, unknown, public))
        self.assertFalse(can_read_body(viewer, public, unknown))

    def test_unknown_approval_does_not_grant_participant_access(self):
        viewer = Viewer(True, True, "unknown")
        self.assertFalse(viewer.approved)
        self.assertFalse(can_read_request(viewer, ContentAccess()))

    def test_public_body_cannot_broaden_private_request(self):
        self.assertFalse(can_read_body(Viewer(), ContentAccess(), ContentAccess(Visibility.PUBLIC)))

    def test_restricted_body_leaves_public_request_visible(self):
        viewer = Viewer()
        request = ContentAccess(Visibility.PUBLIC)
        self.assertTrue(can_read_request(viewer, request))
        self.assertFalse(can_read_body(viewer, request, ContentAccess(Visibility.PUBLIC, restricted=True)))

    def test_default_viewer_and_content_do_not_grant_public_access(self):
        self.assertFalse(can_read_request(Viewer(), ContentAccess()))
        self.assertFalse(can_read_social_address(Viewer(), ContentAccess()))
        self.assertFalse(can_read_body(Viewer(), ContentAccess(), ContentAccess()))
