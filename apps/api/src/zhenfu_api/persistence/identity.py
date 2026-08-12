from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import ClassVar, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from zhenfu_api.auth import (
    DUMMY_PASSWORD_HASH,
    UserRole,
    hash_password,
    verify_password,
)
from zhenfu_api.domain.models import Team, User

from .tables import IdentitySessionRecord, TeamRecord, UserRecord, team_members


class SqlIdentityRepository:
    """SQL-backed users, memberships, teams, and opaque access sessions."""

    persistent: ClassVar[bool] = True

    def __init__(self, sessions: sessionmaker[Session], *, ttl_seconds: int = 3600) -> None:
        self._sessions = sessions
        self._ttl_seconds = ttl_seconds

    def register(self, email: str, password: str, display_name: str) -> User:
        normalized_email = email.strip().casefold()
        normalized_name = display_name.strip()
        if not normalized_name:
            raise ValueError("display name must not be empty")
        user = User(
            email=normalized_email,
            password_hash=hash_password(password),
            display_name=normalized_name,
        )
        record = UserRecord(
            id=user.id,
            email=user.email,
            password_hash=user.password_hash,
            display_name=user.display_name,
            active=user.active,
            role="user",
            created_at=user.created_at,
        )
        try:
            with self._sessions.begin() as session:
                session.add(record)
        except IntegrityError as exc:
            raise ValueError("email is already registered") from exc
        return user

    def login(self, email: str, password: str) -> str | None:
        normalized_email = email.strip().casefold()
        with self._sessions() as session:
            record = session.scalar(select(UserRecord).where(UserRecord.email == normalized_email))
            encoded = record.password_hash if record is not None else DUMMY_PASSWORD_HASH
            password_matches = verify_password(password, encoded)
            if not password_matches or record is None or not record.active:
                return None

            token = secrets.token_urlsafe(32)
            session.add(
                IdentitySessionRecord(
                    user_id=record.id,
                    token_hash=self._token_hash(token),
                    expires_at=datetime.now(UTC) + timedelta(seconds=self._ttl_seconds),
                )
            )
            session.commit()
            return token

    def user_for_token(self, token: str) -> User | None:
        now = datetime.now(UTC)
        with self._sessions() as session:
            row = session.execute(
                select(IdentitySessionRecord, UserRecord)
                .join(UserRecord, UserRecord.id == IdentitySessionRecord.user_id)
                .where(IdentitySessionRecord.token_hash == self._token_hash(token))
            ).one_or_none()
            if row is None:
                return None
            identity_session, user = row
            expires_at = identity_session.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if identity_session.revoked_at is not None or expires_at <= now or not user.active:
                return None
            return self._user(user)

    def revoke_token(self, token: str) -> bool:
        with self._sessions.begin() as session:
            identity_session = session.scalar(
                select(IdentitySessionRecord).where(
                    IdentitySessionRecord.token_hash == self._token_hash(token),
                    IdentitySessionRecord.revoked_at.is_(None),
                )
            )
            if identity_session is None:
                return False
            identity_session.revoked_at = datetime.now(UTC)
            return True

    def create_team(self, user: User, name: str) -> Team:
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("team name must not be empty")
        team = Team(name=normalized_name, owner_id=user.id)
        with self._sessions.begin() as session:
            if session.get(UserRecord, user.id) is None:
                raise ValueError("user does not exist")
            session.add(TeamRecord(id=team.id, name=team.name, owner_id=user.id))
            session.flush()
            session.execute(team_members.insert().values(team_id=team.id, user_id=user.id))
        return team

    def teams_for_user(self, user_id: UUID) -> list[Team]:
        with self._sessions() as session:
            records = list(
                session.scalars(
                    select(TeamRecord)
                    .join(team_members, team_members.c.team_id == TeamRecord.id)
                    .where(team_members.c.user_id == user_id)
                    .order_by(TeamRecord.name, TeamRecord.id)
                )
            )
            if not records:
                return []
            team_ids = [record.id for record in records]
            memberships = session.execute(
                select(team_members.c.team_id, team_members.c.user_id).where(
                    team_members.c.team_id.in_(team_ids)
                )
            )
            member_ids: dict[UUID, set[UUID]] = {team_id: set() for team_id in team_ids}
            for team_id, member_id in memberships:
                member_ids[team_id].add(member_id)
            return [
                Team(
                    id=record.id,
                    name=record.name,
                    owner_id=record.owner_id,
                    member_ids=member_ids[record.id],
                )
                for record in records
            ]

    def role_for_user(self, user_id: UUID) -> UserRole | None:
        with self._sessions() as session:
            role = session.scalar(select(UserRecord.role).where(UserRecord.id == user_id))
        if role in {"user", "editor", "admin"}:
            return cast(UserRole, role)
        return None

    def set_role(self, user_id: UUID, role: UserRole) -> None:
        """Provision an editorial role outside the public registration API."""
        if role not in {"user", "editor", "admin"}:
            raise ValueError("invalid user role")
        with self._sessions.begin() as session:
            user = session.get(UserRecord, user_id)
            if user is None:
                raise ValueError("user does not exist")
            user.role = role

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    @staticmethod
    def _user(record: UserRecord) -> User:
        created_at = record.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        return User(
            id=record.id,
            email=record.email,
            password_hash=record.password_hash,
            display_name=record.display_name,
            active=record.active,
            created_at=created_at,
        )
