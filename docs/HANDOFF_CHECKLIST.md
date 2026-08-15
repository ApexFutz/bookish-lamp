# Client Handoff Checklist

Use this checklist to transfer full ownership of bookish-lamp to the client and remove the
original developer's access. The goal: **after handoff the client owns and operates everything,
and the developer retains no access.** Work top to bottom and record the date/owner for each item.

## 1. Source code & repository
- [ ] Transfer the GitHub repository to the client's organization/account (Settings → Transfer),
      or fork+re-own and archive the original.
- [ ] Make the client an **Owner**; remove the developer from collaborators/teams.
- [ ] Rotate any repo-level secrets (Actions secrets, deploy keys, webhooks).
- [ ] Confirm CI (GitHub Actions) runs under the client's account.

## 2. Hosting & infrastructure
- [ ] Transfer or recreate the hosting app (Render/Railway/Fly/etc.) under a **client-owned**
      account with client billing.
- [ ] Transfer or recreate the managed **PostgreSQL** database under client ownership; confirm
      automated backups are enabled and retention is acceptable.
- [ ] Transfer domain/DNS and TLS to the client.
- [ ] Remove the developer's access to the hosting and database dashboards.

## 3. Secrets & credentials
- [ ] Regenerate `SECRET_KEY` and set it in the client-owned environment.
- [ ] Re-issue all `EMAIL_*` / SMTP credentials under a client-owned mailbox.
- [ ] Rotate any third-party API keys (error tracking, etc.) to client-owned accounts.
- [ ] Confirm **no secrets** live in the repo (only `.env.example` with placeholders).

## 4. Application administrators
- [ ] Client runs `python manage.py bootstrap_admin` (or has an admin) under **their** control.
- [ ] Remove or hand over any developer/demo accounts (`manager`, `admin`, `picker`, …) created
      by `seed_demo` — **do not run `seed_demo` against production.**
- [ ] Verify the client can log in, manage users/roles/tiers/equipment, and reach `/admin/`.

## 5. Knowledge transfer
- [ ] Walk the client through the [Operations Runbook](RUNBOOK.md).
- [ ] Confirm the client can independently: deploy an update, run migrations, take/restore a
      backup, and reset a locked-out user.
- [ ] Hand over the [ADR](adr/ADR-0001.md) and this repo's README.

## 6. Legal / ownership
- [ ] Confirm licensing/ownership terms are in place (see [../LICENSE](../LICENSE)).
- [ ] Sign off: ownership transferred, developer access removed.

---

**Sign-off:** ____________________  **Date:** ____________
