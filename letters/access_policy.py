"""Pure access decisions for the forthcoming participant privacy feature.

Not yet wired to views. Persisted approval/visibility adapters follow in a
separate migration batch. Never derive these inputs from client claims.
Staff access through admin is a separate permission path.
"""
from dataclasses import dataclass
from enum import StrEnum


class Visibility(StrEnum):
    PUBLIC = "public"
    PARTICIPANTS_ONLY = "participants_only"


class ParticipantStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUSPENDED = "suspended"


@dataclass(frozen=True)
class Viewer:
    authenticated: bool = False
    active: bool = False
    status: str = ParticipantStatus.PENDING

    @property
    def approved(self):
        return self.authenticated and self.active and self.status == ParticipantStatus.APPROVED


@dataclass(frozen=True)
class ContentAccess:
    # Safe defaults for missing or not-yet-migrated policy information.
    visibility: str = Visibility.PARTICIPANTS_ONLY
    restricted: bool = False
    published: bool = True


def can_read_request(viewer, request_access):
    """Request prompt and permitted alias share this audience."""
    if not request_access.published or request_access.visibility not in tuple(Visibility):
        return False
    if viewer.approved:
        return True
    return request_access.visibility == Visibility.PUBLIC and not request_access.restricted


def can_read_social_address(viewer, request_access):
    return viewer.approved and can_read_request(viewer, request_access)


def can_read_body(viewer, request_access, body_access):
    """The body cannot broaden its originating request's audience."""
    if not can_read_request(viewer, request_access):
        return False
    if not body_access.published or body_access.visibility not in tuple(Visibility):
        return False
    if viewer.approved:
        return True
    return body_access.visibility == Visibility.PUBLIC and not body_access.restricted
