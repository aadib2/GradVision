"""Cross-cutting access control: which routes need a login, and that they all enforce it."""

import pytest

from app.main import app

# Every route must be listed in exactly one of these two sets. The completeness test
# below fails when someone adds an endpoint without deciding whether it is public.
PROTECTED = {
    ("GET", "/api/users/{id}"),
    ("PATCH", "/api/users/{id}"),
    ("DELETE", "/api/users/{id}"),
    ("GET", "/api/users/{id}/saved-programs/"),
    ("POST", "/api/users/{id}/saved-programs/"),
    ("DELETE", "/api/users/{id}/saved-programs/{program_id}"),
    ("GET", "/api/users/{user_id}/applications/"),
    ("POST", "/api/users/{user_id}/applications/"),
    ("PATCH", "/api/applications/{application_id}"),
    ("DELETE", "/api/applications/{application_id}"),
    ("GET", "/api/users/{user_id}/tasks/"),
    ("POST", "/api/users/{user_id}/tasks/"),
    ("GET", "/api/users/{user_id}/calendar/"),
    ("PATCH", "/api/tasks/{task_id}"),
    ("DELETE", "/api/tasks/{task_id}"),
}

PUBLIC = {
    ("GET", "/"),
    ("POST", "/api/users"),
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/token"),
    ("POST", "/api/auth/refresh"),
    ("POST", "/api/auth/logout"),
    ("GET", "/api/universities"),
    ("GET", "/api/program/{program_id}"),
    ("GET", "/api/professors/{id}/papers"),
    ("GET", "/api/papers"),
    ("GET", "/api/search/universities"),
    ("GET", "/api/search/professors"),
}


def concrete(path: str) -> str:
    """Turn '/api/users/{id}/x' into '/api/users/1/x'."""
    for name in ("user_id", "program_id", "application_id", "task_id", "id"):
        path = path.replace("{" + name + "}", "1")
    return path


# Routes declared with include_in_schema=False never appear in the OpenAPI schema,
# so the completeness test cannot discover them; list them here by hand.
HIDDEN_FROM_SCHEMA = {("POST", "/api/auth/token")}


def registered_routes() -> set[tuple[str, str]]:
    """Every (METHOD, path) the app serves, read from its public OpenAPI schema.

    (Walking app.routes is not reliable: include_router wraps routers in private,
    version-specific classes.)
    """
    http_methods = {"get", "post", "put", "patch", "delete"}
    return {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
        if method in http_methods
    }


def test_every_route_is_classified_as_public_or_protected():
    assert PROTECTED.isdisjoint(PUBLIC)
    assert registered_routes() | HIDDEN_FROM_SCHEMA == PROTECTED | PUBLIC


@pytest.mark.parametrize("method, path", sorted(PROTECTED))
class TestProtectedRoutes:
    def test_rejects_requests_without_a_token(self, client, method, path):
        response = client.request(method, concrete(path), json={})

        assert response.status_code == 401
        assert response.json() == {"success": False, "error": "Not authenticated"}

    def test_rejects_requests_with_a_bad_token(self, client, method, path):
        response = client.request(
            method,
            concrete(path),
            json={},
            headers={"Authorization": "Bearer not-a-real-token"},
        )

        assert response.status_code == 401
        assert response.json() == {"success": False, "error": "Could not validate credentials"}

    def test_rejects_a_refresh_token(self, client, user, method, path):
        response = client.request(
            method,
            concrete(path),
            json={},
            headers={"Authorization": f"Bearer {user.refresh_token}"},
        )

        assert response.status_code == 401


@pytest.mark.xfail(
    reason="The custom HTTPException handler in core/exceptions.py builds a bare "
    "JSONResponse and drops exc.headers, so the WWW-Authenticate: Bearer header "
    "set in deps.py never reaches the client (RFC 6750 expects it on a 401)",
    strict=True,
)
def test_401_includes_www_authenticate_header(client, user):
    response = client.get(
        f"/api/users/{user.user_id}", headers={"Authorization": "Bearer not-a-real-token"}
    )

    assert response.headers.get("www-authenticate") == "Bearer"


@pytest.mark.parametrize(
    "method, path",
    sorted(
        route
        for route in PUBLIC
        if route not in {("POST", "/api/users"), ("POST", "/api/auth/login"),
                         ("POST", "/api/auth/token"), ("POST", "/api/auth/refresh"),
                         ("POST", "/api/auth/logout"), ("GET", "/api/search/professors")}
    ),
)
def test_public_get_routes_work_without_a_token(client, method, path):
    response = client.request(method, concrete(path))

    # 200, or a 404 for "/api/program/1" and "/api/professors/1/papers" on an empty
    # database. Either way: not 401, because no login is required.
    assert response.status_code in {200, 404}


def test_public_search_professors_needs_no_token(client):
    response = client.get("/api/search/professors", params={"university_id": 1})

    assert response.status_code == 200
