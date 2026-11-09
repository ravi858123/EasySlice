"""EasySlice kern: model laden, schalen, slicen (lagen, wanden, infill, supports) en G-code."""
import math
import numpy as np
import trimesh
from shapely import affinity
from shapely.geometry import Polygon, MultiLineString
from shapely.ops import unary_union

PRESETS = {
    "Snel (0.30 mm)":    dict(layer=0.30, first=0.30, walls=2, top=3, bottom=3, infill=10, speed=90, outer=60, first_speed=25),
    "Normaal (0.20 mm)": dict(layer=0.20, first=0.30, walls=3, top=4, bottom=4, infill=15, speed=60, outer=40, first_speed=20),
    "Detail (0.10 mm)":  dict(layer=0.10, first=0.20, walls=3, top=6, bottom=6, infill=20, speed=35, outer=25, first_speed=15),
}
SUPPORT_MODES = ["geen", "alleen vanaf bouwplaat", "overal"]
ADHESION = ["skirt", "brim", "geen"]

DEFAULTS = dict(
    bed_x=220.0, bed_y=220.0, bed_z=250.0, nozzle=0.4, fil=1.75, hotend=210.0, bed_temp=60.0,
    travel=150.0, retract=5.0, retract_speed=35.0, fan=100.0, flow=100.0,
    sx=100.0, sy=100.0, sz=100.0, rot_z=0.0,
    support="geen", support_angle=50.0, support_spacing=2.5, support_gap=0.4,
    adhesion="skirt", brim=5.0,
    **PRESETS["Normaal (0.20 mm)"])


def load_mesh(path):
    m = trimesh.load(path, force="mesh")
    if not isinstance(m, trimesh.Trimesh) or len(m.faces) == 0:
        raise ValueError("Geen bruikbaar 3D-model (met vlakken) gevonden in dit bestand.")
    return m


def _rot(s):
    a = math.radians(s["rot_z"])
    c, n = math.cos(a), math.sin(a)
    return np.array([[c, -n, 0], [n, c, 0], [0, 0, 1.0]])


def extents(mesh, s):
    v = (mesh.vertices @ _rot(s).T) * np.array([s["sx"], s["sy"], s["sz"]]) / 100
    return v.max(0) - v.min(0)


def fit_percent(mesh, s):
    e = extents(mesh, dict(s, sx=100, sy=100, sz=100))
    return min((s["bed_x"] - 10) / e[0], (s["bed_y"] - 10) / e[1], s["bed_z"] / e[2]) * 100


def prepare(mesh, s):
    m = mesh.copy()
    M = np.eye(4)
    M[:3, :3] = np.diag([s["sx"], s["sy"], s["sz"]]) / 100 @ _rot(s)
    m.apply_transform(M)
    lo, hi = m.bounds
    m.apply_translation([s["bed_x"] / 2 - (lo[0] + hi[0]) / 2, s["bed_y"] / 2 - (lo[1] + hi[1]) / 2, -lo[2]])
    return m


def _region(p):
    """Even-odd vulling van alle gesloten lussen in een doorsnede."""
    r = Polygon()
    if p is None:
        return r
    for loop in p.discrete:
        if len(loop) >= 3:
            r = r.symmetric_difference(Polygon(loop).buffer(0))
    return r


def _polys(g):
    return [p for p in getattr(g, "geoms", [g]) if p.geom_type == "Polygon" and not p.is_empty]


def _rings(g, holes=True):
    out = []
    for p in _polys(g):
        out.append(list(p.exterior.coords))
        if holes:
            out += [list(i.coords) for i in p.interiors]
    return out


def _hatch(region, spacing, angle):
    if region.is_empty:
        return []
    a = math.radians(angle)
    c, sn = math.cos(a), math.sin(a)
    r = affinity.rotate(region, -angle, origin=(0, 0))
    minx, miny, maxx, maxy = r.bounds
    ys = np.arange(math.ceil(miny / spacing) * spacing, maxy, spacing)
    if len(ys) == 0:
        return []
    inter = r.intersection(MultiLineString([[(minx - 1, y), (maxx + 1, y)] for y in ys]))
    rows = {}
    for g in getattr(inter, "geoms", [inter]):
        if g.geom_type != "LineString" or g.length < 0.4:
            continue
        (x1, y1), (x2, _) = g.coords[0], g.coords[-1]
        rows.setdefault(round(y1, 3), []).append((min(x1, x2), max(x1, x2)))
    out = []
    for idx, y in enumerate(sorted(rows)):
        segs = sorted(rows[y])
        if idx % 2:
            segs = [(b, a_) for a_, b in reversed(segs)]
        for x1, x2 in segs:
            out.append([(x1 * c - y * sn, x1 * sn + y * c), (x2 * c - y * sn, x2 * sn + y * c)])
    return out


def _supports(regions, ths, s, w):
    n = len(regions)
    sup = [Polygon() for _ in range(n)]
    if s["support"] == "geen" or n < 3:
        return sup
    tn = math.tan(math.radians(s["support_angle"]))
    gap = s["support_gap"]
    below = None
    if s["support"].startswith("alleen"):
        below, acc = [], Polygon()
        for r in regions:
            below.append(acc)
            acc = unary_union([acc, r])
    cur = Polygon()
    for i in range(n - 1, 0, -1):
        over = regions[i].difference(regions[i - 1].buffer(tn * ths[i]))
        cur = unary_union([cur, over]).difference(regions[i - 1].buffer(gap))
        j = i - 2  # één laag vrij tussen support en model
        if j < 0:
            continue
        c = cur.buffer(-w).buffer(w).difference(regions[j].buffer(gap))
        if below is not None:
            c = c.difference(below[j].buffer(gap))
        sup[j] = c
    return sup


