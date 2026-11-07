# iCloud Calendar

Read this file first. It is the contract for operating this connector: what it does, which hosts it may call, and the limitations in the Limitations section below. Do not work around a limitation by guessing — say what is missing and stop at that step.

- `custom.icloud-calendar` connects Muse to the user's iCloud calendars through Apple's CalDAV service. Apple Calendar stays the system of record and this connector is only a client.

- The helper lives at `~/workspace/custom-connectors/custom.icloud-calendar/bin/icloud-calendar`. It is a single Python file with no third-party dependencies and it prints JSON.

- The design mirrors a direct CalDAV client. Discovery, iCalendar parsing and recurrence expansion are all implemented in the helper itself.

## Connection details

| Item | Value |
|---|---|
| Transport | Plain HTTPS against Apple's CalDAV servers. No laptop process, no MCP server. |
| Auth | Exactly one secret: the complete `Authorization` header value (`Basic <base64(Apple ID + ":" + app-specific password)>`). No username/password fields, no OAuth, no session cookies. |
| Credential connections | Two, holding the same value: `custom.icloud-calendar` for `caldav.icloud.com`, and `custom.icloud-calendar-p<NN>` for the account's partition host `p<NN>-caldav.icloud.com`. |
| Allowed hosts | `caldav.icloud.com` and `p<NN>-caldav.icloud.com` (partition numbers 1–299). Nothing else. |
| Timezone | Floating times and date-only values are read in `ICLOUD_CALENDAR_TZ` when set (an IANA zone name), otherwise Europe/Amsterdam. |
| Request timeout | 30 seconds per request. |
| Redirects | Never followed automatically. Followed manually only to `caldav.icloud.com` or a `p<NN>-caldav.icloud.com` host, at most 4 hops. |
| Rate limits | None published by Apple for CalDAV. Do not retry a 429 in a tight loop; back off and report it. |
| Privacy | The helper never logs, stores or prints credential material. It only ever sees an `hsurr:` surrogate, which Muse swaps for the real credential on egress, only toward a registered host. |

## Connect

- The connection is registered with `credentials.request_api_access`. Reuse these exact details for a reconnect because the scheme and placement cannot change afterwards:

```json
{
  "provider": "icloud-calendar",
  "auth_scheme": "api_key",
  "placement": "custom_header:Authorization",
  "api_hosts": ["caldav.icloud.com"]
}
```

- CalDAV only offers HTTP Basic auth, and Muse's connector registration deposits exactly one secret. The `multi_secret` and `password` schemes were both tried on 2026-10-24 and declined by name. So the one stored secret is the complete Authorization header value, which the user builds on their own machine from their Apple ID email and an app-specific password, as README.md describes. Two-field (username + password) storage is not supported by the registration today; if that changes, the CLI's `authorization_value` is the one place that changes.

- The user generates the app-specific password at appleid.apple.com and can revoke it there at any time. Its scope is CalDAV and CardDAV only.

- The same value must be registered **twice**: once for `caldav.icloud.com` (connection `custom.icloud-calendar`) and once for the account's partition host (connection `custom.icloud-calendar-p<NN>`, e.g. `p45-caldav.icloud.com` → `custom.icloud-calendar-p45`). Discovery is answered by `caldav.icloud.com` itself, but the calendar collections live on `p<NN>-caldav.icloud.com`, and Muse swaps the credential only toward a host registered on the connection used for that request. A connection's hosts are fixed at first registration — reconnecting with extra hosts did not take effect (verified live 2026-10-24: discovery 207, every direct partition-host request 401, anonymous control also 401, so the credential itself is valid). The partition host shows in the calendar-home URL during discovery. The CLI picks the connection by request host. If Apple ever moves the account to a different partition host, register one more connection for it the same way.

