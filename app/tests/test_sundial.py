import math
from datetime import datetime, timezone

import numpy as np
import pytest
import trimesh

from sundialweb import solar
from sundialweb.design import DesignParams, build_design, closest_point_to_axis, accuracy_report
from sundialweb.meshing import BodyGeometry, build_all, build_roller, build_dial


STUTTGART = dict(lat=48.7758, lon=9.1829, utc_offset_h=1.0, year=2026)


def test_equation_of_time_reference_values():
    for (m, d, eot_ref) in [(11, 3, 16.4), (2, 11, -14.2), (6, 21, -1.8), (12, 21, 1.9)]:
        t = solar.dt_to_unix(datetime(2026, m, d, 12, tzinfo=timezone.utc))
        _, eot = solar.sun_geometry(t)
        assert abs(eot - eot_ref) < 0.25, (m, d, eot)


def test_solstice_instants():
    dec_prev, jun, dec = solar.solstices(2026)
    assert abs(jun - solar.dt_to_unix(datetime(2026, 6, 21, 8, 24, tzinfo=timezone.utc))) < 3600
    assert abs(dec - solar.dt_to_unix(datetime(2026, 12, 21, 20, 50, tzinfo=timezone.utc))) < 3600
    assert abs(dec_prev - solar.dt_to_unix(datetime(2025, 12, 21, 15, 3, tzinfo=timezone.utc))) < 3600


def test_hemispheres_and_hour_range():
    dn = build_design(DesignParams(**STUTTGART))
    ds = build_design(DesignParams(lat=-33.9, lon=151.2, utc_offset_h=10.0, year=2026))
    assert dn.omega == 1.0 and ds.omega == -1.0
    assert (dn.hour_first, dn.hour_last) == (4, 21)
    assert ds.hour_first <= 5 and ds.hour_last >= 19
    assert dn.min_roller_r == pytest.approx(4.0, abs=0.01)
    for rp in dn.rollers:
        assert np.all(np.diff(rp.z) > 0)
        assert rp.r.min() >= 3.99


@pytest.fixture(scope="module")
def stuttgart():
    d = build_design(DesignParams(scale_radius=75.0, zone_label="CET  UTC+1", **STUTTGART))
    g = BodyGeometry.for_radius(75.0)
    return d, g


def _roller_in_dial_frame(d, g, k, sections=96):
    m, info = build_roller(d, g, d.rollers[k], grooves=k + 1)
    m = m.copy()
    m.apply_translation([0, 0, info["pin_bottom_z_dial"]])
    return m


def _sun_dial(d, unix_s):
    return solar.enu_to_dial(solar.sun_vector_enu(unix_s, d.params.lat, d.params.lon), d.params.lat)


def _mark(d, T, offset_min=0.0):
    psi = math.radians(float(d.psi_of_time(T)) + d.omega * offset_min / 4.0)
    return np.array([d.R * math.sin(psi), d.R * math.cos(psi), 0.0])


def _in_shadow_analytic(d, roller, mark, s, n=4000):
    """True if the ray mark + lambda*s passes through the roller profile."""
    lam = np.linspace(0.0, 2.2 * d.R, n)
    pts = mark[None, :] + lam[:, None] * s[None, :]
    rr = np.hypot(pts[:, 0], pts[:, 1])
    rp = np.interp(pts[:, 2], roller.z, roller.r, left=-1, right=-1)
    return bool(np.any(rr < rp - 1e-9))


def test_shadow_edge_hits_the_minute_analytic(stuttgart):
    """Bisection on the mark angle: where does lit turn into shadow?  Away
    from the solstices the leading shadow edge must sit on the mean-time mark
    within 0.3 minutes; within 25 days of a solstice the overlapping ray
    hyperboloids limit any roller to a few minutes (Glaeser & Hofmann 2004)."""
    d, g = stuttgart
    worst_mid, worst_all = 0.0, 0.0
    for k, (m0, m1) in enumerate([(1, 6), (7, 12)]):
        rp = d.rollers[k]
        t0, t1 = rp.days.min(), rp.days.max()
        for month in range(m0, m1 + 1):
            for day in (5, 20):
                for hour in (6, 8, 10, 12, 14, 16, 18, 20):
                    t = solar.zone_time_to_unix(2026, month, day, hour, 1.0)
                    if not (t0 <= t <= t1):
                        continue
                    s_enu = solar.sun_vector_enu(t, d.params.lat, d.params.lon)
                    if s_enu[2] < 0.02:
                        continue
                    s = _sun_dial(d, t)
                    lo, hi = -6.0, 6.0  # minutes; lo must be shadow, hi must be lit
                    assert _in_shadow_analytic(d, rp, _mark(d, hour, lo), s)
                    assert not _in_shadow_analytic(d, rp, _mark(d, hour, hi), s)
                    for _ in range(14):
                        mid = 0.5 * (lo + hi)
                        if _in_shadow_analytic(d, rp, _mark(d, hour, mid), s):
                            lo = mid
                        else:
                            hi = mid
                    e = abs(0.5 * (lo + hi))
                    worst_all = max(worst_all, e)
                    if min(t - t0, t1 - t) > 25 * 86400:
                        worst_mid = max(worst_mid, e)
    print("worst edge error (minutes): mid-season", worst_mid, "overall", worst_all)
    assert worst_mid < 0.3
    assert worst_all < 3.5
    rep = accuracy_report(d, 1.0)
    assert all(abs(r["max_error_min"]) < 3.5 for r in rep)