def slice_model(mesh, s, progress=lambda f, t: None):
    m = prepare(mesh, s)
    w = s["nozzle"] * 1.1
    h, h0 = s["layer"], s["first"]
    top = m.bounds[1][2]
    tops = [min(h0, top)]
    while tops[-1] + h * 0.5 < top:
        tops.append(min(tops[-1] + h, top))
    ths = [tops[0]] + [b - a for a, b in zip(tops, tops[1:])]
    mids = [t - th / 2 for t, th in zip(tops, ths)]
    n = len(tops)

    progress(0.03, "Doorsnijden…")
    secs = m.section_multiplane([0, 0, 0], [0, 0, 1], mids)
    regions = []
    for i, p in enumerate(secs):
        regions.append(_region(p))
        if i % 20 == 0:
            progress(0.03 + 0.2 * i / n, "Lagen opbouwen…")
    nw, nt, nb = int(s["walls"]), int(s["top"]), int(s["bottom"])
    inner = [r.buffer(-w * nw) for r in regions]

    progress(0.25, "Supports berekenen…")
    sup = _supports(regions, ths, s, w)

    layers = []
    for i in range(n):
        paths = []
        r = regions[i]
        if i == 0 and s["adhesion"] != "geen":
            base = unary_union([r, sup[0]])
            if not base.is_empty:
                if s["adhesion"] == "brim":
                    for j in range(max(1, int(s["brim"] / w))):
                        paths += [("skirt", x) for x in _rings(base.buffer(w * (j + 0.5)), holes=False)]
                else:
                    for j in range(2):
                        g = base.buffer(6 + w * (j + 0.5)).simplify(0.2)
                        paths += [("skirt", x) for x in _rings(g, holes=False)]
        if not sup[i].is_empty:
            paths += [("support", x) for x in _rings(sup[i].buffer(-w * 0.5))]
            for seg in _hatch(sup[i].buffer(-w), s["support_spacing"], 0 if i % 2 == 0 else 90):
                paths.append(("support", seg))
        for k in range(nw - 1, -1, -1):
            kind = "outer" if k == 0 else "inner"
            paths += [(kind, x) for x in _rings(r.buffer(-w * (k + 0.5)))]
        if not inner[i].is_empty:
            ang = 45 if i % 2 == 0 else 135
            if i < nb or i + nt >= n:
                solid = inner[i]
            else:
                solid = inner[i].difference(inner[i + nt]).union(inner[i].difference(inner[i - nb]))
            for seg in _hatch(solid, w, ang):
                paths.append(("solid", seg))
            if s["infill"] > 0:
                sparse = inner[i].difference(solid.buffer(w * 0.5))
                for seg in _hatch(sparse, w / (s["infill"] / 100), ang):
                    paths.append(("infill", seg))
        layers.append(dict(z=tops[i], th=ths[i], paths=paths))
        if i % 5 == 0:
            progress(0.3 + 0.65 * i / n, f"Laag {i + 1}/{n}")
    progress(1.0, "Klaar")
    return layers


def write_gcode(layers, s):
    w = s["nozzle"] * 1.1
    fa = math.pi * (s["fil"] / 2) ** 2
    ret, rs, tv = s["retract"], s["retract_speed"], s["travel"]
    L = ["; Gemaakt met EasySlice",
         f"M140 S{s['bed_temp']:.0f}", f"M104 S{s['hotend']:.0f}",
         f"M190 S{s['bed_temp']:.0f}", f"M109 S{s['hotend']:.0f}",
         "G28", "G90", "M83", "M107", "G92 E0"]
    st = dict(x=0.0, y=0.0, ret=False, e=0.0, t=0.0)

    def travel(px, py):
        d = math.hypot(px - st["x"], py - st["y"])
        if d > 1.5 and not st["ret"]:
            L.append(f"G1 E-{ret:.2f} F{rs * 60:.0f}")
            st["ret"] = True
        L.append(f"G0 X{px:.3f} Y{py:.3f} F{tv * 60:.0f}")
        st["t"] += d / tv
        st["x"], st["y"] = px, py

    for li, lay in enumerate(layers):
        L.append(f";LAYER:{li}")
        if li == 1:
            L.append(f"M106 S{int(255 * s['fan'] / 100)}")
        if not st["ret"]:
            L.append(f"G1 E-{ret:.2f} F{rs * 60:.0f}")
            st["ret"] = True
        L.append(f"G0 Z{lay['z']:.3f} F600")
        th = lay["th"]
        epm = ((w - th) * th + math.pi * (th / 2) ** 2) / fa * s["flow"] / 100
        for kind, pts in lay["paths"]:
            if li == 0:
                v = s["first_speed"]
            else:
                v = s["outer"] if kind == "outer" else s["speed"]
            travel(*pts[0])
            if st["ret"]:
                L.append(f"G1 E{ret:.2f} F{rs * 60:.0f}")
                st["ret"] = False
            first = True
            for px, py in pts[1:]:
                d = math.hypot(px - st["x"], py - st["y"])
                e = d * epm
                L.append(f"G1 X{px:.3f} Y{py:.3f} E{e:.4f}" + (f" F{v * 60:.0f}" if first else ""))
                first = False
                st["e"] += e
                st["t"] += d / v
                st["x"], st["y"] = px, py
    L += ["M107", "M104 S0", "M140 S0", f"G1 E-{ret:.2f} F{rs * 60:.0f}",
          "G91", "G1 Z10 F600", "G90", f"G0 X0 Y{s['bed_y']:.0f} F{tv * 60:.0f}", "M84"]
    return "\n".join(L) + "\n", dict(time=st["t"], filament=st["e"], grams=st["e"] * fa / 1000 * 1.24)