- Live verification record, 2026-10-24: `calendars` returned the account's 7 calendars, and `events` on the shared calendar returned real events with recurrence expansion and the October DST change handled correctly — reads are verified end to end. The first live REPORT exposed a bug in the connector, since fixed: the calendar-query body declared two default namespaces, which Apple rejects with HTTP 400; the query elements are now properly prefixed. Update was exercised live later the same day (retiming an existing entry) and is verified with read-back; it exposed two more bugs, both fixed: iCloud answers some UID text-match REPORTs with 412 (fetch_by_uid now falls back to a direct GET of `<uid>.ics`), and a timed value for an all-day event was silently truncated to dates (it now converts the event to timed). A full CRUD test followed on 2026-10-24 at the user's request (throwaway event on the shared calendar): create, read, update (ETag rolled), delete, and post-delete read/search confirming removal — all passed. Every operation is now verified live.

- Prove access with a harmless read before the first write in a conversation:

```text
~/workspace/custom-connectors/custom.icloud-calendar/bin/icloud-calendar calendars
```

- Discovery starts at caldav.icloud.com and the account's calendars then live on one partition host named like p45-caldav.icloud.com. If a live read fails because egress to that host is refused, reconnect with the same details plus that one partition host added to `api_hosts`. The partition host is visible in the redirect the helper reports.

## Credentials

- The registered connection holds the credential. Helpers import `/opt/muse/skills/custom-connector-setup/bin/dynamic_credentials.py`, which returns an `hsurr:` surrogate and places it where the provider reads the key. Muse swaps in the real credential only on an approved request to a registered host.

- Never put a key, token, password or cookie in this doc, a helper, a command argument, an environment variable or a log. Never ask the user to paste one in chat.

- Keep redirects disabled on authenticated requests. The helper follows a redirect manually only when the target is caldav.icloud.com or a partition host that matches the p-number pattern, and it re-issues the request so the surrogate travels with it.

## Read calendars and events

- List calendars with a live discovery on every call. Nothing is cached between calls:

```text
icloud-calendar calendars
icloud-calendar events --from 2026-10-24 --to 2026-10-31
icloud-calendar events --from 2026-10-24T00:00:00+02:00 --to 2026-10-25T00:00:00+02:00 --calendar "Family" --limit 20
icloud-calendar search --query dentist --from 2026-10-01 --to 2026-12-31
icloud-calendar get --uid <event-uid>
```

- Date-only `--from` and `--to` values cover whole days in `ICLOUD_CALENDAR_TZ` (default Europe/Amsterdam) and `--to` is exclusive. Full ISO datetimes with an offset are honoured as given.

- Recurring events are expanded into occurrences inside the window. The expansion covers daily, weekly, monthly and yearly rules with interval, count, until, byday and bymonthday, plus exdate exclusions and recurrence overrides. Rules outside that set are returned unexpanded and flagged only by their master start, so check the raw iCalendar from `get` before relying on an unusual series.

- Each event carries its calendar name, href and etag. Keep the uid, href and etag unchanged for a later write.

- When planning for the user, only consult the user's own calendars and the shared family calendar. Ignore subscribed and system calendars unless the user names one.

## Create, change or delete an event

- Create with a named calendar. Timed events need full ISO datetimes and all-day events use `--all-day` with dates:

```text
icloud-calendar create --calendar "Family" --summary "Dentist" --start 2026-11-02T14:30:00+01:00 --end 2026-11-02T15:30:00+01:00
icloud-calendar create --calendar "Family" --summary "Trip" --start 2026-12-24 --end 2026-12-27 --all-day
icloud-calendar update --uid <event-uid> --location "Clinic"
icloud-calendar delete --uid <event-uid>
```

- Updates and deletes send the etag back as an If-Match precondition. An HTTP 412 reply means the event changed on the server since it was read. Read it again with `get` and retry instead of forcing the write.

- Creating an event with guests, and any change that would notify guests, needs the user's confirmation first, matching the scheduling skill. This helper does not send invitations itself.

- After a write, read the event back with `get` and report its final local time. If a write outcome is uncertain, read before retrying so you never create a duplicate.

## Limitations — read before acting

These are hard limits, not preferences. Do not work around them by guessing, retrying blindly, or substituting another source.

### Auth and hosts

