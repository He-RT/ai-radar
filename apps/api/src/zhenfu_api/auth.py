from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import ClassVar, Literal, Protocol
from uuid import UUID

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from zhenfu_api.domain.models import Team, User

UserRole = Literal["user", "editor", "admin"]
EDITORIAL_ROLES: frozenset[UserRole] = frozenset({"editor", "admin"})

PASSWORD_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)
# Login always performs one Argon2id verification, including when the email is
# unknown. Keeping a valid precomputed hash avoids making unknown-email attempts
# observably cheaper while also avoiding an extra hash operation on that path.
DUMMY_PASSWORD_HASH = PASSWORD_HASHER.hash("identity-login-dummy-password")


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("password must contain at least 12 characters")
    if len(password.encode("utf-8")) > 1024:
        raise ValueError("password is too long")
    return PASSWORD_HASHER.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    try:
        return PASSWORD_HASHER.verify(encoded, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


class IdentityRepository(Protocol):
    """Persistence boundary used by the HTTP identity endpoints."""

    persistent: ClassVar[bool]

    def register(self, email: str, password: str, display_name: str) -> User: ...

    def login(self, email: str, password: str) -> str | None: ...

    def user_for_token(self, token: str) -> User | None: ...

    def revoke_token(self, token: str) -> bool: ...

    def create_team(self, user: User, name: str) -> Team: ...

    def teams_for_user(self, user_id: UUID) -> list[Team]: ...

    def role_for_user(self, user_id: UUID) -> UserRole | None: ...

    def set_role(self, user_id: UUID, role: UserRole) -> None: ...


@dataclass
class MemorySession:
    user_id: UUID
    expires_at: datetime
    revoked_at: datetime | None = None


@dataclass
class IdentityStore:
    """Thread-safe development/test implementation of :class:`IdentityRepository`."""

    persistent: ClassVar[bool] = False
    ttl_seconds: int = 3600
    users: dict[UUID, User] = field(default_factory=dict)
    emails: dict[str, UUID] = field(default_factory=dict)
    roles: dict[UUID, UserRole] = field(default_factory=dict)
    teams: dict[UUID, Team] = field(default_factory=dict)
    sessions: dict[str, MemorySession] = field(default_factory=dict)
    _lock: RLock = field(default_factory=RLock)

    def register(self, email: str, password: str, display_name: str) -> User:
        normalized_email = email.strip().casefold()
        normalized_name = display_name.strip()
        if not normalized_name:
            raise ValueError("display name must not be empty")
        with self._lock:
            if normalized_email in self.emails:
                raise ValueError("email is already registered")
            user = User(
                email=normalized_email,
                password_hash=hash_password(password),
                display_name=normalized_name,
            )
            self.users[user.id] = user
            self.emails[normalized_email] = user.id
            self.roles[user.id] = "user"
            return user

    def login(self, email: str, password: str) -> str | None:
        with self._lock:
            user_id = self.emails.get(email.strip().casefold())
            user = self.users.get(user_id) if user_id else None
        encoded = user.password_hash if user else DUMMY_PASSWORD_HASH
        if not verify_password(password, encoded) or user is None or not user.active:
            return None
        token = secrets.token_urlsafe(32)
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self._lock:
            self.sessions[digest] = MemorySession(
                user_id=user.id,
                expires_at=datetime.now(UTC) + timedelta(seconds=self.ttl_seconds),
            )
        return token

    def user_for_token(self, token: str) -> User | None:
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self._lock:
            session = self.sessions.get(digest)
            if session is None or session.revoked_at is not None:
                return None
            if session.expires_at <= datetime.now(UTC):
                self.sessions.pop(digest, None)
                return None
            user = self.users.get(session.user_id)
            return user if user is not None and user.active else None

    def revoke_token(self, token: str) -> bool:
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self._lock:
            session = self.sessions.get(digest)
            if session is None or session.revoked_at is not None:
                return False
            session.revoked_at = datetime.now(UTC)
            return True

    def create_team(self, user: User, name: str) -> Team:
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("team name must not be empty")
        team = Team(name=normalized_name, owner_id=user.id)
        with self._lock:
            self.teams[team.id] = team
        return team

    def teams_for_user(self, user_id: UUID) -> list[Team]:
        with self._lock:
            return sorted(
                (team for team in self.teams.values() if user_id in team.member_ids),
                key=lambda team: (team.name.casefold(), str(team.id)),
            )

    def role_for_user(self, user_id: UUID) -> UserRole | None:
        with self._lock:
            return self.roles.get(user_id)

    def set_role(self, user_id: UUID, role: UserRole) -> None:
        """Test/development provisioning hook; this is intentionally not an HTTP endpoint."""
        if role not in {"user", "editor", "admin"}:
            raise ValueError("invalid user role")
        with self._lock:
            if user_id not in self.users:
                raise ValueError("user does not exist")
            self.roles[user_id] = role
