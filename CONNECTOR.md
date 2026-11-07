# iCloud Calendar

- `custom.icloud-calendar` connects Muse to the user's iCloud calendars through Apple's CalDAV service. Apple Calendar stays the system of record and this connector is only a client.
- It talks plain HTTPS to Apple's CalDAV servers. There is no laptop process and no MCP server.
- The helper lives at `~/workspace/custom-connectors/custom.icloud-calendar/bin/icloud-calendar`. It is a single Python file with no third-party dependencies and it prints JSON.
- Discovery, iCalendar parsing and recurrence expansion are all implemented in the helper itself.
- Read this file first. It is the contract for operating this connector. Do not work around a limitation by guessing. Say what is missing and stop at that step.

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

- Guide the user through setup one step at a time. Do not paste the whole procedure at once. Tell them to make an app-specific password at appleid.apple.com, then to build the header value with setup.html on their own machine, then to paste that value into the secure form when it appears. Verify with `calendars` at the end and say when setup is done.
- CalDAV only offers HTTP Basic auth, and Muse's connector registration deposits exactly one secret. The `multi_secret` and `password` schemes were both tried on 2026-10-24 and declined by name. So the one stored secret is the complete Authorization header value, which the user builds on their own machine from their Apple ID email and an app-specific password, as README.md describes. Two-field storage with username and password kept separately is not supported by the registration today. If that changes, the CLI's `authorization_value` is the one place that changes.
- The user generates the app-specific password at appleid.apple.com and can revoke it there at any time. Its scope is CalDAV and CardDAV only.
- The same value must be registered twice. Register it once for `caldav.icloud.com` under the connection `custom.icloud-calendar`, and once for the account's partition host under the connection `custom.icloud-calendar-p<NN>`. For a host such as `p45-caldav.icloud.com` the connection is `custom.icloud-calendar-p45`. Discovery is answered by `caldav.icloud.com` itself, but the calendar collections live on `p<NN>-caldav.icloud.com`, and Muse swaps the credential only toward a host registered on the connection used for that request. A connection's hosts are fixed at first registration. Reconnecting with extra hosts did not take effect. This was verified live on 2026-10-24, when discovery answered 207, every direct partition-host request answered 401, and an anonymous control request also answered 401, so the credential itself is valid. The partition host shows in the calendar-home URL during discovery. The CLI picks the connection by request host. If Apple ever moves the account to a different partition host, register one more connection for it the same way.
- Live verification record, 2026-10-24: `calendars` returned the account's 7 calendars, and `events` on the shared calendar returned real events with recurrence expansion and the October DST change handled correctly, so reads are verified end to end. The first live REPORT exposed a bug in the connector, since fixed: the calendar-query body declared two default namespaces, which Apple rejects with HTTP 400, and the query elements are now properly prefixed. Update was exercised live later the same day by retiming an existing entry and is verified with read-back. It exposed two more bugs, both fixed: iCloud answers some UID text-match REPORTs with 412, so fetch_by_uid now falls back to a direct GET of `<uid>.ics`, and a timed value for an all-day event was silently truncated to dates, so it now converts the event to timed. A full CRUD test followed on 2026-10-24 at the user's request, on a throwaway event on the shared calendar: create, read, update with the ETag rolling, delete, and post-delete read and search confirming removal. All passed. Every operation is now verified live.
- Prove access with a harmless read before the first write in a conversation:

```text
~/workspace/custom-connectors/custom.icloud-calendar/bin/icloud-calendar calendars
```

- Discovery starts at caldav.icloud.com and the account's calendars then live on one partition host named like p45-caldav.icloud.com. If a live read fails because egress to that host is refused, reconnect with the same details plus that one partition host added to `api_hosts`. The partition host is visible in the redirect the helper reports.

## Credentials

- The registered connection holds the credential. Helpers import `/opt/muse/skills/custom-connector-setup/bin/dynamic_credentials.py`, which returns an `hsurr:` surrogate and places it where the provider reads the key. Muse swaps in the real credential only on an approved request to a registered host.
- Never put a key, token, password or cookie in this doc, a helper, a command argument, an environment variable or a log. Never ask the user to paste one in chat.
- Keep redirects disabled on authenticated requests. The helper follows a redirect manually only when the target is caldav.icloud.com or a partition host that matches the p-number pattern, and it re-issues the request so the surrogate travels with it.
- Each request times out after 30 seconds. A timeout is not proof that a write did or did not happen. Read before retrying.

## Read calendars and events

- List calendars with a live discovery on every call. Nothing is cached between calls:

```text
icloud-calendar calendars
icloud-calendar events --from 2026-10-24 --to 2026-10-31
icloud-calendar events --from 2026-10-24T00:00:00+02:00 --to 2026-10-25T00:00:00+02:00 --calendar "Family" --limit 20
icloud-calendar search --query dentist --from 2026-10-01 --to 2026-12-31
icloud-calendar get --uid <event-uid>
```

