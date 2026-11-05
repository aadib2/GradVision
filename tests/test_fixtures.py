"""Proves the shared fixtures work before any real tests rely on them."""

from app.core.database import engine as app_engine


def test_make_user_returns_working_token(client, user):
    response = client.get(f"/api/users/{user.user_id}", headers=user.headers)

    assert response.status_code == 200
    assert response.json()["email"] == user.email


def test_each_test_gets_a_fresh_database(client, user):
    # Every test creates user1@example.com; this would 400 as a duplicate if the
    # database were shared between tests.
    assert user.email == "user1@example.com"


def test_two_users_have_different_ids(user, other_user):
    assert user.user_id != other_user.user_id


def test_seeded_catalog_is_visible_through_the_api(client, seeded_catalog):
    program_id = seeded_catalog["ai_masters"].program_id

    response = client.get(f"/api/program/{program_id}")

    assert response.status_code == 200


def test_tests_do_not_use_the_real_database():
    assert str(app_engine.url) == "sqlite://"
