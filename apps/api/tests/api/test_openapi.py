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
