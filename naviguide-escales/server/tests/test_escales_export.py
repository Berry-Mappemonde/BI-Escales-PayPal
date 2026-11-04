"""Export JSON /escales/export pour BI Escales."""
from __future__ import annotations

import escales_export


def test_build_export_from_minimal_marks():
    marks = [
        {"name": "Mayotte", "lat": -12.7, "lon": 45.2, "iso": "2026-09-01T08:00:00Z", "flag": True},
    ]
    payload = escales_export.export_from_marks(marks, {"t0": "2026-05-15T08:00:00Z", "marks": marks})
    assert payload["version"] == escales_export.EXPORT_VERSION
    by_id = {row["milestone_id"]: row for row in payload["escales"]}
    assert by_id["dep-mayotte"]["arrival_iso"]


def test_milestone_id_for_name():
    assert escales_export.milestone_id_for_name("Fort-de-France") == "dep-fort-de-france"