- Date-only `--from` and `--to` values cover whole days in `ICLOUD_CALENDAR_TZ` when set, otherwise Europe/Amsterdam, and `--to` is exclusive. Full ISO datetimes with an offset are honoured as given.
- Floating times with no timezone in the event are read in that same zone. When a time looks wrong, read the raw iCalendar with `get` and check it there.
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

## Recover from errors

- A 401 on a request that carried the surrogate means the app-specific password was revoked or replaced. Ask the user to generate a fresh one and reconnect with the details above. A 401 on a request without the surrogate says nothing about the credential, so check the helper attached it before reconnecting.
- Apple publishes no rate limits for CalDAV. Do not retry a 429 in a tight loop. Back off and report it.
- After a failed or timed-out change, check the current state with a read before trying again, because the first request may have completed.
- The `status` command only proves the base credential entry exists in the store. Only the `calendars` command proves live access, including the partition-host connection.

## Limits

### Auth and hosts

- One secret only. The stored secret is the complete `Authorization` header value. There is no way to store the Apple ID and the app-specific password as two fields, no OAuth flow, and no session-cookie login. Do not ask the user for either field in chat. The secure form takes the composed header value.
- Two connections hold the same value. Discovery is answered by `caldav.icloud.com`, but the calendar collections live on the account's partition host `p<NN>-caldav.icloud.com`, so the same value must also be registered under `custom.icloud-calendar-p<NN>`. A request to the partition host without its own connection is refused with 401 even though the value is correct.
- Hosts are fixed at first registration. A connection's hosts cannot be extended afterwards. If Apple moves the account to a different partition host, register one more connection for the new host the same way. Do not edit the old one and expect it to take effect.
- One Apple ID per connection pair. There is no multi-account mode. A second account needs its own connection pair and its own CLI invocation.
- The CLI only ever handles an `hsurr:` surrogate. It never sees, logs, stores or prints the real credential. Never put a key, token, password or cookie in a doc, a helper, a command argument, an environment variable or a log.

### Reads

- Nothing is cached. Every call re-runs discovery live. If Apple is unreachable, there is no last-known copy to fall back to. Report the failure instead of answering from memory.
- Date-only `--from` and `--to` cover whole days in `ICLOUD_CALENDAR_TZ` when set, otherwise Europe/Amsterdam, and `--to` is exclusive. A date-only `--to` of 2026-10-31 does not include 31 October. Full ISO datetimes with an offset are honoured as given.
- Floating times with no timezone in the event are read in that same zone. An event that looks like 09:00 in another zone is still read as 09:00 in the configured zone. Check the raw iCalendar from `get` when a time looks wrong.
- Recurrence expansion covers DAILY, WEEKLY, MONTHLY and YEARLY rules with INTERVAL, COUNT, UNTIL, BYDAY and BYMONTHDAY, plus EXDATE exclusions and RECURRENCE-ID overrides. Any other rule, for example BYSETPOS or BYWEEKNO, is returned unexpanded and flagged only by its master start. Before relying on an unusual series, read its raw iCalendar with `get` and say the expansion is unverified.
- `search` is a substring match over summary, location and description, inside the requested window only, and it returns at most 50 hits by default. It does not search outside the window, and it does not search attendees or attachments.
- `events` returns occurrences sorted by start, and `--limit` truncates after sorting. A limit therefore never hides an earlier event in favour of a later one, but it can hide later ones. Say so when a limit was applied.
- Each request times out after 30 seconds. A timeout is not proof that a write did or did not happen. Read before retrying.

### Writes

- `create` needs a named calendar, by exact name, case-insensitive, or by URL. Timed events need full ISO datetimes, and all-day events need `--all-day` with dates. There is no default calendar.
- `update` and `delete` need the event UID, and they send the ETag back as an `If-Match` precondition. An HTTP 412 means the event changed on the server since it was read. Read it again with `get` and retry. Never force the write.
- `create` sends `If-None-Match: *`, so creating an event whose object already exists fails instead of overwriting it.
- After a write, read the event back with `get` and report its final local time. If a write outcome is uncertain, read before retrying so you never create a duplicate.
- This helper never sends invitations and never notifies guests. Creating an event with guests, or any change that would notify guests, needs the user's confirmation first, matching the scheduling skill.
- This is calendars only. Tasks, reminders, contacts, mail and files are out of scope, and there is no CalDAV scheduling beyond plain event objects.

### Scope and proof

- When planning, only consult the user's own calendars and the shared family calendar. Ignore subscribed and system calendars unless the user names one.
- `status` proves only that the base credential entry exists in the store. Only `calendars` proves live access, including the partition-host connection. Prove access with a harmless read before the first write in a conversation.
- Operations verified live against the user's account are recorded in README.md. Anything not listed there is implemented and unit tested but untested live. Label it untested. Do not present it as verified.

## Related skills

- [Scheduling](/opt/muse/skills/scheduling/SKILL.md)
