"""Tablas de SQLAlchemy Core.

Reflejan a mano `supabase/migrations/*.sql`, que es la única fuente de verdad
del esquema: si cambias una migración, actualiza también este archivo.
"""

from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    Numeric,
    SmallInteger,
    String,
    Table,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = MetaData()


def _timestamps() -> list[Column[Any]]:
    return [
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        Column("updated_at", DateTime(timezone=True)),
    ]


def _id() -> Column[Any]:
    return Column("id", UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())


auth_users = Table(
    "users",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("email", String),
    # Null mientras la invitación no se acepta (Supabase lo llena al abrir el enlace).
    Column("email_confirmed_at", DateTime(timezone=True)),
    Column("invited_at", DateTime(timezone=True)),
    schema="auth",
)

organizations = Table(
    "organizations", metadata, _id(), Column("name", Text), *_timestamps(), schema="app"
)

user_roles = Table(
    "user_roles",
    metadata,
    Column("user_id", UUID(as_uuid=True), ForeignKey("auth.users.id"), primary_key=True),
    Column(
        "organization_id", UUID(as_uuid=True), ForeignKey("app.organizations.id"), primary_key=True
    ),
    Column("role", Text, nullable=False),
    *_timestamps(),
    schema="app",
)

judges = Table(
    "judges",
    metadata,
    Column("user_id", UUID(as_uuid=True), ForeignKey("auth.users.id"), primary_key=True),
    Column("organization_id", UUID(as_uuid=True), ForeignKey("app.organizations.id")),
    Column("full_name", Text, nullable=False),
    Column("active", Boolean, nullable=False, server_default="true"),
    *_timestamps(),
    schema="app",
)

events = Table(
    "events",
    metadata,
    _id(),
    Column("organization_id", UUID(as_uuid=True), ForeignKey("app.organizations.id")),
    Column("slug", Text, nullable=False, unique=True),
    Column("name", Text, nullable=False),
    Column("brand", Text, nullable=False),
    Column("logo_path", Text),
    Column("venue", Text),
    Column("country_code", String(2)),
    Column("timezone", Text, nullable=False),
    Column("starts_on", Date, nullable=False),
    Column("ends_on", Date, nullable=False),
    Column("status", Text, nullable=False, server_default="draft"),
    Column("default_rubric_id", UUID(as_uuid=True)),
    Column("publication_settings", JSONB, nullable=False),
    *_timestamps(),
    schema="app",
)

rubrics = Table(
    "rubrics",
    metadata,
    _id(),
    Column("event_id", UUID(as_uuid=True), ForeignKey("app.events.id"), nullable=False),
    Column("name", Text, nullable=False),
    Column("scale_min", SmallInteger, nullable=False),
    Column("scale_max", SmallInteger, nullable=False),
    *_timestamps(),
    schema="app",
)

criteria = Table(
    "criteria",
    metadata,
    _id(),
    Column("rubric_id", UUID(as_uuid=True), ForeignKey("app.rubrics.id"), nullable=False),
    Column("name", Text, nullable=False),
    Column("description", Text),
    Column("weight", Numeric(5, 2), nullable=False),
    Column("position", Integer, nullable=False),
    Column("level_descriptors", JSONB, nullable=False),
    *_timestamps(),
    schema="app",
)

committees = Table(
    "committees",
    metadata,
    _id(),
    Column("event_id", UUID(as_uuid=True), ForeignKey("app.events.id"), nullable=False),
    Column("name", Text, nullable=False),
    Column("acronym", Text, nullable=False),
    Column("slug", Text, nullable=False),
    Column("type", Text, nullable=False),
    Column("delegation_mode", Text, nullable=False),
    Column("sessions_count", Integer, nullable=False),
    Column("rubric_id", UUID(as_uuid=True), ForeignKey("app.rubrics.id")),
    Column("award_quotas", JSONB, nullable=False),
    *_timestamps(),
    schema="app",
)

