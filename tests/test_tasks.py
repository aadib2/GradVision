"""Task and calendar routes."""

from datetime import date

import pytest

from app.models import models

NOT_YOUR_TASKS = {
    "success": False,
    "error": "You do not have permission to access these tasks",
}
NOT_YOUR_TASK = {
    "success": False,
    "error": "You do not have permission to modify this task",
}


def tasks_url(user_id):
    return f"/api/users/{user_id}/tasks/"


def create_task(client, user, **fields):
    response = client.post(
        tasks_url(user.user_id), headers=user.headers, json={"title": "A task", **fields}
    )
    assert response.status_code == 201, response.text
    return response.json()["task"]


def create_application(client, user, program_id):
    response = client.post(
        f"/api/users/{user.user_id}/applications/",
        headers=user.headers,
        json={"program_id": program_id},
    )
    assert response.status_code == 201, response.text
    return response.json()["application"]


class TestCreateTask:
    def test_minimal_task(self, client, user):
        response = client.post(
            tasks_url(user.user_id), headers=user.headers, json={"title": "Book GRE"}
        )

        assert response.status_code == 201
        body = response.json()
        assert body["success"] is True
        assert body["task"]["task_id"] > 0
        assert body["task"]["user_id"] == user.user_id
        assert body["task"]["title"] == "Book GRE"
        assert body["task"]["completed"] is False
        assert body["task"]["due_date"] is None
        assert body["task"]["application_id"] is None

    def test_with_due_date_and_own_application(self, client, user, seeded_catalog):
        application = create_application(
            client, user, seeded_catalog["ai_masters"].program_id
        )

        task = create_task(
            client,
            user,
            due_date="2027-01-10T12:00:00",
            application_id=application["application_id"],
        )

        assert task["due_date"] == "2027-01-10T12:00:00"
        assert task["application_id"] == application["application_id"]

    def test_unknown_application(self, client, user):
        response = client.post(
            tasks_url(user.user_id),
            headers=user.headers,
            json={"title": "x", "application_id": 999},
        )

        assert response.status_code == 404
        assert response.json() == {"success": False, "error": "Application not found"}

    def test_cannot_attach_to_another_users_application(
        self, client, user, other_user, seeded_catalog
    ):
        theirs = create_application(
            client, other_user, seeded_catalog["ai_masters"].program_id
        )

        response = client.post(
            tasks_url(user.user_id),
            headers=user.headers,
            json={"title": "sneaky", "application_id": theirs["application_id"]},
        )

        # Same response as a nonexistent application, so ids can't be probed.
        assert response.status_code == 404
        assert response.json() == {"success": False, "error": "Application not found"}

    @pytest.mark.parametrize(
        "body",
        [{}, {"title": 123456789}, {"title": "x", "due_date": "not-a-date"}],
    )
    def test_invalid_body(self, client, user, body):
        response = client.post(tasks_url(user.user_id), headers=user.headers, json=body)

        assert response.status_code == 422

    def test_cannot_create_for_another_user(self, client, user, other_user):
        response = client.post(
            tasks_url(other_user.user_id), headers=user.headers, json={"title": "x"}
        )

        assert response.status_code == 403
        assert response.json() == NOT_YOUR_TASKS
        assert client.get(tasks_url(other_user.user_id), headers=other_user.headers).json() == []


class TestListTasks:
    def test_starts_empty(self, client, user):
        response = client.get(tasks_url(user.user_id), headers=user.headers)

        assert response.status_code == 200
        assert response.json() == []

    def test_ordered_by_due_date_with_undated_tasks_last(self, client, user):
        create_task(client, user, title="undated")
        create_task(client, user, title="late", due_date="2027-06-01T00:00:00")
        create_task(client, user, title="early", due_date="2027-01-01T00:00:00")

        tasks = client.get(tasks_url(user.user_id), headers=user.headers).json()

        assert [t["title"] for t in tasks] == ["early", "late", "undated"]

    def test_lists_only_own_tasks(self, client, user, other_user):
        create_task(client, user, title="mine")
        create_task(client, other_user, title="theirs")

        mine = client.get(tasks_url(user.user_id), headers=user.headers).json()

        assert [t["title"] for t in mine] == ["mine"]

    def test_cannot_list_another_users_tasks(self, client, user, other_user):
        response = client.get(tasks_url(other_user.user_id), headers=user.headers)

        assert response.status_code == 403
        assert response.json() == NOT_YOUR_TASKS


