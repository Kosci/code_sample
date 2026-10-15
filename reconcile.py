"""Validation and reconciliation logic (pure functions, no network access).

Keeping this separate from the API client makes the business rules easy to
unit test:

  Rule 1: A student who is `enrolled` in the SIS must appear on the roster.
  Rule 2: Anyone on the roster who is NOT `enrolled` in the SIS
          (dropped, waitlisted, or unknown) is stale and should be removed.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

VALID_STATUSES = frozenset({"enrolled", "waitlisted", "dropped"})


@dataclass(frozen=True)
class Enrollment:
    student_id: str
    course: str
    term: str
    status: str


@dataclass(frozen=True)
class Rejected:
    record: dict
    reason: str


@dataclass(frozen=True)
class Discrepancy:
    kind: str  # "missing_in_roster" | "stale_in_roster"
    student_id: str
    course: str
    detail: str


def normalize_student_id(value) -> str:
    return str(value or "").strip().upper()


def normalize_course(value) -> str:
    """'  cse 115 ' -> 'CSE115' so formatting differences don't cause false mismatches."""
    return "".join(str(value or "").split()).upper()


def parse_enrollment(raw: dict) -> Enrollment:
    """Validate and normalize one raw API record. Raises ValueError if unusable."""
    student_id = normalize_student_id(raw.get("student_id"))
    if not student_id:
        raise ValueError("missing student_id")
    course = normalize_course(raw.get("course"))
    if not course:
        raise ValueError("missing course")
    status = str(raw.get("status") or "").strip().lower()
    if status not in VALID_STATUSES:
        raise ValueError(f"unknown status {raw.get('status')!r}")
    return Enrollment(student_id, course, str(raw.get("term", "")).strip(), status)


def parse_all(raw_records: Iterable[dict]) -> tuple[list[Enrollment], list[Rejected]]:
    """Split raw records into valid enrollments and rejects (with reasons)."""
    good: list[Enrollment] = []
    bad: list[Rejected] = []
    for raw in raw_records:
        try:
            good.append(parse_enrollment(raw))
        except ValueError as exc:
            bad.append(Rejected(raw, str(exc)))
    return good, bad


def load_roster(path: str | Path) -> set[tuple[str, str]]:
    """Load a downstream roster CSV (columns: student_id, course)."""
    with open(path, newline="") as handle:
        return {
            (normalize_student_id(row["student_id"]), normalize_course(row["course"]))
            for row in csv.DictReader(handle)
        }


def reconcile(
    enrollments: Iterable[Enrollment], roster: set[tuple[str, str]]
) -> list[Discrepancy]:
    """Compare SIS enrollments with a downstream roster; return sorted discrepancies."""
    enrollments = list(enrollments)
    status_by_key = {(e.student_id, e.course): e.status for e in enrollments}
    expected = {key for key, status in status_by_key.items() if status == "enrolled"}

    results = [
        Discrepancy("missing_in_roster", sid, course, "enrolled in SIS but absent from roster")
        for sid, course in sorted(expected - roster)
    ]
    for sid, course in sorted(roster - expected):
        status = status_by_key.get((sid, course))
        detail = f"SIS status is '{status}'" if status else "no matching SIS record"
        results.append(Discrepancy("stale_in_roster", sid, course, detail))
    return results


def write_report(discrepancies: Iterable[Discrepancy], path: str | Path) -> None:
    fields = ["kind", "student_id", "course", "detail"]
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(asdict(d) for d in discrepancies)