def test_shadow_edge_on_mesh(stuttgart):
    """Same check with real rays against the revolved roller mesh."""
    d, g = stuttgart
    for k, samples in enumerate([[(2, 10, 9), (3, 25, 14), (5, 15, 17)], [(7, 20, 10), (9, 10, 12), (11, 5, 14)]]):
        roller = _roller_in_dial_frame(d, g, k)
        assert roller.is_watertight
        ray = trimesh.ray.ray_triangle.RayMeshIntersector(roller)
        for (month, day, hour) in samples:
            t = solar.zone_time_to_unix(2026, month, day, hour, 1.0)
            s = _sun_dial(d, t)
            behind = _mark(d, hour, -0.6)
            ahead = _mark(d, hour, +0.6)
            hit = ray.intersects_any(np.vstack([behind, ahead]), np.vstack([s, s]))
            assert hit[0], (month, day, hour, "mark 0.6 min behind should be in shadow")
            assert not hit[1], (month, day, hour, "mark 0.6 min ahead should be lit")


def test_dial_body_does_not_block_the_sun(stuttgart):
    """Rays from the reading marks towards the sun must clear the dial body
    (wings, hub) for all usable hours.  The only exception is the low sun of
    the first/last hour of the day for a couple of weeks around the
    equinoxes, when it skims the opposite wing tip (as on the original)."""
    d, g = stuttgart
    dial, info = build_dial(d, g, engrave=False)
    ray = trimesh.ray.ray_triangle.RayMeshIntersector(dial)
    origins, dirs, tags = [], [], []
    for month in range(1, 13):
        for day in (4, 18):
            for hour in range(d.hour_first, d.hour_last + 1):
                t = solar.zone_time_to_unix(2026, month, day, hour, 1.0)
                if solar.sun_vector_enu(t, d.params.lat, d.params.lon)[2] < math.sin(math.radians(2.0)):
                    continue
                s = _sun_dial(d, t)
                m = _mark(d, hour, 0.0)
                origins.append(m + 0.6 * s); dirs.append(s); tags.append((month, day, hour))
    hit = ray.intersects_any(np.array(origins), np.array(dirs))
    blocked = [tg for tg, h in zip(tags, hit) if h]
    frac = len(blocked) / len(tags)
    print(f"blocked {len(blocked)} of {len(tags)} samples: {blocked}")
    assert frac < 0.10
    for (month, day, hour) in blocked:
        near_equinox = month in (2, 3, 4, 9, 10)
        at_equinox = (month, day) in {(3, 18), (9, 18)}   # sun in the scale plane: any hour may graze a wing
        edge_hour = hour <= d.hour_first + 5 or hour >= d.hour_last - 5
        assert near_equinox and (edge_hour or at_equinox), (month, day, hour)
    # the analytic report agrees: only ranges around the equinoxes
    from sundialweb.meshing import shadowed_days_report
    rep = shadowed_days_report(d, g, info["surface"])
    assert all(r["days"] <= 60 for r in rep), rep
    assert all(r["from"][3:] in ("Feb", "Mar", "Apr", "Sep", "Oct") for r in rep), rep


def test_all_parts_are_continuous(stuttgart):
    """Proof of continuity: every part is watertight and a single connected
    body, and the dial's top surface has no step larger than 3 mm between
    neighbouring samples (half a degree / half a millimetre apart)."""
    from sundialweb.meshing import continuity_report
    d, g = stuttgart
    parts = build_all(d, g)
    rep = continuity_report(parts)
    for name, r in rep.items():
        assert r["watertight"], name
        assert r["components"] == 1, (name, r)
        assert r["volume_mm3"] > 0, name
    assert rep["dial"]["max_step_mm_per_half_degree"] < 3.0, rep["dial"]
    assert rep["dial"]["max_step_mm_per_half_mm"] < 3.0, rep["dial"]
    assert rep["dial"]["max_inner_edge_step_mm"] <= 1.0 + 1e-6, rep["dial"]