class TestUpdateTask:
    def test_updates_fields(self, client, user):
        task = create_task(client, user, title="Old title")

        response = client.patch(
            f"/api/tasks/{task['task_id']}",
            headers=user.headers,
            json={"title": "New title", "completed": True, "due_date": "2027-03-01T09:30:00"},
        )

        assert response.status_code == 200
        assert response.json() == {"success": True}
        updated = client.get(tasks_url(user.user_id), headers=user.headers).json()[0]
        assert updated["title"] == "New title"
        assert updated["completed"] is True
        assert updated["due_date"] == "2027-03-01T09:30:00"

    def test_partial_update_leaves_other_fields(self, client, user):
        task = create_task(client, user, title="Keep me", due_date="2027-03-01T09:30:00")

        client.patch(
            f"/api/tasks/{task['task_id']}", headers=user.headers, json={"completed": True}
        )

        updated = client.get(tasks_url(user.user_id), headers=user.headers).json()[0]
        assert updated["title"] == "Keep me"
        assert updated["due_date"] == "2027-03-01T09:30:00"

    def test_can_clear_the_due_date(self, client, user):
        task = create_task(client, user, due_date="2027-03-01T09:30:00")

        client.patch(
            f"/api/tasks/{task['task_id']}", headers=user.headers, json={"due_date": None}
        )

        updated = client.get(tasks_url(user.user_id), headers=user.headers).json()[0]
        assert updated["due_date"] is None

    def test_ownership_fields_in_the_body_are_ignored(
        self, client, user, other_user, seeded_catalog
    ):
        # TaskUpdate has no user_id / application_id, so a task cannot be reassigned.
        theirs = create_application(
            client, other_user, seeded_catalog["ai_masters"].program_id
        )
        task = create_task(client, user, title="Mine")

        client.patch(
            f"/api/tasks/{task['task_id']}",
            headers=user.headers,
            json={
                "user_id": other_user.user_id,
                "application_id": theirs["application_id"],
            },
        )

        mine = client.get(tasks_url(user.user_id), headers=user.headers).json()
        assert [t["task_id"] for t in mine] == [task["task_id"]]
        assert mine[0]["application_id"] is None
        assert client.get(tasks_url(other_user.user_id), headers=other_user.headers).json() == []

    def test_unknown_task(self, client, user):
        response = client.patch(
            "/api/tasks/999999", headers=user.headers, json={"completed": True}
        )

        assert response.status_code == 404
        assert response.json() == {"success": False, "error": "Task not found"}

    def test_cannot_update_another_users_task(self, client, user, other_user):
        task = create_task(client, other_user, title="Theirs")

        response = client.patch(
            f"/api/tasks/{task['task_id']}", headers=user.headers, json={"title": "Hijacked"}
        )

        assert response.status_code == 403
        assert response.json() == NOT_YOUR_TASK
        unchanged = client.get(tasks_url(other_user.user_id), headers=other_user.headers).json()
        assert unchanged[0]["title"] == "Theirs"

    @pytest.mark.parametrize("field", ["title", "completed"])
    def test_null_for_required_field_is_rejected(self, client, user, field):
        task = create_task(client, user, title="Keep me")

        response = client.patch(
            f"/api/tasks/{task['task_id']}", headers=user.headers, json={field: None}
        )

        assert response.status_code == 422
        assert response.json()["success"] is False
        assert f"{field} cannot be null" in response.json()["error"]
        unchanged = client.get(tasks_url(user.user_id), headers=user.headers).json()[0]
        assert unchanged[field] == task[field]


