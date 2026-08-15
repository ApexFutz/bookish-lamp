# Operations Runbook

This is the day-to-day guide for **running, deploying, and maintaining bookish-lamp** after
handoff. It assumes no prior work on this codebase — follow it top to bottom for a first
deploy, or jump to the section you need. See [ADR-0001](adr/ADR-0001.md) for why the stack is
what it is.

Stack: **Django** (Python) + **PostgreSQL**, served as a single web process. Static files are
served by WhiteNoise. Config comes entirely from **environment variables** — there are no
secrets in the code.

---

## 1. Prerequisites

- Python 3.11 or 3.12
- A **PostgreSQL** database (managed is strongly recommended — see §3)
- The ability to set environment variables on your host

## 2. Configuration (environment variables)

Copy `.env.example` to `.env` and fill it in (local dev), or set these in your host's config
(production). The app **fails to start if `SECRET_KEY` is missing when `DEBUG=False`** — this
is intentional.

| Variable | Required | Notes |
|---|---|---|
| `SECRET_KEY` | prod | Long random string. Never commit it. |
| `DEBUG` | — | `False` in production. |
| `ALLOWED_HOSTS` | prod | Comma-separated hostnames, e.g. `app.yourco.com`. |
| `DATABASE_URL` | prod | `postgres://user:pass@host:5432/dbname`. Unset = local SQLite. |
| `SESSION_COOKIE_AGE` | — | Idle timeout (seconds). Default 28800 (8h). |
| `AXES_FAILURE_LIMIT` / `AXES_COOLOFF_HOURS` | — | Login lockout tuning. |
| `EMAIL_*` / `DEFAULT_FROM_EMAIL` | prod | SMTP for password-reset emails. |
| `BOOTSTRAP_ADMIN_*` | once | Used only by the first-admin bootstrap (§5). |

## 3. Deploy (managed PaaS — recommended)

Host the app on a platform you (the client) own — e.g. **Render, Railway, or Fly.io** — with a
**managed PostgreSQL** add-on. Managed Postgres gives you automated daily backups and
point-in-time restore with no server to babysit. Steps:

1. Create the app + a managed Postgres instance on your platform; copy its connection string
   into `DATABASE_URL`.
2. Set the environment variables from §2 (`SECRET_KEY`, `DEBUG=False`, `ALLOWED_HOSTS`, email).
3. Build/release commands:
   ```bash
   pip install -r requirements.txt
   python manage.py migrate --noinput
   python manage.py collectstatic --noinput
   ```
4. Start command:
   ```bash
   gunicorn config.wsgi   # or: python manage.py runserver for local only
   ```
5. Create your first admin (§5), then log in and configure roles/tiers/equipment.

> Docker/compose is an equally valid path if you prefer to self-host; the app is a standard
> Django project, so any Django-capable host works. Avoid platform lock-in by keeping config in
> env vars (already the case).

## 4. Database migrations

Any time you deploy a new version:
```bash
python manage.py migrate --noinput
```
Migrations are versioned in `access/migrations/` and are safe to run repeatedly.

## 5. Create the first administrator (one-time)

On a brand-new install, create the founding super-admin — this needs **no developer account**
and **disables itself** once an admin exists:
```bash
python manage.py bootstrap_admin --username admin --email admin@yourco.com --password 'STRONG-PASSPHRASE'
# or set BOOTSTRAP_ADMIN_USERNAME / BOOTSTRAP_ADMIN_PASSWORD and run: python manage.py bootstrap_admin
```
After this, add users/roles/tiers/equipment from the app and the Django admin (`/admin/`).

## 6. Backups & restore

- **Backups:** rely on your managed Postgres provider's automated daily backups + point-in-time
  recovery. Verify they are enabled and note the retention window.
- **Manual snapshot:**
  ```bash
  pg_dump "$DATABASE_URL" > backup-$(date +%F).sql
  ```
- **Restore:**
  ```bash
  psql "$DATABASE_URL" < backup-YYYY-MM-DD.sql
  ```
- **Test your restore** at least once — a backup you've never restored is not a backup.

## 7. Updating the app

```bash
git pull                          # get the new version
pip install -r requirements.txt   # in case dependencies changed
python manage.py migrate --noinput
python manage.py collectstatic --noinput
# restart the web process
```
Run in a staging environment first if you have one; CI (GitHub Actions) must be green before
deploying.

## 8. Monitoring

- **Uptime:** point an external uptime checker at the site root.
- **Errors:** add a Sentry DSN (or your provider's error tracking) so exceptions are surfaced.
- **Certification expiry job:** once the expiry-alert job (issue #30) is scheduled, monitor that
  it runs on time — its whole purpose is to notify supervisors of lapsing certs.

## 9. Common tasks & troubleshooting

- **A user is locked out of login (too many attempts):** lockouts auto-clear after
  `AXES_COOLOFF_HOURS`. To clear immediately: `python manage.py axes_reset_username <username>`.
- **Reset a forgotten password:** users self-serve via "Forgot password?" (needs email
  configured). Admins can also set a password in `/admin/`.
- **Admin page returns 500 about a "staticfiles manifest":** you deployed with `DEBUG=False`
  but did not run `collectstatic`. Run it (§3 step 3).
- **App won't start, complains `SECRET_KEY` required:** set `SECRET_KEY` in the environment.
- **Everything is denied unexpectedly:** authorization is deny-by-default and derived at read
  time; check the user's role/tier and qualification expiry in `/admin/`.

## 10. Handoff

For transferring ownership away from the original developer, see
[HANDOFF_CHECKLIST.md](HANDOFF_CHECKLIST.md).
