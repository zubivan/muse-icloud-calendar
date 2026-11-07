# AGENTS.md

Notes for coding agents working on this repo. The user-facing docs are
`README.md`; the operator contract Muse follows at runtime is
`CONNECTOR.md` — its Limits section is authoritative. Do not weaken
a limitation to make a feature work; if a limitation blocks the task,
say so.

## Layout

- `bin/icloud-calendar` — the whole connector: one Python file, stdlib
  only, executable (`100755`). No dependencies to install.
- `tests/test_icloud_calendar.py` — offline unit tests (parser, RRULE
  expansion, multistatus XML, ICS building, setup page). No network,
  no credentials.
- `CONNECTOR.md` — the doc Muse reads to operate the service.
- `connector.yaml` — the connector descriptor (`custom.icloud-calendar`).
- `setup.html` — offline setup helper. It must never load or send
  anything: no `fetch(`, `XMLHttpRequest`, `WebSocket`, `sendBeacon`,
  `<script src`, or `http://` / `https://` anywhere in the file.
  There is a test enforcing this. Muse shows it inline in the chat
  during setup with `widget.create_html_file_widget` on this file.
  The browser-file route is the fallback.

## Commands

```sh
python3 -m unittest discover -s tests   # offline tests; must pass
python3 -m py_compile bin/icloud-calendar
./bin/icloud-calendar status            # base credential entry present?
./bin/icloud-calendar calendars        # live discovery; proves both connections
```

Live checks need the registered credential connections and touch the
real account. Reads are harmless. Never run a live write except a
throwaway event on purpose, and delete it right after, verifying the
removal with a read/search.

## Hard rules

- No secrets, ever: no key, token, password or cookie in code, docs,
  tests, command arguments, environment variables or logs. The CLI only
  ever handles an `hsurr:` surrogate from `dynamic_credentials.py`.
  Test fixtures use the RFC 7617 example (`Aladdin` / `open sesame`)
  and the placeholder `you@icloud.com` — nothing real.
- Auth is exactly one secret: the complete `Authorization` header
  value. The partition-host connection name is derived from the
  discovered host (`partition_credential`), never hardcoded to one
  account's host.
- Redirects are never followed automatically. Manual follow only to
  `caldav.icloud.com` or a `p<NN>-caldav.icloud.com` host, at most
  4 hops.
- Writes use ETag preconditions (`If-Match` on update/delete,
  `If-None-Match: *` on create). A 412 means re-read and retry, never
  force. After an uncertain write, read before retrying — never create
  a duplicate.
- The helper never sends invitations and never notifies guests.
- Floating times and date-only values use `ICLOUD_CALENDAR_TZ`
  (default Europe/Amsterdam). Do not hardcode another zone.
- Keep the CLI stdlib-only and single-file. If a change needs a new
  dependency, stop and discuss it first.
- When a change affects behaviour, update the tests, the Limits
  section in `CONNECTOR.md`, and the short list in `README.md` in the
  same change.
