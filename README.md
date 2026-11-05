# GradVision
Backend for the COMPE561 Full Stack Web Development course, built with FastAPI.

The API yaml lives in [`docs/GradVision_API.yaml`](docs/GradVision_API.yaml); models and design notes are in [`docs/backend-wireframe-and-models.md`](docs/backend-wireframe-and-models.md).

## Getting Started

### 1. Install dependencies

Requires Python 3.14+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

### 2. Set environment variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `JWT_SECRET_KEY` | **Yes** | — | Secret used to sign JWTs. The app will not start without it. |
| `DATABASE_URL` | No | `sqlite:///./gradvision.db` | Database connection string (relative to where you run the commands). |

Generate a secret and export it in every terminal you use for the app:

```bash
export JWT_SECRET_KEY="$(openssl rand -hex 32)"
```

> Changing the secret invalidates all previously issued tokens.

### 3. Create the database

Run from the repo root so every command uses the same `gradvision.db`:

```bash
uv run alembic upgrade head
```

> The migration creates the catalog and user tables. The `refresh_tokens` table is created automatically the first time the server starts, so start the server (step 5) before trying to log in.

### 4. Add mock data

Seed universities, programs, deadline events, professors and papers:

```bash
uv run python scripts/seed_db.py            # skips if universities already exist
uv run python scripts/seed_db.py --reset    # wipe catalog data first, then re-seed
```

`--reset` also deletes applications, their tasks and saved programs (they can't exist without programs). User accounts are kept.

The seed script does not create users; sign up through the API (see below).

### 5. Run the server

```bash
uv run uvicorn app.main:app --reload --app-dir src
```

- API: http://localhost:8000
- Interactive docs (Swagger UI): http://localhost:8000/docs

CORS is configured for a frontend on `http://localhost:3000`.

## Authentication

The API uses JWT bearer authentication.

| Token | Lifetime | Used for |
|-------|----------|----------|
| Access token | 30 minutes | Sent as `Authorization: Bearer <token>` on protected routes |
| Refresh token | 7 days | Exchanged at `/api/auth/refresh` for a new access token |

Flow:

1. **Sign up** — `POST /api/users` (public).
2. **Log in** — `POST /api/auth/login` with `{"email": ..., "password": ...}` returns `access_token` and `refresh_token`.
3. **Call protected endpoints** with the access token in the `Authorization` header.
4. **Refresh** — `POST /api/auth/refresh` with `{"refresh_token": ...}` returns a new access token.
5. **Log out** — `POST /api/auth/logout` with the refresh token revokes it.

Protected routes under `/api/users/{id}/...` only work for your own user ID. Using another user's ID returns `403 Forbidden`, and a missing/expired token returns `401 Unauthorized`. Errors come back as `{"success": false, "error": "..."}`.

Public routes: sign up, login, refresh, `/api/universities`, `/api/program/{program_id}`, `/api/papers`, `/api/professors/{id}/papers`.

## Trying Out the Endpoints

### In Swagger UI (`/docs`)

1. Create an account with `POST /api/users` → **Try it out**:
   ```json
   {"first_name": "Test", "last_name": "User", "email": "test@example.com", "password": "password123"}
   ```
   Note the `user_id` in the response; you need it for `/api/users/{id}/...` paths.
2. Click **Authorize** (top right). Enter your **email** as `username` and your **password** as `password`. Leave `client_id` and `client_secret` blank, then click **Authorize**.
3. Try protected endpoints, e.g. `POST /api/users/{user_id}/applications/` with `{"program_id": 1}`, then `GET /api/users/{user_id}/applications/`, tasks, saved programs, or the calendar.

Authorize uses a form-based `POST /api/auth/token` endpoint that exists for Swagger only. The frontend should use `/api/auth/login`. If you start getting `401`s, your access token expired (30 min); click Authorize again.

### With curl

```bash
# Sign up
curl -X POST localhost:8000/api/users -H "Content-Type: application/json" \
  -d '{"first_name":"Test","last_name":"User","email":"test@example.com","password":"password123"}'

# Log in and keep the access token
TOKEN=$(curl -s -X POST localhost:8000/api/auth/login -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"password123"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Public catalog data
curl localhost:8000/api/universities

# Protected: add an application, then add a task and view the calendar (user id 1)
curl -X POST localhost:8000/api/users/1/applications/ \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"program_id":1}'
curl -X POST localhost:8000/api/users/1/tasks/ \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"title":"Write statement"}'
curl localhost:8000/api/users/1/calendar/ -H "Authorization: Bearer $TOKEN"
```

## Running Tests

From the repo root (`pytest` is configured in `pyproject.toml` to find `src/`):

```bash
uv run pytest
```

No environment variables are needed: `tests/conftest.py` sets a test `JWT_SECRET_KEY` and
points the app at a throwaway in-memory SQLite database, so the tests never read or
modify `gradvision.db`. Every test starts with a fresh, empty database.

Useful variants:

```bash
uv run pytest -v                                       # list each test
uv run pytest tests/test_tasks.py                      # one file
uv run pytest tests/test_auth.py::TestRefresh          # one class
uv run pytest -k "forbidden or 403"                    # tests matching a keyword
uv run pytest -rx                                      # show why each expected failure is marked xfail
```

Test layout (`tests/`):

| File | Covers |
|---|---|
| `conftest.py` | Shared fixtures: `client`, `user`, `other_user`, `make_user`, `seeded_catalog`, `db_session` |
| `test_auth.py` | Login, token refresh/rotation, logout, access-token validation |
| `test_users.py` | Signup, profile get/update/delete, saved programs |
| `test_applications.py`, `test_tasks.py` | Applications, tasks, calendar, ownership checks |
| `test_public_catalog.py`, `test_search.py` | Universities, programs, papers, search |
| `test_security_access.py` | Every protected route returns 401 without a valid token |

Tests marked `xfail` document known bugs: they assert the *correct* behaviour and are
expected to fail until the bug is fixed. They are `strict`, so once a bug is fixed the
test fails as an unexpected pass, which is the cue to delete its `xfail` marker.

## Repository Structure

```
src/app/
  main.py        FastAPI app, CORS, router registration
  routes/        HTTP endpoints (auth, users, search, programs, papers, applications, tasks/calendar)
  crud/          Database queries used by the routes
  schemas/       Pydantic request/response models
  models/        SQLAlchemy ORM models
  api/deps.py    get_current_user (JWT validation)
  core/          Database session, JWT/password security, error handlers
alembic/         Database migrations
scripts/         seed_db.py (mock data) and db_smoke_test.py
tests/           pytest suite
docs/            OpenAPI spec and design docs
```