delegations = Table(
    "delegations",
    metadata,
    _id(),
    Column("committee_id", UUID(as_uuid=True), ForeignKey("app.committees.id"), nullable=False),
    Column("country_code", String(2)),
    Column("character_name", Text),
    Column("institution", Text),
    *_timestamps(),
    schema="app",
)

delegates = Table(
    "delegates",
    metadata,
    _id(),
    Column("delegation_id", UUID(as_uuid=True), ForeignKey("app.delegations.id"), nullable=False),
    Column("full_name", Text, nullable=False),
    Column("institution", Text),
    *_timestamps(),
    schema="app",
)

committee_judges = Table(
    "committee_judges",
    metadata,
    Column("committee_id", UUID(as_uuid=True), ForeignKey("app.committees.id"), primary_key=True),
    Column("judge_id", UUID(as_uuid=True), ForeignKey("app.judges.user_id"), primary_key=True),
    Column("role", Text, nullable=False, server_default="judge"),
    *_timestamps(),
    schema="app",
)

event_judges = Table(
    "event_judges",
    metadata,
    Column("event_id", UUID(as_uuid=True), ForeignKey("app.events.id"), primary_key=True),
    Column("judge_id", UUID(as_uuid=True), ForeignKey("app.judges.user_id"), primary_key=True),
    *_timestamps(),
    schema="app",
)

scoring_sessions = Table(
    "scoring_sessions",
    metadata,
    _id(),
    Column("committee_id", UUID(as_uuid=True), ForeignKey("app.committees.id"), nullable=False),
    Column("number", Integer, nullable=False),
    Column("status", Text, nullable=False, server_default="closed"),
    Column("opened_at", DateTime(timezone=True)),
    Column("closed_at", DateTime(timezone=True)),
    *_timestamps(),
    schema="app",
)

scores = Table(
    "scores",
    metadata,
    _id(),
    Column("client_id", UUID(as_uuid=True), nullable=False, unique=True),
    Column("judge_id", UUID(as_uuid=True), ForeignKey("app.judges.user_id"), nullable=False),
    Column("delegate_id", UUID(as_uuid=True), ForeignKey("app.delegates.id"), nullable=False),
    Column("session_id", UUID(as_uuid=True), ForeignKey("app.scoring_sessions.id"), nullable=False),
    Column("criterion_id", UUID(as_uuid=True), ForeignKey("app.criteria.id"), nullable=False),
    Column("value", SmallInteger, nullable=False),
    Column("comment", Text),
    Column("client_updated_at", DateTime(timezone=True), nullable=False),
    *_timestamps(),
    schema="app",
)

awards = Table(
    "awards",
    metadata,
    _id(),
    Column("committee_id", UUID(as_uuid=True), ForeignKey("app.committees.id"), nullable=False),
    Column("award_type", Text, nullable=False),
    Column("delegation_id", UUID(as_uuid=True), ForeignKey("app.delegations.id"), nullable=False),
    Column("position", Integer, nullable=False),
    Column("assigned_by", UUID(as_uuid=True)),
    Column("assigned_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    *_timestamps(),
    schema="app",
)

result_snapshots = Table(
    "result_snapshots",
    metadata,
    _id(),
    Column("event_id", UUID(as_uuid=True), ForeignKey("app.events.id"), nullable=False),
    Column("data", JSONB, nullable=False),
    Column("created_by", UUID(as_uuid=True)),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    schema="app",
)

audit_log = Table(
    "audit_log",
    metadata,
    _id(),
    Column("actor_id", UUID(as_uuid=True)),
    Column("entity", Text, nullable=False),
    Column("entity_id", UUID(as_uuid=True)),
    Column("action", Text, nullable=False),
    Column("before", JSONB),
    Column("after", JSONB),
    Column("at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    schema="app",
)

public_results = Table(
    "public_results",
    metadata,
    Column("event_slug", Text, primary_key=True),
    Column("event_id", UUID(as_uuid=True), nullable=False, unique=True),
    Column("published", Boolean, nullable=False),
    Column("version", Integer, nullable=False),
    Column("data", JSONB, nullable=False),
    Column("published_at", DateTime(timezone=True)),
    *_timestamps(),
    schema="public",
)
