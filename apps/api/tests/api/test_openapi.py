"""Contrato OpenAPI: rutas y `operation_id` estables (el frontend genera su cliente con Orval).

Si cambias esta lista, actualiza el ADR 0001 («Cambios al contrato») y avisa al frontend.
"""

from fastapi import FastAPI

EXPECTED_OPERATIONS = {
    ("GET", "/api/v1/health"): "health",
    ("GET", "/api/v1/me"): "get_me",
    ("GET", "/api/v1/judges"): "list_judges",
    ("POST", "/api/v1/judges"): "invite_judge",
    ("PATCH", "/api/v1/judges/{judge_id}"): "update_judge",
    ("GET", "/api/v1/judges/invitations"): "list_judge_invitations",
    ("POST", "/api/v1/judges/{judge_id}/invitation"): "resend_judge_invitation",
    ("GET", "/api/v1/events"): "list_events",
    ("POST", "/api/v1/events"): "create_event",
    ("GET", "/api/v1/events/{event_id}"): "get_event",
    ("PATCH", "/api/v1/events/{event_id}"): "update_event",
    ("DELETE", "/api/v1/events/{event_id}"): "delete_event",
    ("POST", "/api/v1/events/{event_id}/logo"): "upload_event_logo",
    ("POST", "/api/v1/events/{event_id}/close"): "close_event",
    ("GET", "/api/v1/events/{event_id}/committees"): "list_committees",
    ("POST", "/api/v1/events/{event_id}/committees"): "create_committee",
    ("GET", "/api/v1/committees/{committee_id}"): "get_committee",
    ("PATCH", "/api/v1/committees/{committee_id}"): "update_committee",
    ("DELETE", "/api/v1/committees/{committee_id}"): "delete_committee",
    ("GET", "/api/v1/committees/{committee_id}/delegations"): "list_delegations",
    ("POST", "/api/v1/committees/{committee_id}/delegations"): "create_delegation",
    ("POST", "/api/v1/committees/{committee_id}/delegations/import"): "import_delegations",
    ("PATCH", "/api/v1/delegations/{delegation_id}"): "update_delegation",
    ("DELETE", "/api/v1/delegations/{delegation_id}"): "delete_delegation",
    ("POST", "/api/v1/delegations/{delegation_id}/delegates"): "add_delegate",
    ("PATCH", "/api/v1/delegates/{delegate_id}"): "update_delegate",
    ("DELETE", "/api/v1/delegates/{delegate_id}"): "delete_delegate",
    ("GET", "/api/v1/committees/{committee_id}/judges"): "list_committee_judges",
    ("PUT", "/api/v1/committees/{committee_id}/judges"): "replace_committee_judges",
    ("GET", "/api/v1/events/{event_id}/rubrics"): "list_event_rubrics",
    ("POST", "/api/v1/events/{event_id}/rubrics"): "create_rubric",
    ("GET", "/api/v1/rubrics/{rubric_id}"): "get_rubric",
    ("PUT", "/api/v1/rubrics/{rubric_id}"): "replace_rubric",
    ("GET", "/api/v1/committees/{committee_id}/sessions"): "list_committee_sessions",
    ("POST", "/api/v1/committees/{committee_id}/sessions/{number}/open"): "open_session",
    ("POST", "/api/v1/committees/{committee_id}/sessions/{number}/close"): "close_session",
    ("GET", "/api/v1/committees/{committee_id}/progress"): "get_committee_progress",
    ("GET", "/api/v1/committees/{committee_id}/ranking"): "get_committee_ranking",
    ("GET", "/api/v1/committees/{committee_id}/awards"): "list_committee_awards",
    ("PUT", "/api/v1/committees/{committee_id}/awards"): "replace_committee_awards",
    ("GET", "/api/v1/events/{event_id}/export.xlsx"): "export_event_xlsx",
    ("GET", "/api/v1/events/{event_id}/publication-settings"): "get_publication_settings",
    ("PUT", "/api/v1/events/{event_id}/publication-settings"): "update_publication_settings",
    ("GET", "/api/v1/events/{event_id}/publication/preview"): "preview_publication",
    ("POST", "/api/v1/events/{event_id}/publish"): "publish_event",
    ("POST", "/api/v1/events/{event_id}/unpublish"): "unpublish_event",
    ("GET", "/api/v1/judge/committees"): "list_judge_committees",
    ("GET", "/api/v1/judge/committees/{committee_id}"): "get_judge_committee",
    ("GET", "/api/v1/judge/sessions/{session_id}/scores"): "list_my_session_scores",
    ("POST", "/api/v1/judge/scores/batch"): "submit_scores_batch",
    # Votación de delegados (ADR-005, 2026-11-05).
    ("GET", "/api/v1/events/{event_id}/voter-tokens"): "list_voter_tokens",
    ("POST", "/api/v1/events/{event_id}/voter-tokens"): "generate_voter_tokens",
    ("POST", "/api/v1/events/{event_id}/voter-tokens/revoke"): "revoke_voter_tokens",
    ("GET", "/api/v1/vote/ballot"): "get_ballot",
    # Voto entre pares por premios (2026-11-06).
    ("POST", "/api/v1/vote/ballot"): "submit_peer_vote",
    ("GET", "/api/v1/events/{event_id}/peer-vote"): "list_peer_vote_windows",
    ("PUT", "/api/v1/committees/{committee_id}/peer-vote"): "open_peer_vote",
    ("POST", "/api/v1/committees/{committee_id}/peer-vote/close"): "close_peer_vote",
    # Exportación en CSV y desempate manual (2026-11-07).
    ("GET", "/api/v1/events/{event_id}/export.csv"): "export_event_csv",
    ("PUT", "/api/v1/committees/{committee_id}/tiebreak"): "set_committee_tiebreak",
    ("GET", "/api/v1/events/{event_id}/export.pdf"): "export_event_pdf",
    ("POST", "/api/v1/events/{event_id}/voter-tokens/sheet.pdf"): "voter_access_sheet",
    # Gestión de staff (2026-11-08): de la organización; el evento va como ?event_id=.
    ("GET", "/api/v1/staff"): "staff_overview",
    ("POST", "/api/v1/staff-types"): "create_staff_type",
    ("GET", "/api/v1/staff-types/{type_id}"): "get_staff_type",
    ("PATCH", "/api/v1/staff-types/{type_id}"): "update_staff_type",
    ("PUT", "/api/v1/staff-types/{type_id}/rubric"): "put_staff_rubric",
    ("GET", "/api/v1/staff-people"): "list_staff_people",
    ("POST", "/api/v1/staff-types/{type_id}/members"): "add_staff_member",
    ("PATCH", "/api/v1/staff-members/{member_id}"): "update_staff_member",
    ("POST", "/api/v1/staff-members/{member_id}/remove"): "remove_staff_member",
    ("PATCH", "/api/v1/staff-people/{person_id}"): "update_staff_person",
    ("POST", "/api/v1/staff-people/{person_id}/link"): "issue_staff_link",
    ("GET", "/api/v1/staff-types/{type_id}/ranking"): "staff_ranking",
    ("POST", "/api/v1/staff-types/{type_id}/awards"): "add_staff_award",
    ("PATCH", "/api/v1/staff-awards/{award_id}"): "update_staff_award",
    ("PUT", "/api/v1/staff-awards/{award_id}/assignment"): "assign_staff_award",
    ("POST", "/api/v1/staff-types/{type_id}/awards/confirm"): "confirm_staff_awards",
    ("GET", "/api/v1/staff/me"): "staff_me",
    # Personas del staff por evento e invitación con rol (2026-11-08).
    ("GET", "/api/v1/events/{event_id}/staff-members"): "list_event_staff",
    ("POST", "/api/v1/events/{event_id}/invitations"): "invite_to_event",
    ("POST", "/api/v1/staff-members/{member_id}/access"): "resend_staff_access",
    ("GET", "/api/v1/staff/qr/{token}.png"): "staff_qr",
    ("PUT", "/api/v1/staff/evaluations"): "save_staff_evaluation",
}


def test_operation_ids_are_stable(app: FastAPI) -> None:
    spec = app.openapi()
    actual = {
        (method.upper(), path): operation["operationId"]
        for path, operations in spec["paths"].items()
        for method, operation in operations.items()
    }
    assert actual == EXPECTED_OPERATIONS


def test_paths_use_api_prefix(app: FastAPI) -> None:
    spec = app.openapi()
    assert spec["info"]["title"] == "MUNYCH — API de calificaciones"
    for path, operations in spec["paths"].items():
        assert path.startswith("/api/v1/")
        for operation in operations.values():
            assert operation["operationId"].isidentifier()