class TestDeleteTask:
    def test_deletes(self, client, user):
        task = create_task(client, user)

        response = client.delete(f"/api/tasks/{task['task_id']}", headers=user.headers)

        assert response.status_code == 200
        assert response.json() == {"success": True}
        assert client.get(tasks_url(user.user_id), headers=user.headers).json() == []

    def test_deleting_twice_gives_404(self, client, user):
        task = create_task(client, user)
        client.delete(f"/api/tasks/{task['task_id']}", headers=user.headers)

        response = client.delete(f"/api/tasks/{task['task_id']}", headers=user.headers)

        assert response.status_code == 404
        assert response.json() == {"success": False, "error": "Task not found"}

    def test_cannot_delete_another_users_task(self, client, user, other_user):
        task = create_task(client, other_user)

        response = client.delete(f"/api/tasks/{task['task_id']}", headers=user.headers)

        assert response.status_code == 403
        assert response.json() == NOT_YOUR_TASK
        assert len(client.get(tasks_url(other_user.user_id), headers=other_user.headers).json()) == 1


class TestCalendar:
    @staticmethod
    def url(user_id):
        return f"/api/users/{user_id}/calendar/"

    @pytest.fixture
    def extra_events(self, db_session, seeded_catalog):
        """seeded_catalog has one AI Masters event (2027-01-15); add two more."""
        db_session.add_all(
            [
                models.Event(
                    program_id=seeded_catalog["cs_phd"].program_id,
                    label="CS PhD deadline",
                    event_type="deadline",
                    event_date=date(2026, 12, 1),
                ),
                models.Event(
                    program_id=seeded_catalog["bio_masters"].program_id,
                    label="Bio deadline",
                    event_type="deadline",
                    event_date=date(2027, 2, 1),
                ),
            ]
        )
        db_session.commit()

    def test_empty_with_no_applications_or_saved_programs(self, client, user, extra_events):
        response = client.get(self.url(user.user_id), headers=user.headers)

        assert response.status_code == 200
        assert response.json() == []

    def test_includes_applied_and_saved_programs_ordered_by_date(
        self, client, user, seeded_catalog, extra_events
    ):
        create_application(client, user, seeded_catalog["ai_masters"].program_id)
        client.post(
            f"/api/users/{user.user_id}/saved-programs/",
            headers=user.headers,
            json={"program_id": seeded_catalog["cs_phd"].program_id},
        )

        response = client.get(self.url(user.user_id), headers=user.headers)

        assert response.status_code == 200
        events = response.json()
        # Bio is neither applied to nor saved, so it is excluded.
        assert [e["label"] for e in events] == ["CS PhD deadline", "AI Masters deadline"]
        assert events[0]["event_date"] == "2026-12-01"
        assert events[0]["program_id"] == seeded_catalog["cs_phd"].program_id

    def test_program_both_applied_and_saved_is_not_duplicated(
        self, client, user, seeded_catalog
    ):
        program_id = seeded_catalog["ai_masters"].program_id
        create_application(client, user, program_id)
        client.post(
            f"/api/users/{user.user_id}/saved-programs/",
            headers=user.headers,
            json={"program_id": program_id},
        )

        events = client.get(self.url(user.user_id), headers=user.headers).json()

        assert len(events) == 1

    def test_is_per_user(self, client, user, other_user, seeded_catalog):
        create_application(client, user, seeded_catalog["ai_masters"].program_id)

        theirs = client.get(self.url(other_user.user_id), headers=other_user.headers)

        assert theirs.json() == []

    def test_cannot_view_another_users_calendar(self, client, user, other_user):
        response = client.get(self.url(other_user.user_id), headers=user.headers)

        assert response.status_code == 403
        assert response.json() == NOT_YOUR_TASKS
