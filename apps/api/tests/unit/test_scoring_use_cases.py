"""Casos de uso de `scoring` con adaptadores en memoria (sin base de datos)."""

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest

from munych_api.modules.scoring.application.get_progress import GetJudgeScores, GetProgress
from munych_api.modules.scoring.application.open_close_session import ManageSessions
from munych_api.modules.scoring.application.ports import (
    CommitteeInfo,
    ConcurrentWriteError,
    JudgeProgress,
    ProgressData,
)
from munych_api.modules.scoring.application.submit_scores import SubmitScores
from munych_api.modules.scoring.domain.models import (
    Score,
    ScoreKey,
    ScoreSubmission,
    ScoringSession,
    SessionContext,
)
from munych_api.shared.kernel import DomainError, ErrorCode

NOW = datetime(2026, 10, 10, 15, 0, tzinfo=UTC)
ORG = uuid.uuid4()
COMMITTEE = uuid.uuid4()
JUDGE = uuid.uuid4()
OTHER_JUDGE = uuid.uuid4()
DELEGATE = uuid.uuid4()
CRITERIA = [uuid.uuid4(), uuid.uuid4()]


class FixedClock:
    def __init__(self, now: datetime = NOW) -> None:
        self.current = now

    def now(self) -> datetime:
        return self.current


class InMemoryScoringRepository:
    def __init__(self) -> None:
        self.sessions: dict[UUID, ScoringSession] = {}
        self.scores: dict[UUID, Score] = {}
        self.assigned: set[tuple[UUID, UUID]] = {(JUDGE, COMMITTEE), (OTHER_JUDGE, COMMITTEE)}
        self.event_closed = False
        self.fail_next_write = False

    def add_session(self, number: int, status: str = "open") -> ScoringSession:
        session = ScoringSession(uuid.uuid4(), COMMITTEE, number, status, None, None)  # type: ignore[arg-type]
        self.sessions[session.id] = session
        return session

    async def session_context(self, session_id: UUID) -> SessionContext | None:
        session = self.sessions.get(session_id)
        if session is None:
            return None
        return SessionContext(
            session=session,
            event_closed=self.event_closed,
            scale_min=1,
            scale_max=4,
            criterion_ids=frozenset(CRITERIA),
            delegate_ids=frozenset({DELEGATE}),
        )

    async def is_assigned(self, judge_id: UUID, committee_id: UUID) -> bool:
        return (judge_id, committee_id) in self.assigned

    async def get_by_client_id(self, client_id: UUID) -> Score | None:
        return next((s for s in self.scores.values() if s.client_id == client_id), None)

    async def get_by_key(self, key: ScoreKey) -> Score | None:
        return next((s for s in self.scores.values() if s.key == key), None)

    def _check_failure(self) -> None:
        if self.fail_next_write:
            self.fail_next_write = False
            raise ConcurrentWriteError

    async def insert(self, item: ScoreSubmission) -> Score:
        self._check_failure()
        score = Score(
            uuid.uuid4(),
            item.client_id,
            item.judge_id,
            item.delegate_id,
            item.session_id,
            item.criterion_id,
            item.value,
            item.comment,
            item.client_updated_at,
        )
        self.scores[score.id] = score
        return score

    async def update(self, score_id: UUID, item: ScoreSubmission) -> Score:
        self._check_failure()
        score = replace(
            self.scores[score_id],
            client_id=item.client_id,
            value=item.value,
            comment=item.comment,
            client_updated_at=item.client_updated_at,
        )
        self.scores[score_id] = score
        return score

    async def judge_scores(self, judge_id: UUID, session_id: UUID) -> list[Score]:
        return [
            s for s in self.scores.values() if s.judge_id == judge_id and s.session_id == session_id
        ]

    async def get_session(self, session_id: UUID) -> ScoringSession | None:
        return self.sessions.get(session_id)

    async def get_committee(
        self, committee_id: UUID, organization_id: UUID
    ) -> CommitteeInfo | None:
        if committee_id != COMMITTEE or organization_id != ORG:
            return None
        return CommitteeInfo(COMMITTEE, self.event_closed)

    async def list_sessions(self, committee_id: UUID) -> list[ScoringSession]:
        return sorted(self.sessions.values(), key=lambda s: s.number)

    async def get_session_by_number(self, committee_id: UUID, number: int) -> ScoringSession | None:
        return next((s for s in self.sessions.values() if s.number == number), None)

    async def save_session(self, session: ScoringSession) -> None:
        self.sessions[session.id] = session

    async def progress(self, committee_id: UUID) -> ProgressData:
        counts: dict[UUID, dict[UUID, int]] = {JUDGE: {}, OTHER_JUDGE: {}}
        for s in self.scores.values():
            counts[s.judge_id][s.session_id] = counts[s.judge_id].get(s.session_id, 0) + 1
        return ProgressData(
            sessions=await self.list_sessions(committee_id),
            delegates_count=1,
            criteria_count=len(CRITERIA),
            judges=[
                JudgeProgress(JUDGE, "Laura", counts[JUDGE]),
                JudgeProgress(OTHER_JUDGE, "Carlos", counts[OTHER_JUDGE]),
            ],
        )


