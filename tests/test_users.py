"""User routes: signup, profile get/update/delete, and saved programs."""

import pytest
from sqlalchemy import select

from app.models.models import RefreshToken, SavedProgram, User

FORBIDDEN_PROFILE = {
    "success": False,
    "error": "You do not have permission to access this profile",
}

EDUCATION = {
    "university_name": "State University",
    "major": "Mathematics",
    "degree": "BSc",
    "year_started": 2020,
    "year_ended": 2024,
    "currently_attending": False,
}


def signup_payload(**overrides):
    return {
        "first_name": "Ada",
        "last_name": "Lovelace",
        "email": "ada@example.com",
        "password": "analytical-engine",
        **overrides,
    }


class TestSignup:
    def test_creates_user(self, client):
        response = client.post("/api/users", json=signup_payload())

        assert response.status_code == 201
        body = response.json()
        assert body["success"] is True
        assert body["user"]["email"] == "ada@example.com"
        assert body["user"]["first_name"] == "Ada"
        assert body["user"]["last_name"] == "Lovelace"
        assert body["user"]["user_id"] > 0
        assert body["user"]["past_education"] == []
        assert body["user"]["research_interests"] == []

    def test_response_never_contains_the_password(self, client):
        response = client.post("/api/users", json=signup_payload())

        assert "analytical-engine" not in response.text
        assert "password" not in response.json()["user"]
        assert "hashed_password" not in response.json()["user"]

    def test_password_is_stored_hashed(self, client, db_session):
        client.post("/api/users", json=signup_payload())

        stored = db_session.execute(select(User)).scalar_one()
        assert stored.hashed_password != "analytical-engine"
        assert stored.hashed_password.startswith("$2")  # bcrypt

    def test_saves_past_education(self, client):
        response = client.post("/api/users", json=signup_payload(past_education=[EDUCATION]))

        assert response.status_code == 201
        education = response.json()["user"]["past_education"]
        assert len(education) == 1
        assert education[0]["university_name"] == "State University"
        assert education[0]["education_id"] > 0

    def test_duplicate_email_is_rejected(self, client):
        client.post("/api/users", json=signup_payload())

        response = client.post("/api/users", json=signup_payload(first_name="Other"))

        assert response.status_code == 400
        assert response.json() == {"success": False, "error": "Email is already registered"}

    @pytest.mark.parametrize(
        "missing_field", ["first_name", "last_name", "email", "password"]
    )
    def test_missing_required_field(self, client, missing_field):
        payload = signup_payload()
        del payload[missing_field]

        response = client.post("/api/users", json=payload)

        assert response.status_code == 422
        assert response.json()["success"] is False
        assert missing_field in response.json()["error"]

    def test_invalid_email(self, client):
        response = client.post("/api/users", json=signup_payload(email="not-an-email"))

        assert response.status_code == 422


class TestGetUser:
    def test_returns_own_profile(self, client, user):
        response = client.get(f"/api/users/{user.user_id}", headers=user.headers)

        assert response.status_code == 200
        body = response.json()
        assert body["user_id"] == user.user_id
        assert body["email"] == user.email
        assert "hashed_password" not in body

    def test_other_users_profile_is_forbidden(self, client, user, other_user):
        response = client.get(f"/api/users/{other_user.user_id}", headers=user.headers)

        assert response.status_code == 403
        assert response.json() == FORBIDDEN_PROFILE


