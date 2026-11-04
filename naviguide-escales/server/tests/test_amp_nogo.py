from amp_nogo import amp_nogo_fn, load_forbidden_nogo, reset_nogo_cache
from isochrone import combine_nogo

SQUARE = {
    "type": "Feature",
    "properties": {"site_id": "NOGO-1", "name": "Parc interdit", "entry": 1, "speed": 3},
    "geometry": {
        "type": "Polygon",
        "coordinates": [[
            [-2.0, 46.0], [-1.5, 46.0], [-1.5, 46.3], [-2.0, 46.3], [-2.0, 46.0],
        ]],
    },
}


def test_amp_nogo_blocks_inside_and_spares_escape():
    reset_nogo_cache()
    items = load_forbidden_nogo(fetch_fn=lambda: {"features": [SQUARE]})
    blocked = amp_nogo_fn(items)
    assert blocked(46.15, -1.75, None) is True
    assert blocked(46.15, -1.16, None) is False
    escape = amp_nogo_fn(items, escape_points=[(46.15, -1.75)])
    assert escape(46.15, -1.75, None) is False


def test_combine_nogo_is_or():
    wind = lambda lat, lon, t: lon < -4
    amp = lambda lat, lon, t: 46.0 < lat < 46.3 and -2.0 < lon < -1.5
    fn = combine_nogo(wind, amp)
    assert fn(46.15, -1.75, None) is True
    assert fn(46.15, -5.0, None) is True
    assert fn(46.15, -1.16, None) is False
