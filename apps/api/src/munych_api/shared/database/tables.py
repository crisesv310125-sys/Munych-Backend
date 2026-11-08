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
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

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
    Column("event_type", Text, nullable=False, server_default="judges_only"),
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
    Column("peer_vote_opens_at", DateTime(timezone=True)),
    Column("peer_vote_closes_at", DateTime(timezone=True)),
    # Desempate manual del admin (2026-11-07): orden de las delegaciones empatadas.
    Column(
        "tiebreak_order", ARRAY(UUID(as_uuid=True)), nullable=False, server_default=text("'{}'")
    ),
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

voter_tokens = Table(
    "voter_tokens",
    metadata,
    _id(),
    Column("delegate_id", UUID(as_uuid=True), ForeignKey("app.delegates.id"), nullable=False),
    Column("event_id", UUID(as_uuid=True), ForeignKey("app.events.id"), nullable=False),
    Column("token_hash", Text, nullable=False, unique=True),
    # Código corto de respaldo (2026-11-07); null en los accesos generados antes.
    Column("code_hash", Text, unique=True),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True)),
    Column("last_used_at", DateTime(timezone=True)),
    Column("created_by", UUID(as_uuid=True)),
    *_timestamps(),
    schema="app",
)

peer_votes = Table(
    "peer_votes",
    metadata,
    _id(),
    Column("voter_delegate_id", UUID(as_uuid=True), ForeignKey("app.delegates.id"), nullable=False),
    Column("committee_id", UUID(as_uuid=True), ForeignKey("app.committees.id"), nullable=False),
    Column("award_type", Text, nullable=False),
    Column("delegation_id", UUID(as_uuid=True), ForeignKey("app.delegations.id"), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
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

# ---------------------------------------------------------------- staff (2026-11-08)

staff_types = Table(
    "staff_types",
    metadata,
    _id(),
    Column(
        "organization_id", UUID(as_uuid=True), ForeignKey("app.organizations.id"), nullable=False
    ),
    Column("name", Text, nullable=False),
    Column("code", Text, nullable=False),
    Column("color", Text, nullable=False, server_default="#98A6B5"),
    Column("description", Text),
    Column("evaluates", Text),
    Column("all_committees", Boolean, nullable=False, server_default="true"),
    Column("committee_ids", ARRAY(UUID(as_uuid=True)), nullable=False, server_default=text("'{}'")),
    Column("min_evaluators", SmallInteger, nullable=False, server_default="2"),
    Column("counts_as", Text, nullable=False, server_default="none"),
    Column("scale_min", Numeric(6, 2), nullable=False, server_default="0"),
    Column("scale_max", Numeric(6, 2), nullable=False, server_default="10"),
    Column("scale_step", Numeric(6, 2), nullable=False, server_default="0.5"),
    Column("criteria", JSONB, nullable=False, server_default=text("'[]'")),
    Column("position", Integer, nullable=False, server_default="0"),
    Column("archived_at", DateTime(timezone=True)),
    *_timestamps(),
    schema="app",
)

staff_people = Table(
    "staff_people",
    metadata,
    _id(),
    Column(
        "organization_id", UUID(as_uuid=True), ForeignKey("app.organizations.id"), nullable=False
    ),
    Column("full_name", Text, nullable=False),
    Column("email", Text),
    Column("title", Text),
    Column("token_hash", Text, unique=True),
    Column("token_issued_at", DateTime(timezone=True)),
    Column("token_expires_at", DateTime(timezone=True)),
    Column("last_used_at", DateTime(timezone=True)),
    *_timestamps(),
    schema="app",
)

staff_members = Table(
    "staff_members",
    metadata,
    _id(),
    Column("staff_type_id", UUID(as_uuid=True), ForeignKey("app.staff_types.id"), nullable=False),
    Column("person_id", UUID(as_uuid=True), ForeignKey("app.staff_people.id"), nullable=False),
    Column("role", Text, nullable=False, server_default="evaluator"),
    Column("committee_ids", ARRAY(UUID(as_uuid=True)), nullable=False, server_default=text("'{}'")),
    Column("removed_at", DateTime(timezone=True)),
    Column("evaluations_count", Boolean, nullable=False, server_default="true"),
    *_timestamps(),
    schema="app",
)

staff_evaluations = Table(
    "staff_evaluations",
    metadata,
    _id(),
    Column("member_id", UUID(as_uuid=True), ForeignKey("app.staff_members.id"), nullable=False),
    Column("candidate_id", UUID(as_uuid=True), nullable=False),
    Column("values", JSONB, nullable=False, server_default=text("'{}'")),
    Column("comment", Text),
    Column("client_updated_at", DateTime(timezone=True)),
    *_timestamps(),
    schema="app",
)

staff_awards = Table(
    "staff_awards",
    metadata,
    _id(),
    Column("staff_type_id", UUID(as_uuid=True), ForeignKey("app.staff_types.id"), nullable=False),
    Column("name", Text, nullable=False),
    Column("winners", SmallInteger, nullable=False, server_default="1"),
    Column("scope", Text, nullable=False, server_default="event"),
    Column("tiebreak_criterion_id", Text),
    Column("position", Integer, nullable=False, server_default="0"),
    Column("archived_at", DateTime(timezone=True)),
    *_timestamps(),
    schema="app",
)

staff_award_assignments = Table(
    "staff_award_assignments",
    metadata,
    _id(),
    Column("award_id", UUID(as_uuid=True), ForeignKey("app.staff_awards.id"), nullable=False),
    Column("event_id", UUID(as_uuid=True), ForeignKey("app.events.id"), nullable=False),
    Column("committee_id", UUID(as_uuid=True), ForeignKey("app.committees.id")),
    Column("position", SmallInteger, nullable=False),
    Column("candidate_id", UUID(as_uuid=True)),
    Column("suggested_candidate_id", UUID(as_uuid=True)),
    Column("override_reason", Text),
    Column("assigned_by", UUID(as_uuid=True)),
    Column("assigned_at", DateTime(timezone=True)),
    *_timestamps(),
    schema="app",
)

staff_award_confirmations = Table(
    "staff_award_confirmations",
    metadata,
    Column("staff_type_id", UUID(as_uuid=True), ForeignKey("app.staff_types.id"), primary_key=True),
    Column("event_id", UUID(as_uuid=True), ForeignKey("app.events.id"), primary_key=True),
    Column("confirmed_at", DateTime(timezone=True)),
    Column("confirmed_by", UUID(as_uuid=True)),
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