class RecordingAudit:
    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    async def record_score_change(self, **entry: Any) -> None:
        self.entries.append(entry)


@pytest.fixture
def repo() -> InMemoryScoringRepository:
    return InMemoryScoringRepository()


@pytest.fixture
def audit() -> RecordingAudit:
    return RecordingAudit()


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock()


@pytest.fixture
def submit(
    repo: InMemoryScoringRepository, audit: RecordingAudit, clock: FixedClock
) -> SubmitScores:
    return SubmitScores(repo, audit, clock)


def item(session: ScoringSession, **overrides: Any) -> ScoreSubmission:
    values: dict[str, Any] = {
        "client_id": uuid.uuid4(),
        "judge_id": JUDGE,
        "delegate_id": DELEGATE,
        "session_id": session.id,
        "criterion_id": CRITERIA[0],
        "value": 3,
        "comment": None,
        "client_updated_at": NOW - timedelta(minutes=5),
        **overrides,
    }
    return ScoreSubmission(**values)


# ---------------------------------------------------------------- validación por ítem


async def test_valid_item_is_inserted_and_audited(
    submit: SubmitScores, repo: InMemoryScoringRepository, audit: RecordingAudit
) -> None:
    session = repo.add_session(1)
    submission = item(session, comment="Buen discurso")
    result = await submit.execute([submission])
    assert result.accepted == [submission.client_id]
    assert result.rejected == []
    (stored,) = repo.scores.values()
    assert stored.value == 3
    assert audit.entries[0]["action"] == "create"
    assert audit.entries[0]["before"] is None
    assert audit.entries[0]["after"]["comment"] == "Buen discurso"


async def test_closed_session_is_rejected_without_affecting_other_items(
    submit: SubmitScores, repo: InMemoryScoringRepository
) -> None:
    open_session = repo.add_session(1)
    closed_session = repo.add_session(2, status="closed")
    good, bad = item(open_session), item(closed_session)
    result = await submit.execute([bad, good])
    assert result.accepted == [good.client_id]
    (rejected,) = result.rejected
    assert rejected.client_id == bad.client_id
    assert rejected.code == ErrorCode.SESSION_CLOSED
    assert rejected.detail == "La sesión 2 está cerrada"


async def test_judge_not_assigned(submit: SubmitScores, repo: InMemoryScoringRepository) -> None:
    session = repo.add_session(1)
    result = await submit.execute([item(session, judge_id=uuid.uuid4())])
    assert result.rejected[0].code == ErrorCode.JUDGE_NOT_ASSIGNED
    assert repo.scores == {}


