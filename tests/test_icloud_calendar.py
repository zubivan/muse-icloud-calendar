"""Offline tests for the icloud-calendar CLI.

No network, no credentials: these cover the iCalendar parser, the RRULE
expansion, the CalDAV multistatus parsing and the ICS serializer, all against
fixtures. Live behaviour is verified separately against the real account
(see CONNECTOR.md) and is not faked here.

Run: python3 -m pytest tests/ -q   (or: python3 -m unittest discover tests)
"""

import importlib.util
import pathlib
import sys
import unittest
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

BIN = pathlib.Path(__file__).resolve().parent.parent / "bin" / "icloud-calendar"
_spec = importlib.util.spec_from_loader("icloud_calendar", loader=None)
mod = importlib.util.module_from_spec(_spec)
# The CLI is an extensionless script; load it as source.
import importlib.machinery
_loader = importlib.machinery.SourceFileLoader("icloud_calendar", str(BIN))
_spec = importlib.util.spec_from_loader("icloud_calendar", _loader)
mod = importlib.util.module_from_spec(_spec)
sys.modules["icloud_calendar"] = mod
_loader.exec_module(mod)

AMS = ZoneInfo("Europe/Amsterdam")

SAMPLE = (
    "BEGIN:VCALENDAR\r\n"
    "VERSION:2.0\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:test-1@example\r\n"
    "SUMMARY:Team\\, sync; weekly\r\n"
    "DTSTART;TZID=Europe/Amsterdam:20261026T090000\r\n"
    "DTEND;TZID=Europe/Amsterdam:20261026T100000\r\n"
    "LOCATION:Office\\nRoom 2\r\n"
    "RRULE:FREQ=WEEKLY;COUNT=3\r\n"
    "END:VEVENT\r\n"
    "END:VCALENDAR\r\n"
)

MULTISTATUS = b"""<?xml version="1.0" encoding="utf-8"?>
<multistatus xmlns="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <response>
    <href>/12345/calendars/home/abc.ics</href>
    <propstat><prop>
      <getetag>"etag-1"</getetag>
      <c:calendar-data>BEGIN:VCALENDAR&#13;
VERSION:2.0&#13;
BEGIN:VEVENT&#13;
UID:u1&#13;
SUMMARY:One&#13;
DTSTART:20261024T100000Z&#13;
DTEND:20261024T110000Z&#13;
END:VEVENT&#13;
END:VCALENDAR&#13;
</c:calendar-data>
    </prop><status>HTTP/1.1 200 OK</status></propstat>
  </response>
</multistatus>"""


class ParseTests(unittest.TestCase):
    def test_unfold_and_props(self):
        events = mod.parse_ical(SAMPLE)
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev.uid, "test-1@example")
        self.assertEqual(ev.summary, "Team, sync; weekly")
        self.assertEqual(ev.get_text("LOCATION"), "Office\nRoom 2")
        start, is_date = ev.start()
        self.assertFalse(is_date)
        self.assertEqual(start, datetime(2026, 10, 26, 9, 0, tzinfo=AMS))

    def test_folded_line(self):
        text = ("BEGIN:VEVENT\r\nUID:x\r\n"
                "SUMMARY:A very long summary that was fold\r\n ed here\r\n"
                "DTSTART:20261024T100000Z\r\nDTEND:20261024T110000Z\r\n"
                "END:VEVENT\r\n")
        ev = mod.parse_ical(text)[0]
        self.assertEqual(ev.summary, "A very long summary that was folded here")

    def test_all_day_default_end(self):
        text = ("BEGIN:VEVENT\r\nUID:x\r\nSUMMARY:Holiday\r\n"
                "DTSTART;VALUE=DATE:20261024\r\nEND:VEVENT\r\n")
        ev = mod.parse_ical(text)[0]
        start, is_date = ev.start()
        end, _ = ev.end(start, is_date)
        self.assertTrue(is_date)
        self.assertEqual(start, date(2026, 10, 24))
        self.assertEqual(end, date(2026, 10, 25))