class TestUpdateUser:
    def test_partial_update_changes_only_sent_fields(self, client, user):
        response = client.patch(
            f"/api/users/{user.user_id}",
            headers=user.headers,
            json={"first_name": "Renamed"},
        )

        assert response.status_code == 200
        assert response.json() == {"success": True}
        profile = client.get(f"/api/users/{user.user_id}", headers=user.headers).json()
        assert profile["first_name"] == "Renamed"
        assert profile["last_name"] == "User1"
        assert profile["email"] == user.email

    def test_updates_list_and_text_fields(self, client, user):
        changes = {
            "research_interests": ["machine learning", "nlp"],
            "career_goals": ["professor"],
            "program_interests": ["PhD"],
            "personal_statement": "I like research.",
        }

        client.patch(f"/api/users/{user.user_id}", headers=user.headers, json=changes)

        profile = client.get(f"/api/users/{user.user_id}", headers=user.headers).json()
        for field, value in changes.items():
            assert profile[field] == value

    def test_can_change_email(self, client, user):
        response = client.patch(
            f"/api/users/{user.user_id}",
            headers=user.headers,
            json={"email": "new@example.com"},
        )

        assert response.status_code == 200
        login = client.post(
            "/api/auth/login",
            json={"email": "new@example.com", "password": user.password},
        )
        assert login.status_code == 200

    def test_cannot_take_another_users_email(self, client, user, other_user):
        response = client.patch(
            f"/api/users/{user.user_id}",
            headers=user.headers,
            json={"email": other_user.email},
        )

        assert response.status_code == 400
        assert response.json() == {"success": False, "error": "Email is already registered"}

    def test_resending_own_email_is_not_a_conflict(self, client, user):
        response = client.patch(
            f"/api/users/{user.user_id}",
            headers=user.headers,
            json={"email": user.email},
        )

        assert response.status_code == 200

    def test_changing_password_replaces_the_old_one(self, client, user):
        client.patch(
            f"/api/users/{user.user_id}",
            headers=user.headers,
            json={"password": "a-brand-new-password"},
        )

        old = client.post(
            "/api/auth/login", json={"email": user.email, "password": user.password}
        )
        new = client.post(
            "/api/auth/login",
            json={"email": user.email, "password": "a-brand-new-password"},
        )
        assert old.status_code == 401
        assert new.status_code == 200

    def test_past_education_is_replaced_not_appended(self, client, user):
        url = f"/api/users/{user.user_id}"
        client.patch(url, headers=user.headers, json={"past_education": [EDUCATION]})

        second = {**EDUCATION, "university_name": "Other College"}
        client.patch(url, headers=user.headers, json={"past_education": [second]})

        education = client.get(url, headers=user.headers).json()["past_education"]
        assert [e["university_name"] for e in education] == ["Other College"]

    def test_empty_past_education_clears_the_list(self, client, user):
        url = f"/api/users/{user.user_id}"
        client.patch(url, headers=user.headers, json={"past_education": [EDUCATION]})

        client.patch(url, headers=user.headers, json={"past_education": []})

        assert client.get(url, headers=user.headers).json()["past_education"] == []

    def test_omitting_past_education_keeps_it(self, client, user):
        url = f"/api/users/{user.user_id}"
        client.patch(url, headers=user.headers, json={"past_education": [EDUCATION]})

        client.patch(url, headers=user.headers, json={"first_name": "Renamed"})

        assert len(client.get(url, headers=user.headers).json()["past_education"]) == 1

    def test_cannot_update_another_user(self, client, user, other_user):
        response = client.patch(
            f"/api/users/{other_user.user_id}",
            headers=user.headers,
            json={"first_name": "Hacked"},
        )

        assert response.status_code == 403
        assert response.json() == FORBIDDEN_PROFILE
        untouched = client.get(
            f"/api/users/{other_user.user_id}", headers=other_user.headers
        ).json()
        assert untouched["first_name"] == "Test"

    def test_invalid_email_is_rejected(self, client, user):
        response = client.patch(
            f"/api/users/{user.user_id}",
            headers=user.headers,
            json={"email": "not-an-email"},
        )

        assert response.status_code == 422

    @pytest.mark.parametrize(
        "field",
        [
            "first_name",
            "last_name",
            "email",
            "research_interests",
            "career_goals",
            "program_interests",
        ],
    )
    def test_null_for_required_field_is_rejected(self, client, user, field):
        url = f"/api/users/{user.user_id}"
        before = client.get(url, headers=user.headers).json()

        response = client.patch(url, headers=user.headers, json={field: None})

        assert response.status_code == 422
        assert response.json()["success"] is False
        assert f"{field} cannot be null" in response.json()["error"]
        assert client.get(url, headers=user.headers).json() == before  # nothing changed

    def test_all_null_fields_are_reported_together(self, client, user):
        response = client.patch(
            f"/api/users/{user.user_id}",
            headers=user.headers,
            json={"first_name": None, "last_name": None},
        )

        assert response.status_code == 422
        assert "first_name, last_name cannot be null" in response.json()["error"]

    def test_personal_statement_can_be_cleared_with_null(self, client, user):
        url = f"/api/users/{user.user_id}"
        client.patch(url, headers=user.headers, json={"personal_statement": "Hello"})

        response = client.patch(url, headers=user.headers, json={"personal_statement": None})

        assert response.status_code == 200
        assert client.get(url, headers=user.headers).json()["personal_statement"] is None

    def test_null_password_and_past_education_are_ignored(self, client, user):
        url = f"/api/users/{user.user_id}"
        client.patch(url, headers=user.headers, json={"past_education": [EDUCATION]})

        response = client.patch(
            url, headers=user.headers, json={"password": None, "past_education": None}
        )

        assert response.status_code == 200
        assert len(client.get(url, headers=user.headers).json()["past_education"]) == 1
        login = client.post(
            "/api/auth/login", json={"email": user.email, "password": user.password}
        )
        assert login.status_code == 200  # password unchanged


