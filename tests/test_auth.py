"""Authentication: login, token refresh/rotation, logout, and access-token validation."""

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from sqlalchemy import select

from app.core.security import JWT_ALGORITHM, JWT_SECRET_KEY, hash_refresh_token
from app.models.models import RefreshToken

BAD_LOGIN = {"success": False, "error": "Incorrect email or password"}
BAD_REFRESH = {"success": False, "error": "Invalid or expired refresh token"}
BAD_CREDENTIALS = {"success": False, "error": "Could not validate credentials"}


def make_jwt(payload, key=JWT_SECRET_KEY, algorithm=JWT_ALGORITHM):
    return jwt.encode(payload, key, algorithm=algorithm)


def in_minutes(minutes):
    return datetime.now(timezone.utc) + timedelta(minutes=minutes)


def login(client, user):
    response = client.post(
        "/api/auth/login", json={"email": user.email, "password": user.password}
    )
    assert response.status_code == 200
    return response.json()


def refresh(client, token):
    return client.post("/api/auth/refresh", json={"refresh_token": token})


def logout(client, token):
    return client.post("/api/auth/logout", json={"refresh_token": token})


class TestLogin:
    def test_success_returns_both_tokens(self, client, user):
        response = client.post(
            "/api/auth/login", json={"email": user.email, "password": user.password}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["token_type"] == "bearer"
        assert body["access_token"]
        assert body["refresh_token"]

    def test_tokens_carry_the_user_id_and_correct_type(self, client, user):
        body = login(client, user)

        access = jwt.decode(body["access_token"], JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        refresh_payload = jwt.decode(
            body["refresh_token"], JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM]
        )
        assert access["sub"] == str(user.user_id)
        assert access["type"] == "access"
        assert refresh_payload["sub"] == str(user.user_id)
        assert refresh_payload["type"] == "refresh"
        assert refresh_payload["jti"]

    def test_access_token_expires_in_about_30_minutes(self, client, user):
        body = login(client, user)

        payload = jwt.decode(body["access_token"], JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        lifetime = datetime.fromtimestamp(payload["exp"], timezone.utc) - datetime.now(
            timezone.utc
        )
        assert timedelta(minutes=29) < lifetime <= timedelta(minutes=30)

    def test_refresh_token_is_stored_hashed_never_raw(self, client, db_session, user):
        refresh_token = login(client, user)["refresh_token"]

        rows = db_session.execute(select(RefreshToken)).scalars().all()
        assert refresh_token not in {row.token_hash for row in rows}
        assert hash_refresh_token(refresh_token) in {row.token_hash for row in rows}

    def test_wrong_password(self, client, user):
        response = client.post(
            "/api/auth/login", json={"email": user.email, "password": "wrong"}
        )

        assert response.status_code == 401
        assert response.json() == BAD_LOGIN

    def test_unknown_email_gives_the_same_error_as_wrong_password(self, client, user):
        response = client.post(
            "/api/auth/login",
            json={"email": "nobody@example.com", "password": user.password},
        )

        # Identical message, so the API doesn't reveal which emails are registered.
        assert response.status_code == 401
        assert response.json() == BAD_LOGIN

    @pytest.mark.parametrize(
        "payload",
        [
            {"email": "not-an-email", "password": "x"},
            {"email": "a@example.com"},
            {"password": "x"},
            {},
        ],
    )
    def test_invalid_body(self, client, payload):
        response = client.post("/api/auth/login", json=payload)

        assert response.status_code == 422
        assert response.json()["success"] is False


class TestFormLogin:
    """POST /api/auth/token is what the Swagger 'Authorize' button calls."""

    def test_success_with_email_as_username(self, client, user):
        response = client.post(
            "/api/auth/token", data={"username": user.email, "password": user.password}
        )

        assert response.status_code == 200
        assert response.json()["token_type"] == "bearer"

    def test_the_token_it_returns_works(self, client, user):
        token = client.post(
            "/api/auth/token", data={"username": user.email, "password": user.password}
        ).json()["access_token"]

        response = client.get(
            f"/api/users/{user.user_id}", headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200

    def test_wrong_password(self, client, user):
        response = client.post(
            "/api/auth/token", data={"username": user.email, "password": "wrong"}
        )

        assert response.status_code == 401
        assert response.json() == BAD_LOGIN


class TestRefresh:
    def test_returns_a_new_working_token_pair(self, client, user):
        response = refresh(client, user.refresh_token)

        assert response.status_code == 200
        body = response.json()
        assert body["refresh_token"] != user.refresh_token
        profile = client.get(
            f"/api/users/{user.user_id}",
            headers={"Authorization": f"Bearer {body['access_token']}"},
        )
        assert profile.status_code == 200

    def test_old_refresh_token_cannot_be_reused(self, client, user):
        refresh(client, user.refresh_token)

        reused = refresh(client, user.refresh_token)

        assert reused.status_code == 401
        assert reused.json() == BAD_REFRESH

    def test_new_refresh_token_can_be_used_again(self, client, user):
        first = refresh(client, user.refresh_token).json()

        second = refresh(client, first["refresh_token"])

        assert second.status_code == 200

    def test_rotation_revokes_old_row_and_adds_a_new_one(self, client, db_session, user):
        refresh(client, user.refresh_token)

        db_session.expire_all()
        rows = db_session.execute(select(RefreshToken)).scalars().all()
        assert len(rows) == 2
        assert sum(1 for row in rows if row.revoked_at is not None) == 1

    def test_garbage_token(self, client):
        response = refresh(client, "not-a-jwt")

        assert response.status_code == 401
        assert response.json() == BAD_REFRESH

    def test_missing_body_field(self, client):
        assert client.post("/api/auth/refresh", json={}).status_code == 422

    def test_access_token_cannot_be_used_as_a_refresh_token(self, client, user):
        response = refresh(client, user.access_token)

        assert response.status_code == 401
        assert response.json() == BAD_REFRESH

    def test_token_signed_with_the_wrong_key(self, client, user):
        forged = make_jwt(
            {"sub": str(user.user_id), "jti": "x", "type": "refresh", "exp": in_minutes(60)},
            key="a-different-secret-key-that-is-long-enough-123",
        )

        assert refresh(client, forged).status_code == 401

    def test_correctly_signed_but_never_issued_token(self, client, user):
        # Valid signature, valid claims -- but it was never stored in the database.
        forged = make_jwt(
            {"sub": str(user.user_id), "jti": "made-up", "type": "refresh", "exp": in_minutes(60)}
        )

        response = refresh(client, forged)

        assert response.status_code == 401
        assert response.json() == BAD_REFRESH

    def test_jwt_that_is_expired(self, client, user):
        expired = make_jwt(
            {"sub": str(user.user_id), "jti": "x", "type": "refresh", "exp": in_minutes(-5)}
        )

        assert refresh(client, expired).status_code == 401

    def test_stored_token_past_its_database_expiry(self, client, db_session, user):
        # The JWT itself is still valid; only the stored row says it is expired.
        row = db_session.execute(select(RefreshToken)).scalar_one()
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db_session.commit()

        response = refresh(client, user.refresh_token)

        assert response.status_code == 401
        assert response.json() == BAD_REFRESH

    def test_revoked_token(self, client, user):
        logout(client, user.refresh_token)

        response = refresh(client, user.refresh_token)

        assert response.status_code == 401
        assert response.json() == BAD_REFRESH

    def test_user_deleted_after_login(self, client, user):
        client.delete(f"/api/users/{user.user_id}", headers=user.headers)

        response = refresh(client, user.refresh_token)

        assert response.status_code == 401
        assert response.json() == BAD_REFRESH

    def test_one_users_token_cannot_refresh_as_another(self, client, user, other_user):
        # Each token's identity comes from the signed token, not from the request body.
        body = refresh(client, user.refresh_token).json()
        profile = client.get(
            f"/api/users/{other_user.user_id}",
            headers={"Authorization": f"Bearer {body['access_token']}"},
        )

        assert profile.status_code == 403


class TestLogout:
    def test_revokes_the_refresh_token(self, client, db_session, user):
        response = logout(client, user.refresh_token)

        assert response.status_code == 200
        assert response.json() == {"success": True}
        db_session.expire_all()
        row = db_session.execute(select(RefreshToken)).scalar_one()
        assert row.revoked_at is not None

    def test_unknown_token_still_succeeds(self, client):
        response = logout(client, "never-issued")

        assert response.status_code == 200
        assert response.json() == {"success": True}

    def test_logging_out_twice_is_fine(self, client, user):
        logout(client, user.refresh_token)

        assert logout(client, user.refresh_token).status_code == 200

    def test_only_logs_out_the_given_session(self, client, user):
        second_session = login(client, user)

        logout(client, user.refresh_token)

        assert refresh(client, second_session["refresh_token"]).status_code == 200

    def test_access_token_stays_valid_until_it_expires(self, client, user):
        # Access tokens are stateless JWTs, so logout cannot recall them.
        logout(client, user.refresh_token)

        response = client.get(f"/api/users/{user.user_id}", headers=user.headers)

        assert response.status_code == 200

    def test_missing_body_field(self, client):
        assert client.post("/api/auth/logout", json={}).status_code == 422


class TestAccessTokenValidation:
    """What get_current_user accepts, exercised through GET /api/users/{id}."""

    @staticmethod
    def call(client, user, token=None, scheme="Bearer"):
        headers = {} if token is None else {"Authorization": f"{scheme} {token}"}
        return client.get(f"/api/users/{user.user_id}", headers=headers)

    def test_valid_token(self, client, user):
        assert self.call(client, user, user.access_token).status_code == 200

    def test_no_token(self, client, user):
        response = self.call(client, user)

        assert response.status_code == 401
        assert response.json() == {"success": False, "error": "Not authenticated"}

    def test_wrong_auth_scheme(self, client, user):
        response = self.call(client, user, user.access_token, scheme="Basic")

        assert response.status_code == 401

    def test_garbage_token(self, client, user):
        response = self.call(client, user, "not-a-jwt")

        assert response.status_code == 401
        assert response.json() == BAD_CREDENTIALS

    def test_expired_token(self, client, user):
        expired = make_jwt({"sub": str(user.user_id), "type": "access", "exp": in_minutes(-1)})

        response = self.call(client, user, expired)

        assert response.status_code == 401
        assert response.json() == BAD_CREDENTIALS

    def test_refresh_token_is_not_accepted_as_an_access_token(self, client, user):
        response = self.call(client, user, user.refresh_token)

        assert response.status_code == 401
        assert response.json() == BAD_CREDENTIALS

    def test_wrong_signing_key(self, client, user):
        forged = make_jwt(
            {"sub": str(user.user_id), "type": "access", "exp": in_minutes(30)},
            key="a-different-secret-key-that-is-long-enough-123",
        )

        assert self.call(client, user, forged).status_code == 401

    def test_unsigned_token_with_alg_none(self, client, user):
        unsigned = jwt.encode(
            {"sub": str(user.user_id), "type": "access", "exp": in_minutes(30)},
            key=None,
            algorithm="none",
        )

        assert self.call(client, user, unsigned).status_code == 401

    def test_token_without_a_type_claim(self, client, user):
        token = make_jwt({"sub": str(user.user_id), "exp": in_minutes(30)})

        assert self.call(client, user, token).status_code == 401

    @pytest.mark.parametrize("sub", ["abc", "", None])
    def test_unusable_subject(self, client, user, sub):
        payload = {"type": "access", "exp": in_minutes(30)}
        if sub is not None:
            payload["sub"] = sub

        assert self.call(client, user, make_jwt(payload)).status_code == 401

    def test_token_for_a_user_that_does_not_exist(self, client, user):
        token = make_jwt({"sub": "99999", "type": "access", "exp": in_minutes(30)})

        response = self.call(client, user, token)

        assert response.status_code == 401
        assert response.json() == BAD_CREDENTIALS
