"""Shared pytest fixtures for the GradVision API tests.

Every test gets its own throwaway in-memory SQLite database, so tests never
touch gradvision.db and never depend on each other.
"""

import os

# These must be set BEFORE any `app` import: security.py reads JWT_SECRET_KEY at
# import time, and database.py builds its engine from DATABASE_URL at import time.
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-gradvision-tests-0123456789")
os.environ["DATABASE_URL"] = "sqlite://"  # mock DB, doesn't point at gradvision.db
from dataclasses import dataclass  # noqa: E402
from datetime import date  # noqa: E402
from itertools import count  # noqa: E402

import bcrypt  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import models  # noqa: E402

TEST_PASSWORD = "dummy123"


@pytest.fixture(autouse=True)
def fast_bcrypt(monkeypatch):
    """bcrypt is slow on purpose (cost 12); use the minimum cost so signups are cheap.

    Hashes are still real bcrypt hashes and verify normally, because the cost is
    stored inside each hash.
    """
    real_gensalt = bcrypt.gensalt
    monkeypatch.setattr(bcrypt, "gensalt", lambda *a, **kw: real_gensalt(rounds=4))


@pytest.fixture
def engine():
    """A fresh in-memory SQLite database with every table created."""
    # StaticPool keeps a single connection alive; without it each new connection
    # would see its own empty in-memory database.
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # Same per-connection pragma the real engine uses, so ON DELETE CASCADE works.
    @event.listens_for(test_engine, "connect")
    def _enable_sqlite_fks(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(bind=test_engine)
    yield test_engine
    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()


@pytest.fixture
def session_factory(engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture
def db_session(session_factory):
    """A session for tests that need to insert or inspect rows directly."""
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(session_factory):
    """A TestClient whose get_db dependency points at the test database."""

    def override_get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    # Not used as a context manager on purpose: that would run the app lifespan,
    # which calls create_all on the (unused) module-level engine.
    yield TestClient(app)
    app.dependency_overrides.clear()


@dataclass
class TestUser:
    __test__ = False  # stop pytest from trying to collect this as a test class

    user_id: int
    email: str
    password: str
    access_token: str
    refresh_token: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}


@pytest.fixture
def make_user(client):
    """Factory: sign up through the API, log in through the API, return credentials.

    Call it more than once to get several users (e.g. to test 403 cross-user access).
    """
    counter = count(1)

    def _make_user(**overrides) -> TestUser:
        n = next(counter)
        payload = {
            "first_name": "Test",
            "last_name": f"User{n}",
            "email": f"user{n}@example.com",
            "password": TEST_PASSWORD,
            **overrides,
        }
        signup = client.post("/api/users", json=payload)
        assert signup.status_code == 201, signup.text

        login = client.post(
            "/api/auth/login",
            json={"email": payload["email"], "password": payload["password"]},
        )
        assert login.status_code == 200, login.text
        tokens = login.json()

        return TestUser(
            user_id=signup.json()["user"]["user_id"],
            email=payload["email"],
            password=payload["password"],
            access_token=tokens["access_token"],
            refresh_token=tokens["refresh_token"],
        )

    return _make_user


@pytest.fixture
def user(make_user) -> TestUser:
    """A single signed-up, logged-in user."""
    return make_user()


@pytest.fixture
def other_user(make_user, user) -> TestUser:
    """A second user, for ownership / 403 tests. Depends on `user` so ids differ."""
    return make_user()


@pytest.fixture
def seeded_catalog(db_session):
    """A small, predictable slice of the public catalog.

    Returns a dict of the created rows so tests can refer to real ids.
    """
    mit = models.University(university_name="Tech Institute", location="Massachusetts")
    stanford = models.University(university_name="Valley University", location="California")
    db_session.add_all([mit, stanford])
    db_session.flush()

    ai_masters = models.Program(
        university_id=mit.university_id,
        program_name="AI Masters",
        degree_type=models.DegreeType.masters,
        field="Artificial Intelligence",
        funding_available=True,
        application_requirements=["transcripts", "statement"],
        program_start=2027,
        program_end=2029,
        program_content=["Machine Learning"],
        price=40000,
    )
    cs_phd = models.Program(
        university_id=mit.university_id,
        program_name="CS PhD",
        degree_type=models.DegreeType.phd,
        field="Computer Science",
        funding_available=True,
    )
    bio_masters = models.Program(
        university_id=stanford.university_id,
        program_name="Bioinformatics Masters",
        degree_type=models.DegreeType.masters,
        field="Biology",
        funding_available=False,
    )
    db_session.add_all([ai_masters, cs_phd, bio_masters])
    db_session.flush()

    db_session.add(
        models.Event(
            program_id=ai_masters.program_id,
            label="AI Masters deadline",
            event_type="deadline",
            event_date=date(2027, 1, 15),
        )
    )

    professor = models.Professor(
        university_id=mit.university_id,
        name="Dr. Ada Example",
        department="Computer Science",
        research_interests=["machine learning"],
    )
    db_session.add(professor)
    db_session.flush()

    paper_2023 = models.Paper(
        title="Learning Things",
        authors=["Ada Example"],
        topics=["machine learning"],
        publication_date=date(2023, 6, 1),
    )
    paper_2024 = models.Paper(
        title="Learning More Things",
        authors=["Ada Example"],
        topics=["deep learning"],
        publication_date=date(2024, 3, 1),
    )
    db_session.add_all([paper_2023, paper_2024])
    db_session.flush()

    db_session.add_all(
        [
            models.ProfessorPaper(
                professor_id=professor.professor_id, paper_id=paper_2023.paper_id
            ),
            models.ProfessorPaper(
                professor_id=professor.professor_id, paper_id=paper_2024.paper_id
            ),
        ]
    )
    db_session.commit()

    return {
        "mit": mit,
        "stanford": stanford,
        "ai_masters": ai_masters,
        "cs_phd": cs_phd,
        "bio_masters": bio_masters,
        "professor": professor,
        "paper_2023": paper_2023,
        "paper_2024": paper_2024,
    }
