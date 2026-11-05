"""Public (no login needed) routes: root, docs, universities, programs, papers."""

import pytest


class TestAppBasics:
    def test_backend_starts(self, client):
        assert client.get("/docs").status_code == 200

    def test_root(self, client):
        response = client.get("/")

        assert response.status_code == 200
        assert response.json() == {"message": "Hello World"}


class TestListUniversities:
    def test_empty_database_returns_empty_list(self, client):
        response = client.get("/api/universities")

        assert response.status_code == 200
        assert response.json() == []

    def test_returns_summaries_with_counts_ordered_by_name(self, client, seeded_catalog):
        response = client.get("/api/universities")

        assert response.status_code == 200
        body = response.json()
        assert [u["university_name"] for u in body] == ["Tech Institute", "Valley University"]
        assert body[0] == {
            "university_id": seeded_catalog["mit"].university_id,
            "university_name": "Tech Institute",
            "location": "Massachusetts",
            "program_count": 2,
            "professor_count": 1,
        }
        assert body[1]["program_count"] == 1
        assert body[1]["professor_count"] == 0

    @pytest.mark.parametrize(
        "params, expected_names",
        [
            ({"location": "massa"}, ["Tech Institute"]),  # case-insensitive "contains"
            ({"location": "CALIFORNIA"}, ["Valley University"]),
            ({"search": "valley"}, ["Valley University"]),
            ({"search": "nothing-matches-this"}, []),
            ({"program_fields": "Biology"}, ["Valley University"]),
            (
                {"program_fields": ["Biology", "Computer Science"]},
                ["Tech Institute", "Valley University"],
            ),
            ({"location": "massa", "search": "valley"}, []),  # filters combine with AND
        ],
    )
    def test_filters(self, client, seeded_catalog, params, expected_names):
        response = client.get("/api/universities", params=params)

        assert response.status_code == 200
        assert [u["university_name"] for u in response.json()] == expected_names

    def test_pagination(self, client, seeded_catalog):
        first = client.get("/api/universities", params={"limit": 1, "offset": 0}).json()
        second = client.get("/api/universities", params={"limit": 1, "offset": 1}).json()
        past_end = client.get("/api/universities", params={"limit": 1, "offset": 5}).json()

        assert [u["university_name"] for u in first] == ["Tech Institute"]
        assert [u["university_name"] for u in second] == ["Valley University"]
        assert past_end == []

    @pytest.mark.parametrize(
        "params",
        [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"limit": "abc"}],
    )
    def test_invalid_pagination_is_rejected(self, client, params):
        response = client.get("/api/universities", params=params)

        assert response.status_code == 422
        assert response.json()["success"] is False


class TestGetProgram:
    def test_returns_full_detail_with_events(self, client, seeded_catalog):
        program = seeded_catalog["ai_masters"]

        response = client.get(f"/api/program/{program.program_id}")

        assert response.status_code == 200
        body = response.json()
        assert body["program_id"] == program.program_id
        assert body["university_id"] == seeded_catalog["mit"].university_id
        assert body["program_name"] == "AI Masters"
        assert body["degree_type"] == "Masters"
        assert body["field"] == "Artificial Intelligence"
        assert body["funding_available"] is True
        assert body["application_requirements"] == ["transcripts", "statement"]
        assert body["price"] == 40000
        assert [e["label"] for e in body["events"]] == ["AI Masters deadline"]
        assert body["events"][0]["event_date"] == "2027-01-15"

    def test_program_without_events_returns_empty_list(self, client, seeded_catalog):
        response = client.get(f"/api/program/{seeded_catalog['cs_phd'].program_id}")

        assert response.status_code == 200
        assert response.json()["events"] == []

    def test_not_found(self, client):
        response = client.get("/api/program/999999")

        assert response.status_code == 404
        assert response.json() == {"success": False, "error": "Program not found"}

    def test_non_integer_id_is_rejected(self, client):
        response = client.get("/api/program/not-a-number")

        assert response.status_code == 422
        assert response.json()["success"] is False


class TestPapers:
    def test_empty_database(self, client):
        response = client.get("/api/papers")

        assert response.status_code == 200
        assert response.json() == []

    def test_lists_newest_first_with_professor_ids(self, client, seeded_catalog):
        response = client.get("/api/papers")

        assert response.status_code == 200
        body = response.json()
        assert [p["title"] for p in body] == ["Learning More Things", "Learning Things"]
        assert body[0]["professor_ids"] == [seeded_catalog["professor"].professor_id]
        assert body[0]["publication_date"] == "2024-03-01"

    @pytest.mark.parametrize(
        "params, expected_titles",
        [
            ({"year_published": 2023}, ["Learning Things"]),
            ({"year_published": 1999}, []),
            ({"query": "deep"}, ["Learning More Things"]),  # matches the topics list
            ({"query": "LEARNING"}, ["Learning More Things", "Learning Things"]),
            ({"query": "learning more"}, ["Learning More Things"]),  # every keyword must match
            ({"query": "learning nonexistent"}, []),
            ({"limit": 1}, ["Learning More Things"]),
            ({"limit": 1, "offset": 1}, ["Learning Things"]),
        ],
    )
    def test_filters_and_pagination(self, client, seeded_catalog, params, expected_titles):
        response = client.get("/api/papers", params=params)

        assert response.status_code == 200
        assert [p["title"] for p in response.json()] == expected_titles

    def test_filter_by_professor(self, client, seeded_catalog):
        professor_id = seeded_catalog["professor"].professor_id

        matching = client.get("/api/papers", params={"professor_id": professor_id}).json()
        other = client.get("/api/papers", params={"professor_id": professor_id + 100}).json()

        assert len(matching) == 2
        assert other == []

    @pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}])
    def test_invalid_pagination_is_rejected(self, client, params):
        assert client.get("/api/papers", params=params).status_code == 422


class TestProfessorPapers:
    def test_returns_that_professors_papers(self, client, seeded_catalog):
        professor_id = seeded_catalog["professor"].professor_id

        response = client.get(f"/api/professors/{professor_id}/papers")

        assert response.status_code == 200
        assert [p["title"] for p in response.json()] == [
            "Learning More Things",
            "Learning Things",
        ]

    def test_unknown_professor_is_404(self, client, seeded_catalog):
        response = client.get("/api/professors/999999/papers")

        assert response.status_code == 404
        assert response.json() == {"success": False, "error": "Professor not found"}