@pytest.mark.parametrize("value", [0, 5, -1])
async def test_value_out_of_range(
    submit: SubmitScores, repo: InMemoryScoringRepository, value: int
) -> None:
    session = repo.add_session(1)
    result = await submit.execute([item(session, value=value)])
    assert result.rejected[0].code == ErrorCode.VALUE_OUT_OF_RANGE
    assert "1–4" in result.rejected[0].detail


async def test_event_closed(submit: SubmitScores, repo: InMemoryScoringRepository) -> None:
    session = repo.add_session(1)
    repo.event_closed = True
    result = await submit.execute([item(session)])
    assert result.rejected[0].code == ErrorCode.EVENT_CLOSED


@pytest.mark.parametrize(
    "overrides",
    [
        {"session_id": uuid.uuid4()},
        {"delegate_id": uuid.uuid4()},
        {"criterion_id": uuid.uuid4()},
    ],
    ids=["sesion", "delegado", "criterio"],
)
async def test_unknown_references_are_not_found(
    submit: SubmitScores, repo: InMemoryScoringRepository, overrides: dict[str, Any]
) -> None:
    session = repo.add_session(1)
    result = await submit.execute([item(session, **overrides)])
    assert result.rejected[0].code == ErrorCode.NOT_FOUND


# ---------------------------------------------------------------- idempotencia


async def test_same_batch_twice_is_idempotent(
    submit: SubmitScores, repo: InMemoryScoringRepository, audit: RecordingAudit
) -> None:
    session = repo.add_session(1)
    batch = [item(session, criterion_id=c) for c in CRITERIA]
    first = await submit.execute(batch)
    second = await submit.execute(batch)
    assert first.accepted == second.accepted == [i.client_id for i in batch]
    assert len(repo.scores) == 2
    assert len(audit.entries) == 2  # el reintento no genera auditoría


async def test_newer_write_updates_the_same_cell(
    submit: SubmitScores, repo: InMemoryScoringRepository, audit: RecordingAudit
) -> None:
    session = repo.add_session(1)
    original = item(session, value=2)
    await submit.execute([original])
    newer = item(session, value=4, client_updated_at=NOW - timedelta(minutes=1))
    result = await submit.execute([newer])
    assert result.accepted == [newer.client_id]
    (stored,) = repo.scores.values()
    assert (stored.value, stored.client_id) == (4, newer.client_id)
    assert audit.entries[-1]["action"] == "update"
    assert audit.entries[-1]["before"]["value"] == 2


async def test_older_write_is_ignored_last_write_wins(
    submit: SubmitScores, repo: InMemoryScoringRepository, audit: RecordingAudit
) -> None:
    session = repo.add_session(1)
    newer = item(session, value=4, client_updated_at=NOW - timedelta(minutes=1))
    await submit.execute([newer])
    older = item(session, value=1, client_updated_at=NOW - timedelta(minutes=10))
    result = await submit.execute([older])
    assert result.accepted == [older.client_id]  # se acepta sin cambios
    (stored,) = repo.scores.values()
    assert stored.value == 4
    assert len(audit.entries) == 1


async def test_retry_with_same_client_id_and_new_value_updates(
    submit: SubmitScores, repo: InMemoryScoringRepository
) -> None:
    session = repo.add_session(1)
    original = item(session, value=2)
    await submit.execute([original])
    edited = replace(original, value=3, client_updated_at=NOW)
    await submit.execute([edited])
    (stored,) = repo.scores.values()
    assert stored.value == 3


async def test_client_id_reused_for_another_cell_is_rejected(
    submit: SubmitScores, repo: InMemoryScoringRepository
) -> None:
    session = repo.add_session(1)
    original = item(session)
    await submit.execute([original])
    reused = replace(original, criterion_id=CRITERIA[1])
    result = await submit.execute([reused])
    assert result.rejected[0].code == ErrorCode.VALIDATION_ERROR