def test_all_parts_watertight(stuttgart):
    d, g = stuttgart
    parts = build_all(d, g)
    assert parts["dial"].is_watertight and parts["dial"].volume > 0
    assert parts["stand"].is_watertight and parts["stand"].volume > 0
    for name, m, info in parts["rollers"]:
        assert m.is_watertight and m.volume > 0
        assert m.bounds[0][2] == pytest.approx(0.0, abs=1e-6)


def test_api_generate(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import sundialweb.api as api
    monkeypatch.setattr(api, "CACHE_DIR", tmp_path)
    client = TestClient(api.app)
    r = client.get("/api/timezone", params={"lat": 48.7758, "lon": 9.1829})
    assert r.status_code == 200 and r.json()["utc_offset_h"] == 1.0
    r = client.post("/api/generate", json={"lat": 48.7758, "lon": 9.1829, "utc_offset_h": 1.0,
                                           "zone_label": "CET  UTC+1", "scale_radius": 50.0, "year": 2026})
    assert r.status_code == 200, r.text
    info = r.json()
    for url in list(info["files"].values()) + [info["zip"]]:
        f = client.get(url)
        assert f.status_code == 200 and len(f.content) > 1000
    r = client.get("/api/sun", params={"lat": 48.7758, "lon": 9.1829, "utc_offset_h": 1, "year": 2026, "month": 6, "day": 21})
    assert r.status_code == 200 and len(r.json()["hours"]) == 288


@pytest.mark.parametrize("lat,lon", [(10.0, 0.0), (30.0, 31.2), (-34.6, -58.4), (64.1, -21.9)])
def test_stand_does_not_tip(lat, lon):
    """The pebble base must carry the assembled dial with a safety margin:
    the whole assembly can be tilted TIP_ANGLE_REQ_DEG in any direction
    before its centre of mass leaves the footprint."""
    from sundialweb.meshing import TIP_ANGLE_REQ_DEG, load_masses, _dial_to_stand
    d = build_design(DesignParams(lat=lat, lon=lon, utc_offset_h=0.0))
    parts = build_all(d)
    stab = parts["stand_info"]["stability"]
    assert stab["tip_angle_deg"] >= TIP_ANGLE_REQ_DEG - 0.5, stab
    assert stab["margin_mm"] >= 8.0, stab
    # independent check of the centre of mass from the real meshes
    g = parts["geometry"]
    loads = load_masses(d, g, parts["dial"], parts["rollers"], parts["dial_info"])
    stand = parts["stand"]
    V = sum(v for v, _ in loads) + stand.volume
    com = (sum(v * np.asarray(c) for v, c in loads) + stand.volume * np.asarray(stand.center_mass)) / V
    a_x, a_yp, a_ym = parts["stand_info"]["base_semi_axes"]
    y_f = parts["stand_info"]["base_centre_y"]
    dy = com[1] - y_f
    a_y = a_yp if dy > 0 else a_ym
    side = a_x * math.sqrt(max(1.0 - (dy / a_y) ** 2, 0.0)) - abs(com[0])
    margin = min(a_yp - dy, a_ym + dy, side)
    assert math.degrees(math.atan2(margin, com[2])) >= TIP_ANGLE_REQ_DEG - 1.0, (com, parts["stand_info"]["base_semi_axes"])
    assert stand.bounds[0][2] == pytest.approx(0.0, abs=1e-6)


def test_roller_screws_into_the_hub(stuttgart):
    """Male and female thread are the same helix offset by the clearance:
    seated on the hub with the phase aligned, the roller and the dial must
    not overlap, and the roller must be free to turn (no overlap either at
    a quarter turn less deep)."""
    d, g = stuttgart
    parts = build_all(d, g)
    dial = parts["dial"]
    name, roller, inf = parts["rollers"][0]
    assert inf["thread"]["turns"] >= 3
    best = None
    for phase in np.linspace(0, 2 * np.pi, 24, endpoint=False):
        r = roller.copy()
        r.apply_transform(trimesh.transformations.rotation_matrix(phase, [0, 0, 1]))
        r.apply_translation([0, 0, parts["dial_info"]["hub_top_z"] - g.pin_len])
        inter = trimesh.boolean.intersection([dial, r], engine="manifold")
        v = 0.0 if inter.is_empty else float(inter.volume)
        best = v if best is None else min(best, v)
    assert best < 0.5, best
    # the thread holds: with the roller backed out by a quarter pitch and turned
    # by a quarter turn against the helix, the ridges overlap the hub material
    r = roller.copy()
    r.apply_translation([0, 0, parts["dial_info"]["hub_top_z"] - g.pin_len + g.thread_pitch / 2])
    inter = trimesh.boolean.intersection([dial, r], engine="manifold")
    assert (0.0 if inter.is_empty else float(inter.volume)) > 5.0
