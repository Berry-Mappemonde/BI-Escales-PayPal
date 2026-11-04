"""Follow: the journal and layer reasons stay up to the clock, without exception text."""
import json
from datetime import datetime, timedelta, timezone

import voyage_journal as journal


def test_entries_until_returns_every_past_day():
    journal.reset()
    t0 = datetime(2026, 5, 15, 8, tzinfo=timezone.utc)
    folder = journal.journal_dir()
    for i in range(10):
        day = (t0 + timedelta(days=i)).strftime("%Y-%m-%d")
        entries = []
        for hour in (0, 6, 12, 18):
            entries.append({
                "id": f"{day}-{hour}",
                "t": f"{day}T{hour:02d}:00:00Z",
                "kind": "position",
                "lat": 46.0 - i,
                "lon": -1.0,
            })
        (folder / f"{day}.json").write_text(json.dumps(entries), encoding="utf-8")
    (folder / "2026-12-01.json").write_text(json.dumps([{
        "id": "future",
        "t": "2026-12-01T00:00:00Z",
        "kind": "position",
    }]), encoding="utf-8")
    now = t0 + timedelta(days=9, hours=2)
    rows = journal.entries_until(now, limit=60)
    assert len(rows) > 1
    assert rows[0]["t"] >= rows[-1]["t"]
    assert all(row["id"] != "future" for row in rows)
    assert rows[-1]["t"].startswith("2026-05-15")

    import official_store
    official_store.put("moments", {
        "moments": [{"t": "2026-05-15T00:00:00Z", "signature": "kept"}],
        "journal": {
            "count": 1,
            "latest": [{
                "id": "only",
                "t": "2026-05-17T12:00:00Z",
                "kind": "position",
                "lat": 43.3,
                "lon": -8.4,
                "name": "La Coruna",
            }],
            "events": [],
            "days": [{"day": "2026-05-17", "count": 1}],
        },
        "journal_days": {
            "2026-05-15": [{"id": "a", "t": "2026-05-15T08:00:00Z", "kind": "position"}],
            "2026-05-16": [{"id": "b", "t": "2026-05-16T08:00:00Z", "kind": "position"}],
            "2026-05-17": [{"id": "c", "t": "2026-05-17T12:00:00Z", "kind": "stop", "name": "La Coruna"}],
        },
    })
    served = official_store.serve_journal(60)
    assert len(served["latest"]) > 1
    assert served["latest"][0]["t"] >= served["latest"][-1]["t"]
    assert served["days"][0]["day"] == "2026-05-15"
    assert len(served["days"]) > 1
    assert any(row.get("id") == "only" for row in served["latest"])

    moments = official_store.serve_moments()
    sigs = {row.get("signature") for row in moments["moments"]}
    assert "kept" in sigs
    assert moments["count"] >= 3
    # A day the moments already cover is not listed a second time from the journal.
    first_day = [row.get("signature") for row in moments["moments"] if str(row.get("t")).startswith("2026-05-15")]
    assert first_day == ["kept"]


def test_layer_code_has_no_exception_repr():
    from ici_layers import layer_code

    reason = layer_code("overpass_unavailable", "HTTPStatusError")
    assert "HTTPStatusError" not in reason
    assert "<" not in reason
    assert "Traceback" not in reason
    assert reason.startswith("overpass_unavailable")
    ugly = layer_code("aton_unavailable", "<class 'httpx.HTTPStatusError'>")
    assert "HTTPStatusError" not in ugly
    assert "<" not in ugly
    assert layer_code("cdse_stac_unavailable", 503) == "cdse_stac_unavailable:503"
    assert layer_code("cdse_stac_unavailable", "503") == "cdse_stac_unavailable:503"
    assert layer_code("rtofs_unavailable", "rtofs_no_cycle") == "rtofs_unavailable:rtofs_no_cycle"
    assert layer_code("", "HTTPStatusError") == "unavailable"
    assert layer_code("depth_sample_unavailable", "no_data") == "depth_sample_unavailable:no_data"