async def test_future_client_clock_is_clamped_to_server_time(
    submit: SubmitScores, repo: InMemoryScoringRepository, clock: FixedClock
) -> None:
    session = repo.add_session(1)
    await submit.execute([item(session, value=2, client_updated_at=NOW + timedelta(days=1))])
    (stored,) = repo.scores.values()
    assert stored.client_updated_at == NOW

    clock.current = NOW + timedelta(minutes=1)
    await submit.execute([item(session, value=4, client_updated_at=NOW + timedelta(minutes=1))])
    (stored,) = repo.scores.values()
    assert stored.value == 4


async def test_concurrent_write_is_rejected_as_conflict(
    submit: SubmitScores, repo: InMemoryScoringRepository
) -> None:
    session = repo.add_session(1)
    repo.fail_next_write = True
    result = await submit.execute([item(session)])
    assert result.rejected[0].code == ErrorCode.CONFLICT


# ---------------------------------------------------------------- lecturas del juez


async def test_judge_reads_only_own_scores(
    submit: SubmitScores, repo: InMemoryScoringRepository
) -> None:
    session = repo.add_session(1)
    await submit.execute([item(session), item(session, judge_id=OTHER_JUDGE)])
    scores = await GetJudgeScores(repo).execute(JUDGE, session.id)
    assert [s.judge_id for s in scores] == [JUDGE]

    with pytest.raises(DomainError) as exc:
        await GetJudgeScores(repo).execute(uuid.uuid4(), session.id)
    assert exc.value.code == ErrorCode.JUDGE_NOT_ASSIGNED
    with pytest.raises(DomainError) as exc:
        await GetJudgeScores(repo).execute(JUDGE, uuid.uuid4())
    assert exc.value.code == ErrorCode.NOT_FOUND


# ---------------------------------------------------------------- sesiones y avance


async def test_open_and_close_sessions(repo: InMemoryScoringRepository, clock: FixedClock) -> None:
    repo.add_session(1, status="closed")
    manage = ManageSessions(repo, clock)

    opened = await manage.open(ORG, COMMITTEE, 1)
    assert (opened.status, opened.opened_at, opened.closed_at) == ("open", NOW, None)
    assert await manage.open(ORG, COMMITTEE, 1) == opened

    clock.current = NOW + timedelta(hours=2)
    closed = await manage.close(ORG, COMMITTEE, 1)
    assert (closed.status, closed.closed_at) == ("closed", clock.current)
    assert await manage.close(ORG, COMMITTEE, 1) == closed
    assert [s.status for s in await manage.list(ORG, COMMITTEE)] == ["closed"]


async def test_session_errors(repo: InMemoryScoringRepository, clock: FixedClock) -> None:
    manage = ManageSessions(repo, clock)
    with pytest.raises(DomainError) as exc:
        await manage.open(ORG, COMMITTEE, 9)
    assert exc.value.code == ErrorCode.NOT_FOUND
    with pytest.raises(DomainError) as exc:
        await manage.list(uuid.uuid4(), COMMITTEE)
    assert exc.value.code == ErrorCode.NOT_FOUND

    repo.add_session(1)
    repo.event_closed = True
    with pytest.raises(DomainError) as exc:
        await manage.close(ORG, COMMITTEE, 1)
    assert exc.value.code == ErrorCode.EVENT_CLOSED


async def test_progress(submit: SubmitScores, repo: InMemoryScoringRepository) -> None:
    first = repo.add_session(1)
    repo.add_session(2, status="closed")
    await submit.execute([item(first)])

    progress = await GetProgress(repo).execute(ORG, COMMITTEE)
    assert [(p.number, p.status) for p in progress] == [(1, "open"), (2, "closed")]
    assert [(j.full_name, j.scored, j.expected) for j in progress[0].judges] == [
        ("Laura", 1, 2),
        ("Carlos", 0, 2),
    ]
    with pytest.raises(DomainError):
        await GetProgress(repo).execute(uuid.uuid4(), COMMITTEE)