1. One secret only. The stored secret is the complete `Authorization` header value. There is no way to store the Apple ID and the app-specific password as two fields, no OAuth flow, and no session-cookie login. Do not ask the user for either field in chat; the secure form takes the composed header value.
2. Two connections, same value. Discovery is answered by `caldav.icloud.com`, but the calendar collections live on the account's partition host `p<NN>-caldav.icloud.com`, so the same value must also be registered under `custom.icloud-calendar-p<NN>`. A request to the partition host without its own connection is refused (401) even though the value is correct.
3. Hosts are fixed at first registration. A connection's hosts cannot be extended afterwards. If Apple moves the account to a different partition host, register one more connection for the new host the same way — do not edit the old one and expect it to take effect.
4. One Apple ID per connection pair. There is no multi-account mode. A second account needs its own connection pair and its own CLI invocation.
5. The CLI only ever handles an `hsurr:` surrogate. It never sees, logs, stores or prints the real credential. Never put a key, token, password or cookie in a doc, a helper, a command argument, an environment variable or a log.

### Reads

6. Nothing is cached. Every call re-runs discovery live. If Apple is unreachable, there is no last-known copy to fall back to — report the failure instead of answering from memory.
7. Date-only `--from` / `--to` cover whole days in `ICLOUD_CALENDAR_TZ` (default Europe/Amsterdam), and `--to` is exclusive. A date-only `--to` of 2026-10-31 does not include 31 October. Full ISO datetimes with an offset are honoured as given.
8. Floating times (no timezone in the event) are read in that same zone. An event that looks like 09:00 in another zone is still read as 09:00 in the configured zone — check the raw iCalendar from `get` when a time looks wrong.
9. Recurrence expansion covers DAILY, WEEKLY, MONTHLY and YEARLY rules with INTERVAL, COUNT, UNTIL, BYDAY and BYMONTHDAY, plus EXDATE exclusions and RECURRENCE-ID overrides. Any other rule (for example BYSETPOS or BYWEEKNO) is returned unexpanded and flagged only by its master start. Before relying on an unusual series, read its raw iCalendar with `get` and say the expansion is unverified.
10. `search` is a substring match over summary, location and description, inside the requested window only, and it returns at most 50 hits by default. It does not search outside the window, and it does not search attendees or attachments.
11. `events` returns occurrences sorted by start; `--limit` truncates after sorting. A limit therefore never hides an earlier event in favour of a later one, but it can hide later ones — say so when a limit was applied.
12. Each request times out after 30 seconds. A timeout is not proof that a write did or did not happen — read before retrying (see 16).

### Writes

13. `create` needs a named calendar (exact name, case-insensitive, or URL). Timed events need full ISO datetimes; all-day events need `--all-day` with dates. There is no default calendar.
14. `update` and `delete` need the event UID, and they send the ETag back as an `If-Match` precondition. An HTTP 412 means the event changed on the server since it was read: read it again with `get` and retry. Never force the write.
15. `create` sends `If-None-Match: *`, so creating an event whose object already exists fails instead of overwriting it.
16. After a write, read the event back with `get` and report its final local time. If a write outcome is uncertain (timeout, unclear error), read before retrying so you never create a duplicate.
17. This helper never sends invitations and never notifies guests. Creating an event with guests, or any change that would notify guests, needs the user's confirmation first, matching the scheduling skill.
18. This is calendars only. Tasks, reminders, contacts, mail and files are out of scope, and there is no CalDAV scheduling (free-busy, invitations) beyond plain event objects.

### Scope and proof

19. When planning, only consult the user's own calendars and the shared family calendar. Ignore subscribed and system calendars unless the user names one.
20. `status` proves only that the base credential entry exists in the store. Only `calendars` proves live access, including the partition-host connection. Prove access with a harmless read before the first write in a conversation.
21. Operations verified live against the user's account are recorded in README.md. Anything not listed there is implemented and unit tested but untested live — label it untested, do not present it as verified.

## Limits and recovery

- A 401 on a request that carried the surrogate means the app-specific password was revoked or replaced. Ask the user to generate a fresh one and reconnect with the details above. A 401 on a request without the surrogate says nothing about the credential, so check the helper attached it before reconnecting.

- The `status` command only proves the base credential entry exists in the store. Only the `calendars` command proves live access, including the partition-host connection.

- Operations verified live against the user's account are recorded in README.md. Anything not listed there is implemented and unit tested but untested live.

## Related skills

- [Scheduling](/opt/muse/skills/scheduling/SKILL.md)
