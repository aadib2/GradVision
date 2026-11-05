"""Application routes: track the programs a user is applying to."""

import pytest

NOT_YOUR_APPLICATIONS = {
    "success": False,
    "error": "You can only access your own applications",
}


@pytest.fixture
def program_id(seeded_catalog):
    return seeded_catalog["ai_masters"].program_id


def collection_url(user_id):
    return f"/api/users/{user_id}/applications/"


def create_application(client, user, program_id):
    response = client.post(
        collection_url(user.user_id), headers=user.headers, json={"program_id": program_id}
    )
    assert response.status_code == 201, response.text
    return response.json()["application"]


class TestCreateApplication:
    def test_creates_with_defaults(self, client, user, program_id):
        response = client.post(
            collection_url(user.user_id), headers=user.headers, json={"program_id": program_id}
        )

        assert response.status_code == 201
        body = response.json()
        assert body["success"] is True
        application = body["application"]
        assert application["application_id"] > 0
        assert application["user_id"] == user.user_id
        assert application["program_id"] == program_id
        assert application["program_name"] == "AI Masters"
        assert application["university_name"] == "Tech Institute"
        assert application["status"] == "not started"
        assert application["notes"] is None
        for checklist_item in (
            "transcripts_done",
            "recommendations_done",
            "statement_done",
            "test_scores_done",
        ):
            assert application[checklist_item] is False

    # call create_application (POST /api/user/{user_id}/applications) and then run the request again
    def test_same_program_twice_is_rejected(self, client, user, program_id):
        create_application(client, user, program_id)

        response = client.post(
            collection_url(user.user_id), headers=user.headers, json={"program_id": program_id}
        )

        assert response.status_code == 400
        assert response.json() == {
            "success": False,
            "error": "You have already added this program to your applications",
        }

    # verify when an application is created under two different users (ids), that the other application was created successfully
    def test_two_users_can_apply_to_the_same_program(
        self, client, user, other_user, program_id
    ):
        create_application(client, user, program_id)

        other = create_application(client, other_user, program_id)

        assert other["user_id"] == other_user.user_id

    def test_unknown_program(self, client, user):
        response = client.post(
            collection_url(user.user_id), headers=user.headers, json={"program_id": 999}
        )

        assert response.status_code == 404
        assert response.json() == {"success": False, "error": "Program not found"}

    @pytest.mark.parametrize("body", [{}, {"program_id": "abc"}])
    def test_invalid_body(self, client, user, body):
        response = client.post(collection_url(user.user_id), headers=user.headers, json=body)

        assert response.status_code == 422

    def test_cannot_create_for_another_user(self, client, user, other_user, program_id):
        response = client.post(
            collection_url(other_user.user_id),
            headers=user.headers,
            json={"program_id": program_id},
        )

        assert response.status_code == 403
        assert response.json() == NOT_YOUR_APPLICATIONS
        assert client.get(
            collection_url(other_user.user_id), headers=other_user.headers
        ).json() == []


class TestListApplications:
    def test_starts_empty(self, client, user):
        response = client.get(collection_url(user.user_id), headers=user.headers)

        assert response.status_code == 200
        assert response.json() == []

    def test_lists_only_own_applications(
        self, client, user, other_user, seeded_catalog
    ):
        create_application(client, user, seeded_catalog["ai_masters"].program_id)
        create_application(client, user, seeded_catalog["cs_phd"].program_id)
        create_application(client, other_user, seeded_catalog["bio_masters"].program_id)

        mine = client.get(collection_url(user.user_id), headers=user.headers).json()
        theirs = client.get(
            collection_url(other_user.user_id), headers=other_user.headers
        ).json()

        assert {a["program_name"] for a in mine} == {"AI Masters", "CS PhD"}
        assert [a["program_name"] for a in theirs] == ["Bioinformatics Masters"]

    def test_cannot_list_another_users_applications(self, client, user, other_user):
        response = client.get(collection_url(other_user.user_id), headers=user.headers)

        assert response.status_code == 403
        assert response.json() == NOT_YOUR_APPLICATIONS