class TestDeleteUser:
    def test_deletes_account(self, client, user):
        response = client.delete(f"/api/users/{user.user_id}", headers=user.headers)

        assert response.status_code == 200
        assert response.json() == {"success": True}

    def test_deleted_users_token_stops_working(self, client, user):
        client.delete(f"/api/users/{user.user_id}", headers=user.headers)

        response = client.get(f"/api/users/{user.user_id}", headers=user.headers)

        assert response.status_code == 401

    def test_deleted_user_cannot_log_in(self, client, user):
        client.delete(f"/api/users/{user.user_id}", headers=user.headers)

        login = client.post(
            "/api/auth/login", json={"email": user.email, "password": user.password}
        )

        assert login.status_code == 401

    def test_deleting_cascades_to_user_owned_rows(
        self, client, db_session, user, seeded_catalog
    ):
        program_id = seeded_catalog["ai_masters"].program_id
        client.post(
            f"/api/users/{user.user_id}/saved-programs/",
            headers=user.headers,
            json={"program_id": program_id},
        )
        assert db_session.execute(select(RefreshToken)).first() is not None
        assert db_session.execute(select(SavedProgram)).first() is not None

        client.delete(f"/api/users/{user.user_id}", headers=user.headers)

        db_session.expire_all()
        assert db_session.execute(select(User)).first() is None
        assert db_session.execute(select(RefreshToken)).first() is None
        assert db_session.execute(select(SavedProgram)).first() is None

    def test_cannot_delete_another_user(self, client, user, other_user):
        response = client.delete(f"/api/users/{other_user.user_id}", headers=user.headers)

        assert response.status_code == 403
        assert response.json() == FORBIDDEN_PROFILE
        still_there = client.get(
            f"/api/users/{other_user.user_id}", headers=other_user.headers
        )
        assert still_there.status_code == 200


class TestSavedPrograms:
    @staticmethod
    def url(user_id, program_id=None):
        base = f"/api/users/{user_id}/saved-programs/"
        return base if program_id is None else f"{base}{program_id}"

    def test_starts_empty(self, client, user):
        response = client.get(self.url(user.user_id), headers=user.headers)

        assert response.status_code == 200
        assert response.json() == []

    def test_save_then_list(self, client, user, seeded_catalog):
        program = seeded_catalog["ai_masters"]

        saved = client.post(
            self.url(user.user_id),
            headers=user.headers,
            json={"program_id": program.program_id},
        )
        listed = client.get(self.url(user.user_id), headers=user.headers)

        assert saved.status_code == 201
        assert saved.json() == {"success": True}
        assert listed.json() == [
            {
                "program_id": program.program_id,
                "program_name": "AI Masters",
                "degree_type": "Masters",
                "university_name": "Tech Institute",
                "program_start": 2027,
                "program_end": 2029,
            }
        ]

    def test_saving_twice_is_rejected(self, client, user, seeded_catalog):
        body = {"program_id": seeded_catalog["ai_masters"].program_id}
        client.post(self.url(user.user_id), headers=user.headers, json=body)

        response = client.post(self.url(user.user_id), headers=user.headers, json=body)

        assert response.status_code == 400
        assert response.json() == {"success": False, "error": "Program is already saved"}

    def test_saving_unknown_program(self, client, user):
        response = client.post(
            self.url(user.user_id), headers=user.headers, json={"program_id": 999}
        )

        assert response.status_code == 404
        assert response.json() == {"success": False, "error": "Program not found"}

    def test_missing_program_id(self, client, user):
        response = client.post(self.url(user.user_id), headers=user.headers, json={})

        assert response.status_code == 422

    def test_unsave(self, client, user, seeded_catalog):
        program_id = seeded_catalog["ai_masters"].program_id
        client.post(
            self.url(user.user_id), headers=user.headers, json={"program_id": program_id}
        )

        deleted = client.delete(self.url(user.user_id, program_id), headers=user.headers)
        listed = client.get(self.url(user.user_id), headers=user.headers)

        assert deleted.status_code == 200
        assert listed.json() == []

    def test_unsaving_something_not_saved(self, client, user, seeded_catalog):
        program_id = seeded_catalog["ai_masters"].program_id

        response = client.delete(self.url(user.user_id, program_id), headers=user.headers)

        assert response.status_code == 404
        assert response.json() == {"success": False, "error": "Saved program not found"}

    def test_saved_programs_are_per_user(self, client, user, other_user, seeded_catalog):
        client.post(
            self.url(user.user_id),
            headers=user.headers,
            json={"program_id": seeded_catalog["ai_masters"].program_id},
        )

        theirs = client.get(self.url(other_user.user_id), headers=other_user.headers)

        assert theirs.json() == []

    def test_cannot_touch_another_users_saved_programs(
        self, client, user, other_user, seeded_catalog
    ):
        program_id = seeded_catalog["ai_masters"].program_id
        headers = user.headers
        target = other_user.user_id

        responses = [
            client.get(self.url(target), headers=headers),
            client.post(self.url(target), headers=headers, json={"program_id": program_id}),
            client.delete(self.url(target, program_id), headers=headers),
        ]

        assert [r.status_code for r in responses] == [403, 403, 403]
        assert all(r.json() == FORBIDDEN_PROFILE for r in responses)
