# Third-Party Licenses

The runtime dependencies below were reviewed for compatibility with proprietary, client-owned
use. All are permissive (BSD/MIT-style) or LGPL and impose no copyleft obligation on this
application's own source code. Verify current terms when upgrading.

| Dependency | Purpose | License | Client-use compatible |
|---|---|---|---|
| Django | Web framework | BSD-3-Clause | Yes |
| django-axes | Login rate limiting / lockout | MIT | Yes |
| whitenoise | Static file serving | MIT | Yes |
| psycopg (binary) | PostgreSQL driver | LGPL-3.0 | Yes — used as an unmodified library |
| python-dotenv | Load `.env` config | BSD-3-Clause | Yes |
| dj-database-url | Parse `DATABASE_URL` | BSD-3-Clause | Yes |

Notes:
- **psycopg** is LGPL: it is used as an unmodified, dynamically-imported library, which does not
  impose licensing requirements on this application's code. Do not modify psycopg's source.
- Front-end assets (Tailwind, HTMX) are currently loaded from CDNs (MIT-licensed). If they are
  later vendored into a build step (issue #2 follow-up), keep their MIT license notices.

To regenerate an exact dependency license inventory:
```bash
pip install pip-licenses
pip-licenses --format=markdown --with-urls
```