class TestUpdateApplication:
    def test_updates_status_checklist_and_notes(self, client, user, program_id):
        application = create_application(client, user, program_id)

        response = client.patch(
            f"/api/applications/{application['application_id']}",
            headers=user.headers,
            json={
                "status": "in progress",
                "transcripts_done": True,
                "notes": "Email the department.",
            },
        )

        assert response.status_code == 200
        assert response.json() == {"success": True}
        updated = client.get(collection_url(user.user_id), headers=user.headers).json()[0]
        assert updated["status"] == "in progress"
        assert updated["transcripts_done"] is True
        assert updated["notes"] == "Email the department."
        assert updated["statement_done"] is False  # untouched

    # Note: pytest.mark.parametrize runs one body across many inputs
    # in this case, we run all possible status values through the function
    @pytest.mark.parametrize(
        "status", ["not started", "in progress", "submitted", "accepted", "rejected"]
    )
    def test_every_status_value_is_accepted(self, client, user, program_id, status):
        application = create_application(client, user, program_id)

        response = client.patch(
            f"/api/applications/{application['application_id']}",
            headers=user.headers,
            json={"status": status},
        )

        assert response.status_code == 200

    def test_invalid_status_is_rejected(self, client, user, program_id):
        application = create_application(client, user, program_id)

        response = client.patch(
            f"/api/applications/{application['application_id']}",
            headers=user.headers,
            json={"status": "maybe"},
        )

        assert response.status_code == 422

    def test_empty_body_changes_nothing(self, client, user, program_id):
        application = create_application(client, user, program_id)

        response = client.patch(
            f"/api/applications/{application['application_id']}",
            headers=user.headers,
            json={},
        )

        assert response.status_code == 200
        unchanged = client.get(collection_url(user.user_id), headers=user.headers).json()[0]
        assert unchanged["status"] == "not started"

    def test_unknown_application(self, client, user):
        response = client.patch(
            "/api/applications/999999", headers=user.headers, json={"notes": "x"}
        )

        assert response.status_code == 404
        assert response.json() == {"success": False, "error": "Application not found"}

    def test_cannot_update_another_users_application(
        self, client, user, other_user, program_id
    ):
        application = create_application(client, other_user, program_id)

        response = client.patch(
            f"/api/applications/{application['application_id']}",
            headers=user.headers,
            json={"status": "rejected"},
        )

        assert response.status_code == 403
        assert response.json() == NOT_YOUR_APPLICATIONS
        still = client.get(
            collection_url(other_user.user_id), headers=other_user.headers
        ).json()[0]
        assert still["status"] == "not started"

    @pytest.mark.parametrize(
        "field",
        [
            "status",
            "transcripts_done",
            "recommendations_done",
            "statement_done",
            "test_scores_done",
        ],
    )
    def test_null_for_required_field_is_rejected(self, client, user, program_id, field):
        application = create_application(client, user, program_id)

        response = client.patch(
            f"/api/applications/{application['application_id']}",
            headers=user.headers,
            json={field: None},
        )

        assert response.status_code == 422
        assert response.json()["success"] is False
        assert f"{field} cannot be null" in response.json()["error"]
        unchanged = client.get(collection_url(user.user_id), headers=user.headers).json()[0]
        assert unchanged[field] == application[field]

    def test_notes_can_be_cleared_with_null(self, client, user, program_id):
        application = create_application(client, user, program_id)
        url = f"/api/applications/{application['application_id']}"
        client.patch(url, headers=user.headers, json={"notes": "Call admissions"})

        response = client.patch(url, headers=user.headers, json={"notes": None})

        assert response.status_code == 200
        cleared = client.get(collection_url(user.user_id), headers=user.headers).json()[0]
        assert cleared["notes"] is None


class TestDeleteApplication:
    def test_deletes(self, client, user, program_id):
        application = create_application(client, user, program_id)

        response = client.delete(
            f"/api/applications/{application['application_id']}", headers=user.headers
        )

        assert response.status_code == 200
        assert response.json() == {"success": True}
        assert client.get(collection_url(user.user_id), headers=user.headers).json() == []

    def test_can_reapply_after_deleting(self, client, user, program_id):
        application = create_application(client, user, program_id)
        client.delete(
            f"/api/applications/{application['application_id']}", headers=user.headers
        )

        again = create_application(client, user, program_id)

        assert again["program_id"] == program_id

    def test_deleting_an_application_deletes_its_tasks(self, client, user, program_id):
        application = create_application(client, user, program_id)
        # create a couple tasks that correspond to this application
        client.post(
            f"/api/users/{user.user_id}/tasks/",
            headers=user.headers,
            json={"title": "Write statement", "application_id": application["application_id"]},
        )
        client.post(
            f"/api/users/{user.user_id}/tasks/",
            headers=user.headers,
            json={"title": "Unrelated task"},
        )
        # and one unrelated one as well
        client.delete(
            f"/api/applications/{application['application_id']}", headers=user.headers
        )

        tasks = client.get(f"/api/users/{user.user_id}/tasks/", headers=user.headers).json()
        # assert that the only task under this user is the unrelated one (others should have been deleted with the application)
        assert [t["title"] for t in tasks] == ["Unrelated task"]

    def test_unknown_application(self, client, user):
        response = client.delete("/api/applications/999999", headers=user.headers)

        assert response.status_code == 404
        assert response.json() == {"success": False, "error": "Application not found"}

    def test_cannot_delete_another_users_application(
        self, client, user, other_user, program_id
    ):
        application = create_application(client, other_user, program_id)

        response = client.delete(
            f"/api/applications/{application['application_id']}", headers=user.headers
        )

        assert response.status_code == 403
        assert response.json() == NOT_YOUR_APPLICATIONS
        assert len(
            client.get(collection_url(other_user.user_id), headers=other_user.headers).json()
        ) == 1
