"""Command line generator: python -m sundialweb.cli --lat 48.78 --lon 9.18 --utc 1 -o out/"""
import argparse
from pathlib import Path

from .design import DesignParams, build_design
from .meshing import build_all


def main():
    ap = argparse.ArgumentParser(description="Generate STL files for a Bernhardt sundial")
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--utc", type=float, required=True, help="standard-time UTC offset in hours, e.g. 1 for CET")
    ap.add_argument("--label", default="", help="zone label engraved under 12, e.g. 'CET  UTC+1'")
    ap.add_argument("--radius", type=float, default=75.0, help="reading circle radius in mm")
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--first", type=int, default=None)
    ap.add_argument("--last", type=int, default=None)
    ap.add_argument("--no-engrave", action="store_true")
    ap.add_argument("-o", "--out", default="sundial_out")
    a = ap.parse_args()
    p = DesignParams(lat=a.lat, lon=a.lon, utc_offset_h=a.utc, year=a.year, scale_radius=a.radius,
                     hour_first=a.first, hour_last=a.last, zone_label=a.label)
    d = build_design(p)
    parts = build_all(d, engrave=not a.no_engrave)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    parts["dial"].export(out / "dial.stl")
    parts["stand"].export(out / "stand.stl")
    for name, mesh, _ in parts["rollers"]:
        mesh.export(out / f"{name}.stl")
    print(f"hours {d.hour_first}-{d.hour_last}, noon mark at {d.psi_noon:.2f} deg, "
          f"roller radius {d.min_roller_r:.1f}-{d.max_roller_r:.1f} mm -> {out}/")


if __name__ == "__main__":
    main()
