"""Unit and integration tests. Run with:  python -m unittest -v"""
import unittest

import mock_sis_server as mock
from reconcile import Discrepancy, Enrollment, parse_all, parse_enrollment, reconcile
from sis_client import SisApiError, SisClient


class ParsingTests(unittest.TestCase):
    def test_normalizes_formatting(self):
        e = parse_enrollment({"student_id": " s1008 ", "course": "cse 115", "term": "2026F", "status": "Enrolled"})
        self.assertEqual(e, Enrollment("S1008", "CSE115", "2026F", "enrolled"))

    def test_rejects_missing_id_and_unknown_status(self):
        good, bad = parse_all([
            {"student_id": "", "course": "CSE115", "status": "enrolled"},
            {"student_id": "S1", "course": "CSE115", "status": "audit"},
            {"student_id": "S2", "course": "CSE115", "status": "enrolled"},
        ])
        self.assertEqual(len(good), 1)
        self.assertEqual([r.reason for r in bad], ["missing student_id", "unknown status 'audit'"])


class ReconcileTests(unittest.TestCase):
    def setUp(self):
        self.enrollments = [
            Enrollment("S1", "CSE115", "2026F", "enrolled"),
            Enrollment("S2", "CSE115", "2026F", "dropped"),
            Enrollment("S3", "CSE115", "2026F", "waitlisted"),
        ]

    def test_in_sync_has_no_discrepancies(self):
        self.assertEqual(reconcile(self.enrollments, {("S1", "CSE115")}), [])

    def test_missing_in_roster(self):
        result = reconcile(self.enrollments, set())
        self.assertEqual([(d.kind, d.student_id) for d in result], [("missing_in_roster", "S1")])

    def test_stale_in_roster_covers_dropped_waitlisted_and_unknown(self):
        roster = {("S1", "CSE115"), ("S2", "CSE115"), ("S3", "CSE115"), ("S9", "CSE115")}
        result = reconcile(self.enrollments, roster)
        self.assertEqual(
            [(d.student_id, d.detail) for d in result],
            [("S2", "SIS status is 'dropped'"),
             ("S3", "SIS status is 'waitlisted'"),
             ("S9", "no matching SIS record")],
        )


class ClientTests(unittest.TestCase):
    def start(self, **kwargs):
        server = mock.make_server(**kwargs)
        mock.start_in_thread(server)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server

    def client(self, server, token=mock.API_TOKEN, **kwargs):
        return SisClient(mock.base_url(server), token, sleep=lambda s: None, **kwargs)

    def test_follows_pagination_and_filters_by_term(self):
        server = self.start()
        records = list(self.client(server).iter_enrollments("2026F", page_size=4))
        self.assertEqual(len(records), 14)  # the one 2027S row is excluded
        self.assertTrue(all(r["term"] == "2026F" for r in records))

    def test_retries_transient_503_then_succeeds(self):
        server = self.start(flaky_pages={2})
        records = list(self.client(server).iter_enrollments("2026F", page_size=5))
        self.assertEqual(len(records), 14)

    def test_gives_up_after_max_retries(self):
        server = self.start()
        server.shutdown()
        server.server_close()
        with self.assertRaises(SisApiError):
            list(self.client(server, max_retries=1).iter_enrollments("2026F"))

    def test_bad_token_fails_fast_without_retry(self):
        server = self.start()
        sleeps = []
        client = SisClient(mock.base_url(server), "wrong", sleep=sleeps.append)
        with self.assertRaises(SisApiError) as ctx:
            list(client.iter_enrollments("2026F"))
        self.assertEqual(ctx.exception.status, 401)
        self.assertEqual(sleeps, [])  # 401 must not trigger retries


if __name__ == "__main__":
    unittest.main()