class ExpandTests(unittest.TestCase):
    def test_weekly_count(self):
        ev = mod.parse_ical(SAMPLE)[0]
        occ = mod.expand_event(
            ev,
            datetime(2026, 10, 26, tzinfo=timezone.utc),
            datetime(2026, 11, 30, tzinfo=timezone.utc))
        self.assertEqual(len(occ), 3)
        self.assertEqual([o["start"].day for o in occ], [26, 2, 9])

    def test_daily_until_and_exdate(self):
        text = ("BEGIN:VEVENT\r\nUID:x\r\nSUMMARY:Daily\r\n"
                "DTSTART:20261024T080000Z\r\nDTEND:20261024T083000Z\r\n"
                "RRULE:FREQ=DAILY;UNTIL=20261027T235959Z\r\n"
                "EXDATE:20261025T080000Z\r\nEND:VEVENT\r\n")
        ev = mod.parse_ical(text)[0]
        occ = mod.expand_event(
            ev,
            datetime(2026, 10, 24, tzinfo=timezone.utc),
            datetime(2026, 11, 1, tzinfo=timezone.utc))
        self.assertEqual([o["start"].day for o in occ], [24, 26, 27])

    def test_monthly_nth_weekday(self):
        text = ("BEGIN:VEVENT\r\nUID:x\r\nSUMMARY:Board\r\n"
                "DTSTART;TZID=Europe/Amsterdam:20261013T100000\r\n"
                "DTEND;TZID=Europe/Amsterdam:20261013T110000\r\n"
                "RRULE:FREQ=MONTHLY;BYDAY=2TU;COUNT=3\r\nEND:VEVENT\r\n")
        ev = mod.parse_ical(text)[0]
        occ = mod.expand_event(
            ev,
            datetime(2026, 10, 1, tzinfo=timezone.utc),
            datetime(2027, 2, 1, tzinfo=timezone.utc))
        self.assertEqual([(o["start"].month, o["start"].day) for o in occ],
                         [(10, 13), (11, 10), (12, 8)])

    def test_non_recurring_outside_window(self):
        ev = mod.parse_ical(SAMPLE.replace(
            "RRULE:FREQ=WEEKLY;COUNT=3\r\n", ""))[0]
        occ = mod.expand_event(
            ev,
            datetime(2026, 12, 1, tzinfo=timezone.utc),
            datetime(2026, 12, 31, tzinfo=timezone.utc))
        self.assertEqual(occ, [])


class AuthTests(unittest.TestCase):
    def test_authorization_value_is_standard_basic(self):
        # RFC 7617 example credentials.
        self.assertEqual(mod.authorization_value("Aladdin", "open sesame"),
                         "Basic QWxhZGRpbjpvcGVuIHNlc2FtZQ==")

    def test_credential_is_single_header_entry(self):
        self.assertEqual(mod.CREDENTIAL, "custom.icloud-calendar")
        self.assertEqual(mod.ENTRY, "access_token")

    def test_partition_credential_derived_from_host(self):
        # The partition host is per-account; its connection name is
        # derived from it, never hardcoded to one account's host.
        self.assertEqual(
            mod.partition_credential("p45-caldav.icloud.com"),
            "custom.icloud-calendar-p45")
        self.assertEqual(
            mod.partition_credential("p45-caldav.icloud.com"),
            "custom.icloud-calendar-p45")


class WireTests(unittest.TestCase):
    def test_multistatus(self):
        items = mod._parse_multistatus(MULTISTATUS)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["etag"], "etag-1")
        ev = mod.parse_ical(items[0]["ical"])[0]
        self.assertEqual(ev.summary, "One")

    def test_build_roundtrip(self):
        ical = mod.build_ical(
            "u9@muse", "Dentist, check-up",
            datetime(2026, 11, 2, 14, 30, tzinfo=AMS),
            datetime(2026, 11, 2, 15, 30, tzinfo=AMS),
            location="Clinic; North")
        ev = mod.parse_ical(ical)[0]
        self.assertEqual(ev.summary, "Dentist, check-up")
        self.assertEqual(ev.get_text("LOCATION"), "Clinic; North")
        start, _ = ev.start()
        self.assertEqual(start.hour, 14)

    def test_build_all_day(self):
        ical = mod.build_ical("u10@muse", "Trip", date(2026, 12, 24),
                              date(2026, 12, 27), all_day=True)
        self.assertIn("DTSTART;VALUE=DATE:20261224", ical)
        self.assertIn("DTEND;VALUE=DATE:20261227", ical)


class SetupPageTests(unittest.TestCase):
    def test_setup_page_is_fully_offline(self):
        """The setup helper must never be able to send what the user types."""
        page = (pathlib.Path(__file__).resolve().parent.parent
                / "setup.html").read_text(encoding="utf-8")
        for forbidden in ("fetch(", "XMLHttpRequest", "WebSocket",
                          "sendBeacon", "<script src", "http://",
                          "https://"):
            self.assertNotIn(forbidden, page)
        self.assertIn("toBase64", page)


if __name__ == "__main__":
    unittest.main()
