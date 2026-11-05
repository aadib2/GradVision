"""Search routes: /api/search/universities and /api/search/professors (public)."""

import pytest

from app.models import models


class TestSearchUniversities:
    def test_empty_database(self, client):
        response = client.get("/api/search/universities")

        assert response.status_code == 200
        assert response.json() == []

    def test_returns_same_shape_as_the_list_endpoint(self, client, seeded_catalog):
        response = client.get("/api/search/universities")

        assert response.status_code == 200
        assert response.json() == client.get("/api/universities").json()
        assert response.json()[0]["program_count"] == 2

    @pytest.mark.parametrize(
        "params, expected_names",
        [
            ({"location": "california"}, ["Valley University"]),
            ({"search": "tech"}, ["Tech Institute"]),
            ({"program_fields": "Biology"}, ["Valley University"]),
            ({"program_fields": ["Biology", "Computer Science"]}, ["Tech Institute", "Valley University"]),
            ({"search": "tech", "location": "california"}, []),
            ({"search": "zzz"}, []),
        ],
    )
    def test_filters(self, client, seeded_catalog, params, expected_names):
        response = client.get("/api/search/universities", params=params)

        assert response.status_code == 200
        assert [u["university_name"] for u in response.json()] == expected_names

    def test_pagination(self, client, seeded_catalog):
        first = client.get("/api/search/universities", params={"limit": 1}).json()
        second = client.get(
            "/api/search/universities", params={"limit": 1, "offset": 1}
        ).json()

        assert [u["university_name"] for u in first] == ["Tech Institute"]
        assert [u["university_name"] for u in second] == ["Valley University"]

    def test_non_numeric_limit_is_rejected(self, client):
        assert client.get("/api/search/universities", params={"limit": "x"}).status_code == 422

    @pytest.mark.parametrize(
        "params", [{"limit": 0}, {"limit": 101}, {"limit": -5}, {"offset": -1}]
    )
    def test_out_of_range_pagination_is_rejected_like_the_list_endpoint(self, client, params):
        response = client.get("/api/search/universities", params=params)

        assert response.status_code == 422
        assert response.json()["success"] is False

    @pytest.mark.parametrize(
        "params", [{"limit": 1}, {"limit": 100}, {"offset": 0}, {"limit": 100, "offset": 50}]
    )
    def test_boundary_pagination_values_are_accepted(self, client, params):
        assert client.get("/api/search/universities", params=params).status_code == 200


class TestSearchProfessors:
    def test_returns_professors_at_the_university(self, client, seeded_catalog):
        university_id = seeded_catalog["mit"].university_id

        response = client.get("/api/search/professors", params={"university_id": university_id})

        assert response.status_code == 200
        assert response.json() == [
            {
                "professor_id": seeded_catalog["professor"].professor_id,
                "name": "Dr. Ada Example",
                "department": "Computer Science",
                "university_id": university_id,
                "research_interests": ["machine learning"],
            }
        ]

    def test_ordered_by_name(self, client, db_session, seeded_catalog):
        university_id = seeded_catalog["mit"].university_id
        db_session.add(
            models.Professor(university_id=university_id, name="Dr. Aaron First")
        )
        db_session.commit()

        response = client.get("/api/search/professors", params={"university_id": university_id})

        assert [p["name"] for p in response.json()] == ["Dr. Aaron First", "Dr. Ada Example"]

    def test_only_that_universitys_professors(self, client, seeded_catalog):
        response = client.get(
            "/api/search/professors",
            params={"university_id": seeded_catalog["stanford"].university_id},
        )

        assert response.status_code == 200
        assert response.json() == []

    def test_unknown_university_returns_empty_list(self, client, seeded_catalog):
        response = client.get("/api/search/professors", params={"university_id": 999999})

        assert response.status_code == 200
        assert response.json() == []

    def test_university_id_is_required(self, client):
        response = client.get("/api/search/professors")

        assert response.status_code == 422
        assert "university_id" in response.json()["error"]

    def test_university_id_must_be_an_integer(self, client):
        response = client.get("/api/search/professors", params={"university_id": "abc"})

        assert response.status_code == 422
