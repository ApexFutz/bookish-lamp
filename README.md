# bookish-lamp

Warehouse **skills-matrix + access-control** app. Users have a job-function **role**
(baseline permissions) plus certified **equipment qualifications** (e.g. forklift, with
expiry) that layer on extra permissions, governed by **authorization tiers**.

Stack (see ADR-0001 on issue #1): **Django + HTMX/Alpine/Tailwind, PostgreSQL**, delivered
as a responsive PWA. Authorization is **read-time and fail-safe (deny-by-default)**.

## Glossary
- **Role / Job function** — grants a baseline set of permissions (e.g. Picker, Shift Lead).
- **Permission** — a granular capability (e.g. `equipment.operate.forklift`).
- **Tier** — seniority level; a user can only grant at or below their own tier.
- **Qualification / Equipment** — a certifiable skill that adds permissions while valid.
- **Effective permissions** — role baseline ∪ permissions from *currently-valid* qualifications,
  computed at read time (never trusted to a background flag).

## Local setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env          # then edit if needed
python manage.py migrate
python manage.py seed_demo       # demo tiers/roles/qualifications/users
python manage.py runserver
```

Then open http://127.0.0.1:8000/ and log in.

### Demo logins (created by `seed_demo`)
| User      | Password    | Role            | Tier |
|-----------|-------------|-----------------|------|
| `manager` | `demo12345` | Warehouse Mgr   | 3    |
| `lead`    | `demo12345` | Shift Lead      | 2    |
| `picker`  | `demo12345` | Picker          | 1    |

Django admin: http://127.0.0.1:8000/admin/ (`manager` is a superuser).

## The vertical slice this scaffold proves
Log in → see my qualifications & effective permissions → a manager grants "Forklift" →
the picker's effective permissions change immediately (read-time) → it shows in the matrix.
