# muse-icloud-calendar

A Muse custom connector for iCloud Calendar over CalDAV. It talks CalDAV
directly to Apple's servers, with a self-contained iCalendar parser, no
third-party libraries (Python standard library only), and Apple Calendar
remains the system of record.

## Layout

| File | Who it is for |
|---|---|
| `CONNECTOR.md` | Muse itself. The operating contract: connection details, commands, and the full Limitations section. Read it first. |
| `connector.yaml` | The connector descriptor (`custom.icloud-calendar`). |
| `bin/icloud-calendar` | The CLI (single file, stdlib only). |
| `tests/` | Offline unit tests for the parser, RRULE expansion and the CalDAV multistatus reader. |
| `setup.html` | Offline, single-file setup helper that builds the header value in the browser. Loads and sends nothing. |

Install by placing this folder at
`~/workspace/custom-connectors/custom.icloud-calendar/`.

## Commands

```text
icloud-calendar status                                   # credential entry present?
icloud-calendar calendars                                # live discovery + list
icloud-calendar events   --from DATE --to DATE [--calendar NAME] [--limit N]
icloud-calendar search   --query TEXT --from DATE --to DATE
icloud-calendar get      --uid UID
icloud-calendar create   --calendar NAME --summary TEXT --start ISO --end ISO
                         [--all-day] [--location TEXT] [--description TEXT]
                         [--rrule "FREQ=WEEKLY;COUNT=4"]
icloud-calendar update   --uid UID [--summary TEXT] [--location TEXT]
                         [--description TEXT] [--start ISO] [--end ISO]
icloud-calendar delete   --uid UID
```

All output is JSON. Recurring events are expanded into occurrences inside
the requested window (DAILY / WEEKLY / MONTHLY / YEARLY with INTERVAL,
COUNT, UNTIL, BYDAY, BYMONTHDAY, EXDATE and RECURRENCE-ID overrides).

## Authentication: credentials store only

There is no credential in this repo, in any file, or in any environment
variable. The CLI asks Muse's `dynamic_credentials` helper for an
`hsurr:` surrogate and sends only that. Muse swaps the surrogate for the
real credential on egress, and only toward a registered host.

CalDAV offers exactly one auth scheme: HTTP Basic with the Apple ID and
an **app-specific password**. Muse's connector registration deposits
exactly one secret — the `multi_secret` and `password` schemes are both
declined by name (checked 2026-10-24) — so the stored secret is the
complete `Authorization` header value. This is also the pattern public
Muse guides document for Basic-auth services.

1. At [appleid.apple.com](https://appleid.apple.com) → Sign-In and Security →
   App-Specific Passwords, generate a password for this connector.
   Revocable there at any time, scoped to CalDAV/CardDAV only: no mail,
   photos or account access, and never the real Apple ID password.
2. Build the header value on your own device — no terminal needed.
   Open **`setup.html`** from this repo in any browser: it is one
   self-contained file that works with the internet switched off, loads
   and sends nothing, and is short enough to read in full. Type your
   Apple ID email and the app-specific password, tap “Build my value”,
   and copy the result. Spaces are removed automatically.

   Prefer a terminal? The page performs exactly this composition
   (`authorization_value()` in `bin/icloud-calendar`, unit tested
   against the RFC 7617 example):

   ```sh
   printf 'Basic %s' "$(printf '%s' 'you@icloud.com:xxxx-xxxx-xxxx-xxxx' | base64)"
   ```
3. Register the connection in Muse with:
   - provider: `icloud-calendar`
   - auth scheme: `api_key`
   - placement: `custom_header:Authorization`
   - hosts: `caldav.icloud.com`
   and paste that `Basic …` string as the key in the secure form.
4. Verify with `icloud-calendar calendars`.

Discovery starts at `caldav.icloud.com`; the account's collections then live
on a partition host (`p<NN>-caldav.icloud.com`). If egress to that host is
refused, reconnect adding that single host to the registered hosts, under
a second connection named `custom.icloud-calendar-p<NN>` holding the same
value — the CLI derives that name from the discovered host.

Floating times (no timezone in the event) and date-only values are read
in `ICLOUD_CALENDAR_TZ` when set (an IANA zone name), otherwise in
Europe/Amsterdam.

## Tests

```sh
python3 -m unittest discover -s tests
```

Offline only: parsing, recurrence expansion, multistatus XML, ICS building.
Live verification is a separate, explicit step against the real account.
## Security notes

- Authenticated requests never auto-follow redirects. The CLI follows a
  redirect manually only to `caldav.icloud.com` or a `p<NN>-caldav.icloud.com`
  host, re-issuing the request with the surrogate attached.
- Writes use ETag preconditions (`If-Match` on update/delete,
  `If-None-Match: *` on create), so a stale write fails with 412 instead of
  overwriting a newer copy.
- Nothing here logs, stores or prints credential material. Surrogates are
  the only credential-shaped values the process ever sees.

## License

Apache 2.0 — see `LICENSE`.
