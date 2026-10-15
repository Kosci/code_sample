"""Command-line entry point: pull SIS enrollments, reconcile against a roster.

Demo (no setup needed; starts a local mock SIS API automatically):
    python main.py

Against a real or other server:
    python main.py --base-url https://sis.example.edu --token $SIS_TOKEN
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from mock_sis_server import API_TOKEN, base_url, make_server, start_in_thread
from reconcile import load_roster, parse_all, reconcile, write_report
from sis_client import SisApiError, SisClient

HERE = Path(__file__).parent


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--term", default="2026F", help="term code to reconcile (default: 2026F)")
    p.add_argument("--roster", default=HERE / "sample_data" / "sample_roster.csv",
                   help="downstream roster CSV (student_id,course)")
    p.add_argument("--out", default=HERE / "discrepancy_report.csv", help="report output path")
    p.add_argument("--base-url", help="SIS API base URL (omit to use the built-in mock server)")
    p.add_argument("--token", default=API_TOKEN, help="bearer token for the SIS API")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    server = None
    url = args.base_url
    if not url:
        # Fail page 2 once so the demo visibly exercises the retry logic.
        server = make_server(flaky_pages={2})
        start_in_thread(server)
        url = base_url(server)
        logging.info("Started mock SIS API at %s", url)

    try:
        client = SisClient(url, args.token, backoff=0.1)
        raw_records = list(client.iter_enrollments(args.term))
    except SisApiError as exc:
        logging.error("SIS query failed: %s", exc)
        return 2
    finally:
        if server:
            server.shutdown()

    enrollments, rejected = parse_all(raw_records)
    discrepancies = reconcile(enrollments, load_roster(args.roster))
    write_report(discrepancies, args.out)

    print(f"\nTerm {args.term}: {len(raw_records)} SIS records fetched, "
          f"{len(enrollments)} valid, {len(rejected)} rejected")
    for r in rejected:
        print(f"  REJECTED  {r.record}  ->  {r.reason}")
    print(f"\n{len(discrepancies)} discrepancies found:")
    for d in discrepancies:
        print(f"  {d.kind:<15} {d.student_id:<6} {d.course:<7} {d.detail}")
    print(f"\nReport written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
