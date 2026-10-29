"""Privacy-safe interactive grid map for classroom result releases.

The map draws the ACTIVSg2000 network as a schematic graph.  Each bus is
colored by the total MW *served* to all scored teams there (service fraction
x connection capacity, from the evaluator output), so no individual team's
plan is shown and rejected or dropped requests do not appear.  When dispatch results are supplied,
each branch is colored by its peak loading (largest ``|flow| / limit`` over the
evaluated hours).  Hovering a bus shows its name and how its load at the
system peak hour splits into the existing base load and the new data-center
load served to all teams together (never per team); hovering a line shows
its end buses, limit, and loading.  A small script draws these hover boxes and
adds pan and zoom, so the SVG is interactive in any browser.

The scenario package has no bus coordinates, so the layout is a deterministic
force-directed embedding of the network graph.  It is computed once and stored
as JSON so maps from different rounds share the same picture.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from html import escape
from pathlib import Path


LAYOUT_VERSION = "activsg2000-schematic-layout-v1"
NEAR_LIMIT_FRACTION = 0.99


@dataclass(frozen=True)
class MapBranch:
    branch_id: str
    from_bus_id: str
    to_bus_id: str
    limit_mw: float


def load_network(artifact_dir: str | Path) -> tuple[tuple[str, ...], tuple[MapBranch, ...], dict[str, float]]:
    """Return bus IDs, in-service branches, and base load by bus for one block."""
    root = Path(artifact_dir)
    with (root / "bus.csv").open(newline="", encoding="utf-8") as handle:
        bus_ids = tuple(row["bus_id"] for row in csv.DictReader(handle))
    branches = []
    with (root / "branch_limits.csv").open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("status", "1") != "1":
                continue
            branches.append(
                MapBranch(row["branch_id"], row["from_bus_id"], row["to_bus_id"], float(row["thermal_limit_mva"]))
            )
    base_load: dict[str, float] = {}
    load_path = root / "bus_load_base.csv"
    if load_path.is_file():
        with load_path.open(newline="", encoding="utf-8") as handle:
            base_load = {row["bus_id"]: float(row["base_load_mw"]) for row in csv.DictReader(handle)}
    return bus_ids, tuple(branches), base_load


def compute_layout(
    bus_ids: Sequence[str],
    branches: Sequence[MapBranch],
    *,
    iterations: int = 300,
    seed: int = 0,
) -> dict[str, tuple[float, float]]:
    """Deterministic force-directed layout scaled to the unit square.

    A spectral embedding of the graph Laplacian gives the starting positions;
    Fruchterman-Reingold iterations then spread the nodes out.
    """
    import numpy as np

    n = len(bus_ids)
    if n == 0:
        return {}
    index = {bus_id: i for i, bus_id in enumerate(bus_ids)}
    edges = np.array(
        [(index[b.from_bus_id], index[b.to_bus_id]) for b in branches
         if b.from_bus_id in index and b.to_bus_id in index and b.from_bus_id != b.to_bus_id],
        dtype=int,
    ).reshape(-1, 2)
    adjacency = np.zeros((n, n))
    if len(edges):
        adjacency[edges[:, 0], edges[:, 1]] = 1.0
        adjacency[edges[:, 1], edges[:, 0]] = 1.0
    laplacian = np.diag(adjacency.sum(axis=1)) - adjacency
    rng = np.random.default_rng(seed)
    if n > 3:
        _, vectors = np.linalg.eigh(laplacian + 1e-9 * np.eye(n))
        position = vectors[:, 1:3].copy()
    else:
        position = rng.random((n, 2))
    position += 1e-3 * rng.standard_normal((n, 2))
    position -= position.mean(axis=0)
    position /= np.abs(position).max() or 1.0

    k = np.sqrt(4.0 / n)
    temperature = 0.1
    cooling = temperature / (iterations + 1)
    for _ in range(iterations):
        delta = position[:, None, :] - position[None, :, :]
        distance = np.sqrt((delta ** 2).sum(axis=-1))
        np.fill_diagonal(distance, 1.0)
        distance = np.maximum(distance, 1e-3)
        force = k * k / distance ** 2 - adjacency * distance / k
        np.fill_diagonal(force, 0.0)
        displacement = (delta * force[:, :, None]).sum(axis=1)
        length = np.maximum(np.sqrt((displacement ** 2).sum(axis=1)), 1e-9)
        position += displacement / length[:, None] * np.minimum(length, temperature)[:, None]
        temperature -= cooling

    position -= position.min(axis=0)
    position /= position.max(axis=0).max() or 1.0
    return {bus_id: (round(float(position[i, 0]), 5), round(float(position[i, 1]), 5)) for bus_id, i in index.items()}


def load_or_create_layout(
    layout_path: str | Path,
    bus_ids: Sequence[str],
    branches: Sequence[MapBranch],
) -> dict[str, tuple[float, float]]:
    """Read a stored layout, or compute and store one when the file is absent."""
    path = Path(layout_path)
    if path.is_file():
        payload = json.loads(path.read_text(encoding="utf-8"))
        positions = {bus_id: (float(x), float(y)) for bus_id, (x, y) in payload["positions"].items()}
        missing = set(bus_ids) - set(positions)
        if missing:
            raise ValueError(f"layout {path} is missing {len(missing)} buses")
        return positions
    positions = compute_layout(bus_ids, branches)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"layout_version": LAYOUT_VERSION, "positions": positions}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return positions


def load_bus_names(layout_path: str | Path) -> dict[str, str]:
    """Bus names stored with a layout file (empty when the layout has none)."""
    path = Path(layout_path)
    if not path.is_file():
        return {}
    return {str(k): str(v) for k, v in json.loads(path.read_text(encoding="utf-8")).get("bus_names", {}).items()}


def peak_hour_demand(artifact_dir: str | Path) -> tuple[dict[str, float], int | None]:
    """Existing load per bus in the period with the highest total system load.

    Reads ``demand_bus.csv`` (one row per period, one column per bus).  Returns
    ``({bus_id: MW}, period)``, or ``({}, None)`` when the file is absent.
    """
    path = Path(artifact_dir) / "demand_bus.csv"
    if not path.is_file():
        return {}, None
    best_total, best_row, best_period = None, None, None
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            period = int(row.pop("period"))
            values = {bus: float(value) for bus, value in row.items()}
            total = sum(values.values())
            if best_total is None or total > best_total:
                best_total, best_row, best_period = total, values, period
    return best_row or {}, best_period


def load_layout_background(layout_path: str | Path) -> tuple[list[list[tuple[float, float]]], str | None]:
    """Optional outline paths and layout kind stored with a layout file.

    Geographic layouts (``data/teaching/activsg2000_geo_layout_v1.json``) carry a
    ``background_paths`` outline, such as the Texas border, in the same unit
    coordinates as the bus positions.
    """
    path = Path(layout_path)
    if not path.is_file():
        return [], None
    payload = json.loads(path.read_text(encoding="utf-8"))
    paths = [[(float(x), float(y)) for x, y in polyline] for polyline in payload.get("background_paths", [])]
    return paths, payload.get("provenance", {}).get("kind")


def served_load_by_bus(evaluation_dirs: Iterable[str | Path]) -> tuple[dict[str, float], int]:
    """Sum the MW served to every scored site per bus over evaluator outputs.

    Reads each output's ``site_net_withdrawal.csv``, which lists only sites
    of teams that were scored feasible, at their projected load (service
    fraction x connection capacity).  Rejected files (including Submission 2
    files that reuse a Submission 1 site ID) and infeasible teams are not in
    it; a site allocated nothing is served 0 MW and adds nothing.  A site's served MW is its largest hourly load (the projected
    capacity for a flat CSV site).  Only per-bus totals are returned; team
    and site identifiers are discarded.  Returns ``(totals, served_sites)``.
    """
    from .base_load import read_site_net_withdrawal

    totals: dict[str, float] = {}
    served_sites = 0
    for directory in evaluation_dirs:
        peak: dict[tuple[str, str], tuple[str, float]] = {}
        for row in read_site_net_withdrawal(directory):
            key = (str(row["team_id"]), str(row["site_id"]))
            previous = peak.get(key, (row["bus_id"], 0.0))[1]
            peak[key] = (str(row["bus_id"]), max(previous, float(row["load_mw"])))
        for bus_id, mw in peak.values():
            if mw > 1e-9:
                served_sites += 1
                totals[bus_id] = totals.get(bus_id, 0.0) + mw
    return totals, served_sites


def branch_loading(
    dispatch_dir: str | Path,
    branches: Sequence[MapBranch],
) -> tuple[dict[str, tuple[float, int]], int]:
    """Peak loading and hours near the limit for each branch.

    Reads every ``period_*.json`` in ``dispatch_dir`` (the evaluator's dispatch
    output).  Returns ``{branch_id: (peak |flow|/limit, hours >= 99%)}`` and the
    number of hours read.
    """
    limits = {branch.branch_id: branch.limit_mw for branch in branches if branch.limit_mw > 0}
    peak = dict.fromkeys(limits, 0.0)
    near = dict.fromkeys(limits, 0)
    hours = 0
    for path in sorted(Path(dispatch_dir).glob("period_*.json")):
        flows = json.loads(path.read_text(encoding="utf-8")).get("flow_mw_by_branch", {})
        hours += 1
        for branch_id, limit in limits.items():
            ratio = abs(float(flows.get(branch_id, 0.0))) / limit
            if ratio > peak[branch_id]:
                peak[branch_id] = ratio
            if ratio >= NEAR_LIMIT_FRACTION:
                near[branch_id] += 1
    return {branch_id: (peak[branch_id], near[branch_id]) for branch_id in limits}, hours


def bus_prices(dispatch_dir: str | Path) -> tuple[dict[str, float], dict[str, float]]:
    """Average and highest LMP per bus over the evaluated hours ($/MWh).

    Reads ``balance_dual_by_bus`` from every ``period_*.json`` in ``dispatch_dir``.
    Prices are system outputs and reveal nothing about any team's plan.
    """
    total: dict[str, float] = {}
    peak: dict[str, float] = {}
    hours = 0
    for path in sorted(Path(dispatch_dir).glob("period_*.json")):
        prices = json.loads(path.read_text(encoding="utf-8")).get("balance_dual_by_bus", {})
        if not prices:
            continue
        hours += 1
        for bus_id, value in prices.items():
            value = float(value)
            total[bus_id] = total.get(bus_id, 0.0) + value
            peak[bus_id] = max(peak.get(bus_id, value), value)
    if not hours:
        return {}, {}
    return {bus_id: value / hours for bus_id, value in total.items()}, peak


def peak_flow_sign(dispatch_dir: str | Path, branches: Sequence[MapBranch]) -> dict[str, float]:
    """Sign (+1 or -1) of each branch's flow in the hour of its largest |flow|."""
    best: dict[str, float] = {}
    for path in sorted(Path(dispatch_dir).glob("period_*.json")):
        flows = json.loads(path.read_text(encoding="utf-8")).get("flow_mw_by_branch", {})
        for branch in branches:
            flow = float(flows.get(branch.branch_id, 0.0))
            if abs(flow) > abs(best.get(branch.branch_id, 0.0)):
                best[branch.branch_id] = flow
    return {branch_id: (1.0 if flow >= 0 else -1.0) for branch_id, flow in best.items()}


def binding_line_impacts(
    artifact_dir: str | Path,
    branch_ids: Sequence[str],
    flow_sign: Mapping[str, float],
    *,
    threshold: float = 0.05,
    top: int = 40,
) -> dict[str, list[tuple[str, float]]]:
    """Buses whose new load pushes each listed branch toward its limit.

    Uses DC power-transfer distribution factors (PTDFs) relative to the
    reference bus: one more MW of load at bus k, supplied from the reference
    bus, changes the flow on branch l by ``-PTDF[l, k]``.  Multiplying by the
    sign of the branch's peak flow gives how much of each MW adds to that flow.
    Returns, per branch, the buses with at least ``threshold`` MW per MW
    (strongest first, at most ``top``).
    """
    import numpy as np

    root = Path(artifact_dir)
    with (root / "bus.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    bus_ids = [row["bus_id"] for row in rows]
    reference = next((row["bus_id"] for row in rows if row.get("type") == "3"), bus_ids[0])
    index = {bus_id: i for i, bus_id in enumerate(bus_ids)}
    with (root / "branch_limits.csv").open(newline="", encoding="utf-8") as handle:
        lines = [row for row in csv.DictReader(handle) if row.get("status", "1") == "1"]
    n = len(bus_ids)
    bbus = np.zeros((n, n))
    for row in lines:
        i, j, b = index[row["from_bus_id"]], index[row["to_bus_id"]], 1.0 / float(row["reactance_pu"])
        bbus[i, i] += b
        bbus[j, j] += b
        bbus[i, j] -= b
        bbus[j, i] -= b
    keep = [i for i in range(n) if bus_ids[i] != reference]
    inverse = np.zeros((n, n))
    inverse[np.ix_(keep, keep)] = np.linalg.inv(bbus[np.ix_(keep, keep)])
    by_id = {row["branch_id"]: row for row in lines}
    impacts: dict[str, list[tuple[str, float]]] = {}
    for branch_id in branch_ids:
        row = by_id.get(branch_id)
        if row is None:
            continue
        i, j, b = index[row["from_bus_id"]], index[row["to_bus_id"]], 1.0 / float(row["reactance_pu"])
        ptdf = b * (inverse[i, :] - inverse[j, :])
        push = -ptdf * flow_sign.get(branch_id, 1.0)
        order = np.argsort(-push)
        impacts[branch_id] = [
            (bus_ids[k], round(float(push[k]), 3)) for k in order[:top] if push[k] >= threshold
        ]
    return impacts


def _mix(low: tuple[int, int, int], high: tuple[int, int, int], t: float) -> str:
    t = min(max(t, 0.0), 1.0)
    return "#%02x%02x%02x" % tuple(round(a + (b - a) * t) for a, b in zip(low, high))


def _bus_color(mw: float, max_mw: float) -> str:
    return _mix((254, 224, 139), (165, 0, 38), (mw / max_mw) ** 0.5 if max_mw > 0 else 0.0)


def _price_color(price: float, low: float, high: float) -> str:
    """Blue (cheap) through pale yellow to red (expensive)."""
    if high <= low:
        return "#fee08b"
    t = min(max((price - low) / (high - low), 0.0), 1.0)
    if t < 0.5:
        return _mix((49, 130, 189), (254, 224, 139), t / 0.5)
    return _mix((254, 224, 139), (165, 0, 38), (t - 0.5) / 0.5)


def _line_style(loading: float | None) -> tuple[str, float]:
    if loading is None:
        return "#c9ced6", 0.6
    if loading >= NEAR_LIMIT_FRACTION:
        return "#d7191c", 2.4
    if loading >= 0.8:
        return "#fd8d3c", 1.8
    if loading >= 0.5:
        return "#fdcc5c", 1.2
    return "#c9ced6", 0.6


def _tip_attr(tip: str) -> str:
    """Escape text for an attribute, keeping line breaks as &#10;."""
    return escape(tip).replace("\n", "&#10;")


_MAP_SCRIPT = """
(function () {
  var svg = document.currentScript.ownerSVGElement || document.documentElement;
  var NS = 'http://www.w3.org/2000/svg';
  var view = svg.getElementById('view'), labels = svg.getElementById('labels');
  var W = svg.viewBox.baseVal.width, H = svg.viewBox.baseVal.height;
  var scale = 1, x = 0, y = 0, drag = null, moved = false;
  var MIN = 1, MAX = 60, LABEL_SCALE = 4;
  // The map scales to fit the window, so screen points are converted with the
  // current screen transform (which also accounts for any letterboxing).
  function toView(e) {
    var pt = svg.createSVGPoint();
    pt.x = e.clientX; pt.y = e.clientY;
    pt = pt.matrixTransform(svg.getScreenCTM().inverse());
    return [pt.x, pt.y];
  }
  function screenScale() { return svg.getScreenCTM().a || 1; }
  function apply() {
    view.setAttribute('transform', 'translate(' + x + ',' + y + ') scale(' + scale + ')');
    labels.setAttribute('display', scale >= LABEL_SCALE ? 'inline' : 'none');
    labels.setAttribute('font-size', (11 / scale).toFixed(3));
  }
  function zoomAt(px, py, f) {
    var s = Math.min(MAX, Math.max(MIN, scale * f));
    f = s / scale;
    x = px - (px - x) * f; y = py - (py - y) * f; scale = s; apply();
  }
  // Gentle zoom: the step follows how far the wheel or the two-finger pinch
  // moved, so a small pinch zooms a little (one fixed step per event made
  // trackpads jump).
  svg.addEventListener('wheel', function (e) {
    e.preventDefault();
    var dy = e.deltaY * (e.deltaMode === 1 ? 16 : 1);
    var p = toView(e);
    zoomAt(p[0], p[1], Math.exp(-dy * (e.ctrlKey ? 0.01 : 0.0015)));
  }, {passive: false});
  svg.addEventListener('mousedown', function (e) {
    if (e.target.closest && e.target.closest('.ui')) return;
    drag = [e.clientX, e.clientY, x, y]; moved = false;
  });
  window.addEventListener('mouseup', function () { drag = null; });
  window.addEventListener('mousemove', function (e) {
    if (!drag) return;
    var k = 1 / screenScale();
    var dx = e.clientX - drag[0], dyy = e.clientY - drag[1];
    if (Math.abs(dx) + Math.abs(dyy) > 3) moved = true;
    x = drag[2] + dx * k; y = drag[3] + dyy * k; apply();
  });
  svg.addEventListener('dblclick', function (e) {
    if (e.target.closest && e.target.closest('.ui')) return;
    scale = 1; x = 0; y = 0; apply();
  });

  // Hover boxes.
  var tip = svg.getElementById('tip'), box = tip.querySelector('rect'), text = tip.querySelector('text');
  function show(p, lines) {
    while (text.firstChild) text.removeChild(text.firstChild);
    lines.forEach(function (line, i) {
      var span = document.createElementNS(NS, 'tspan');
      span.setAttribute('x', 12); span.setAttribute('dy', i ? '1.35em' : '1.15em');
      if (i === 0) span.setAttribute('font-weight', 'bold');
      span.textContent = line; text.appendChild(span);
    });
    var b = text.getBBox();
    box.setAttribute('width', b.width + 24); box.setAttribute('height', b.height + 16);
    tip.setAttribute('visibility', 'visible'); place(p);
  }
  // The hover box keeps the same on-screen size however small the map is drawn.
  function place(p) {
    var k = 1 / screenScale();
    var w = +box.getAttribute('width') * k, h = +box.getAttribute('height') * k, d = 16 * k;
    var tx = p[0] + d, ty = p[1] + d;
    if (tx + w > W) tx = p[0] - w - d;
    if (ty + h > H) ty = p[1] - h - d;
    tip.setAttribute('transform', 'translate(' + tx + ',' + ty + ') scale(' + k + ')');
  }
  svg.addEventListener('mouseover', function (e) {
    var t = e.target.getAttribute && e.target.getAttribute('data-tip');
    if (t) show(toView(e), t.split('\\n'));
  });
  svg.addEventListener('mousemove', function (e) {
    if (tip.getAttribute('visibility') === 'visible') place(toView(e));
  });
  svg.addEventListener('mouseout', function (e) {
    if (e.target.getAttribute && e.target.getAttribute('data-tip')) tip.setAttribute('visibility', 'hidden');
  });

  // Layers: MW served or energy price.
  var circles = Array.prototype.slice.call(svg.querySelectorAll('circle[data-id]'));
  function setLayer(name) {
    circles.forEach(function (c) {
      c.setAttribute('fill', c.getAttribute('data-' + name + '-fill'));
      c.setAttribute('r', c.getAttribute('data-' + name + '-r'));
    });
    ['load', 'price'].forEach(function (n) {
      var legend = svg.getElementById('legend-' + n), button = svg.getElementById('button-' + n);
      if (legend) legend.setAttribute('display', n === name ? 'inline' : 'none');
      if (button) button.setAttribute('class', 'ui button' + (n === name ? ' active' : ''));
    });
  }
  ['load', 'price'].forEach(function (n) {
    var button = svg.getElementById('button-' + n);
    if (button) button.addEventListener('click', function () { setLayer(n); });
  });

  // Binding lines: click to highlight the buses that push them.
  var note = svg.getElementById('note');
  function clearImpact() {
    svg.querySelectorAll('.impact').forEach(function (c) { c.classList.remove('impact'); });
    svg.querySelectorAll('.picked').forEach(function (l) { l.classList.remove('picked'); });
    note.textContent = note.getAttribute('data-default');
  }
  svg.addEventListener('click', function (e) {
    if (moved || (e.target.closest && e.target.closest('.ui'))) return;
    var spec = e.target.getAttribute && e.target.getAttribute('data-impact');
    clearImpact();
    if (spec === null || spec === undefined) return;
    e.target.classList.add('picked');
    var items = spec ? spec.split(' ') : [];
    items.forEach(function (item) {
      var c = svg.querySelector('circle[data-id="' + item.split(':')[0] + '"]');
      if (c) c.classList.add('impact');
    });
    note.textContent = items.length
      ? 'Line ' + e.target.getAttribute('data-branch') + ': ' + items.length +
        ' highlighted buses where 1 MW of new load adds at least 0.05 MW to its flow (approximate). Click elsewhere to clear.'
      : 'Line ' + e.target.getAttribute('data-branch') + ': no bus adds 0.05 MW or more per MW of new load.';
  });

  // Search by bus number or name.
  var input = svg.getElementById('search');
  var status = svg.getElementById('search-status');
  function find(query) {
    query = query.trim().toUpperCase();
    if (!query) return null;
    var exact = svg.querySelector('circle[data-id="' + query + '"]');
    if (exact) return exact;
    for (var i = 0; i < circles.length; i++) {
      if ((circles[i].getAttribute('data-name') || '').toUpperCase().indexOf(query) >= 0) return circles[i];
    }
    return null;
  }
  if (input) input.addEventListener('keydown', function (e) {
    if (e.key !== 'Enter') return;
    var c = find(input.value);
    svg.querySelectorAll('.found').forEach(function (f) { f.classList.remove('found'); });
    if (!c) { status.textContent = 'no bus matches "' + input.value + '"'; return; }
    status.textContent = '';
    c.classList.add('found');
    scale = 10;
    var cx = +c.getAttribute('cx'), cy = +c.getAttribute('cy');
    x = W / 2 - cx * scale; y = H * 0.55 - cy * scale; apply();
    show([W / 2, H * 0.55], c.getAttribute('data-tip').split('\\n'));
  });
  apply();
})();
"""


def render_svg(
    *,
    positions: Mapping[str, tuple[float, float]],
    branches: Sequence[MapBranch],
    connection_by_bus: Mapping[str, float],
    base_load_by_bus: Mapping[str, float] | None = None,
    loading_by_branch: Mapping[str, tuple[float, int]] | None = None,
    hours: int = 0,
    title: str = "Grid map",
    subtitle: str = "",
    background_paths: Sequence[Sequence[tuple[float, float]]] = (),
    layout_kind: str | None = None,
    bus_names: Mapping[str, str] | None = None,
    peak_load_by_bus: Mapping[str, float] | None = None,
    peak_period: int | None = None,
    average_price_by_bus: Mapping[str, float] | None = None,
    peak_price_by_bus: Mapping[str, float] | None = None,
    impacts_by_branch: Mapping[str, Sequence[tuple[str, float]]] | None = None,
) -> str:
    """Return a self-contained interactive SVG document."""
    width, margin, panel = 1200, 40, 250
    plot = width - 2 * margin
    y_extent = max(
        [y for _, y in positions.values()] + [y for path in background_paths for _, y in path],
        default=1.0,
    ) or 1.0
    height = round(panel + y_extent * plot + margin)
    base_load_by_bus = base_load_by_bus or {}
    bus_names = bus_names or {}
    peak_load_by_bus = peak_load_by_bus or {}
    average_price_by_bus = average_price_by_bus or {}
    peak_price_by_bus = peak_price_by_bus or {}
    impacts_by_branch = impacts_by_branch or {}
    has_prices = bool(average_price_by_bus)

    def bus_label(bus_id: str) -> str:
        name = bus_names.get(bus_id)
        return f"{name} (bus {bus_id})" if name else f"Bus {bus_id}"

    def point(bus_id: str) -> tuple[float, float]:
        x, y = positions[bus_id]
        return margin + x * plot, panel + y * plot

    max_mw = max(connection_by_bus.values(), default=0.0)
    prices = sorted(average_price_by_bus.values())
    low_price = prices[int(0.02 * (len(prices) - 1))] if prices else 0.0
    high_price = prices[int(0.98 * (len(prices) - 1))] if prices else 0.0
    layout_note = (
        "Approximate geographic layout (bus locations from the 2016 ACTIVSg2000 release)."
        if layout_kind == "approximate geographic"
        else "Schematic layout, not geographic."
    )
    default_note = (
        "Click a red (binding) line to highlight the buses whose new load pushes it toward its limit."
        if impacts_by_branch
        else ""
    )
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        'width="100%" height="100%" style="display:block;max-height:100vh" font-family="Helvetica, Arial, sans-serif">',
        "<style>"
        ".bus:hover,.site:hover{stroke:#111;stroke-width:2}"
        ".line:hover{stroke:#0969da;stroke-width:4}.binding{cursor:pointer}"
        "text{fill:#24292f}#tip text{fill:#ffffff}"
        ".impact{stroke:#0969da !important;stroke-width:2.5 !important}"
        ".picked{stroke:#0969da !important;stroke-width:5 !important}"
        ".found{stroke:#0969da !important;stroke-width:3 !important}"
        ".button{cursor:pointer}.button rect{fill:#f6f8fa;stroke:#8c959f}"
        ".button.active rect{fill:#0969da;stroke:#0969da}.button.active text{fill:#ffffff}"
        "#labels text{fill:#24292f;pointer-events:none}"
        "</style>",
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
        f'<text x="{margin}" y="42" font-size="30" font-weight="bold">{escape(title)}</text>',
    ]
    if subtitle:
        out.append(f'<text x="{margin}" y="72" font-size="18">{escape(subtitle)}</text>')
    out.append(f'<text x="{margin}" y="98" font-size="15" fill="#57606a">{layout_note}</text>')
    out.append(
        f'<text x="{margin}" y="118" font-size="15" fill="#57606a">'
        "Hover a bus or line for details; scroll or pinch to zoom (bus numbers appear when zoomed in), "
        "drag to pan, double-click to reset.</text>"
    )
    out.append(
        f'<text id="note" x="{margin}" y="138" font-size="15" fill="#0969da" '
        f'data-default="{escape(default_note)}">{escape(default_note)}</text>'
    )
    # Toolbar: layer buttons and search.
    bar_y = 152
    buttons = [("load", "MW served")] + ([("price", "Energy price (LMP)")] if has_prices else [])
    bx = margin
    for key, label in buttons:
        bw = 30 + 9 * len(label)
        active = " active" if key == "load" else ""
        out.append(
            f'<g id="button-{key}" class="ui button{active}"><rect x="{bx}" y="{bar_y}" width="{bw}" height="30" rx="6"/>'
            f'<text x="{bx + bw / 2}" y="{bar_y + 20}" font-size="15" text-anchor="middle">{escape(label)}</text></g>'
        )
        bx += bw + 10
    out.append(
        f'<foreignObject class="ui" x="{width - margin - 360}" y="{bar_y}" width="360" height="32">'
        '<input xmlns="http://www.w3.org/1999/xhtml" id="search" type="search" '
        'placeholder="Find a bus by number or name, then press Enter" '
        'style="width:100%;box-sizing:border-box;height:30px;font-size:14px;padding:0 8px;'
        'border:1px solid #8c959f;border-radius:6px"/></foreignObject>'
    )
    out.append(f'<text id="search-status" x="{width - margin - 360}" y="{bar_y + 48}" font-size="13" fill="#cf222e"></text>')
    # Legends.
    legend_y = 205
    out.append(f'<g id="legend-load"><text x="{margin}" y="{legend_y}" font-size="15" font-weight="bold">'
               "New data-center load served at bus (all teams)</text>")
    for i, fraction in enumerate((0.0, 0.25, 0.5, 0.75, 1.0)):
        cx = margin + 12 + i * 52
        out.append(f'<circle cx="{cx}" cy="{legend_y + 18}" r="8" fill="{_bus_color(fraction * max_mw, max_mw)}"/>')
        out.append(f'<text x="{cx}" y="{legend_y + 42}" font-size="14" text-anchor="middle">{fraction * max_mw:.0f}</text>')
    out.append(f'<text x="{margin + 268}" y="{legend_y + 42}" font-size="14">MW</text></g>')
    if has_prices:
        out.append(f'<g id="legend-price" display="none"><text x="{margin}" y="{legend_y}" font-size="15" '
                   f'font-weight="bold">Average energy price over {hours} h</text>')
        for i, fraction in enumerate((0.0, 0.25, 0.5, 0.75, 1.0)):
            value = low_price + fraction * (high_price - low_price)
            cx = margin + 12 + i * 52
            out.append(f'<circle cx="{cx}" cy="{legend_y + 18}" r="8" fill="{_price_color(value, low_price, high_price)}"/>')
            out.append(f'<text x="{cx}" y="{legend_y + 42}" font-size="14" text-anchor="middle">{value:.0f}</text>')
        out.append(f'<text x="{margin + 268}" y="{legend_y + 42}" font-size="14">$/MWh</text></g>')
    if loading_by_branch is not None:
        lx = margin + 420
        out.append(f'<text x="{lx}" y="{legend_y}" font-size="15" font-weight="bold">Peak line loading over {hours} h</text>')
        for i, (label, value) in enumerate((("< 50%", 0.0), ("50-80%", 0.6), ("80-99%", 0.9), ("at limit", 1.0))):
            color, stroke = _line_style(value)
            x0 = lx + i * 105
            out.append(f'<line x1="{x0}" y1="{legend_y + 18}" x2="{x0 + 44}" y2="{legend_y + 18}" stroke="{color}" stroke-width="{max(stroke, 1.5)}"/>')
            out.append(f'<text x="{x0}" y="{legend_y + 42}" font-size="14">{escape(label)}</text>')

    out.append('<g id="view">')
    for path in background_paths:
        points = " ".join(f"{margin + x * plot:.1f},{panel + y * plot:.1f}" for x, y in path)
        out.append(f'<polygon points="{points}" fill="#f6f8fa" stroke="#8c959f" stroke-width="1.5"/>')
    ordered = sorted(
        branches,
        key=lambda b: (loading_by_branch or {}).get(b.branch_id, (0.0, 0))[0],
    )
    for branch in ordered:
        if branch.from_bus_id not in positions or branch.to_bus_id not in positions:
            continue
        loading = None
        tip = (
            f"Line {branch.branch_id}\nfrom {bus_label(branch.from_bus_id)}\nto {bus_label(branch.to_bus_id)}"
            f"\nthermal limit {branch.limit_mw:g} MW"
        )
        if loading_by_branch is not None and branch.branch_id in loading_by_branch:
            loading, near_hours = loading_by_branch[branch.branch_id]
            tip += f"\npeak loading {loading:.0%}\nat or near limit in {near_hours} of {hours} h"
        extra = ""
        if branch.branch_id in impacts_by_branch:
            tip += "\nclick to highlight the buses that push this line"
            spec = " ".join(f"{bus}:{value:g}" for bus, value in impacts_by_branch[branch.branch_id])
            extra = f' data-impact="{escape(spec)}" data-branch="{escape(branch.branch_id)}"'
        color, stroke = _line_style(loading)
        x1, y1 = point(branch.from_bus_id)
        x2, y2 = point(branch.to_bus_id)
        css = "line binding" if extra else "line"
        out.append(
            f'<line class="{css}" x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{color}" stroke-width="{stroke}" data-tip="{_tip_attr(tip)}"{extra}/>'
        )
    label_lines = []
    for bus_id in sorted(positions, key=lambda b: connection_by_bus.get(b, 0.0)):
        x, y = point(bus_id)
        mw = connection_by_bus.get(bus_id, 0.0)
        if peak_period is not None and bus_id in peak_load_by_bus:
            existing, when = peak_load_by_bus[bus_id], f"at the peak hour (period {peak_period})"
        else:
            existing, when = base_load_by_bus.get(bus_id, 0.0), "(base case)"
        tip = f"{bus_label(bus_id)}\nload {when}:\n  existing base load {existing:,.1f} MW"
        tip += f"\n  new data-center load (all teams): {mw:,.1f} MW\n  total {existing + mw:,.1f} MW"
        if bus_id in average_price_by_bus:
            tip += (
                f"\nenergy price over {hours} h:\n  average {average_price_by_bus[bus_id]:,.2f} $/MWh"
                f"\n  highest {peak_price_by_bus.get(bus_id, average_price_by_bus[bus_id]):,.2f} $/MWh"
            )
        if mw > 0:
            css, radius, fill = "site", 3.5 + 6.5 * (mw / max_mw) ** 0.5, _bus_color(mw, max_mw)
            stroke = ' stroke="#5c0016" stroke-width="0.8"'
        else:
            css, radius, fill, stroke = "bus", 2.2, "#8c959f", ""
        price_fill = (
            _price_color(average_price_by_bus[bus_id], low_price, high_price)
            if bus_id in average_price_by_bus
            else fill
        )
        price_r = max(radius, 3.0) if has_prices else radius
        name = escape(bus_names.get(bus_id, ""))
        out.append(
            f'<circle class="{css}" cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}" fill="{fill}"{stroke} '
            f'data-id="{escape(bus_id)}" data-name="{name}" data-load-fill="{fill}" data-load-r="{radius:.1f}" '
            f'data-price-fill="{price_fill}" data-price-r="{price_r:.1f}" data-tip="{_tip_attr(tip)}"/>'
        )
        label_lines.append(f'<text x="{x + 2.5:.1f}" y="{y - 2.5:.1f}">{escape(bus_id)}</text>')
    out.append('<g id="labels" display="none" font-size="11">' + "".join(label_lines) + "</g>")
    out.append("</g>")
    out.append('<g id="tip" visibility="hidden" pointer-events="none">'
               '<rect rx="6" fill="#24292f" fill-opacity="0.94"/>'
               '<text font-size="15" xml:space="preserve" style="white-space:pre"/></g>')
    out.append(f"<script><![CDATA[{_MAP_SCRIPT}]]></script>")
    out.append("</svg>")
    return "\n".join(out) + "\n"


def build_map(
    *,
    artifact_dir: str | Path,
    evaluation_dirs: Sequence[str | Path],
    layout_path: str | Path,
    dispatch_dir: str | Path | None = None,
    title: str = "Grid map",
    subtitle: str = "",
) -> str:
    bus_ids, branches, base_load = load_network(artifact_dir)
    positions = load_or_create_layout(layout_path, bus_ids, branches)
    background_paths, layout_kind = load_layout_background(layout_path)
    bus_names = load_bus_names(layout_path)
    peak_load, peak_period = peak_hour_demand(artifact_dir)
    served, _ = served_load_by_bus(evaluation_dirs)
    unknown = sorted(set(served) - set(bus_ids))
    if unknown:
        raise ValueError("evaluation output references buses outside the artifact: " + ", ".join(unknown[:5]))
    loading, hours = (None, 0)
    average_price: dict[str, float] = {}
    peak_price: dict[str, float] = {}
    impacts: dict[str, list[tuple[str, float]]] = {}
    if dispatch_dir is not None:
        loading, hours = branch_loading(dispatch_dir, branches)
        average_price, peak_price = bus_prices(dispatch_dir)
        binding = [branch_id for branch_id, (peak, _) in loading.items() if peak >= NEAR_LIMIT_FRACTION]
        if binding:
            impacts = binding_line_impacts(artifact_dir, binding, peak_flow_sign(dispatch_dir, branches))
    return render_svg(
        positions=positions,
        branches=branches,
        connection_by_bus=served,
        base_load_by_bus=base_load,
        loading_by_branch=loading,
        hours=hours,
        background_paths=background_paths,
        layout_kind=layout_kind,
        bus_names=bus_names,
        peak_load_by_bus=peak_load,
        peak_period=peak_period,
        average_price_by_bus=average_price,
        peak_price_by_bus=peak_price,
        impacts_by_branch=impacts,
        title=title,
        subtitle=subtitle,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render the privacy-safe interactive classroom grid map (SVG)")
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        help="scenario block directory (default: the released representative-day package)",
    )
    parser.add_argument(
        "--evaluation-dir", required=True, type=Path, action="append",
        help=(
            "batch_cli run output directory (its site_net_withdrawal.csv gives served MW); "
            "repeat with the Submission 1 output to include Submission 1 sites carried into Submission 2"
        ),
    )
    parser.add_argument(
        "--dispatch-dir",
        type=Path,
        help="evaluator dispatch/ directory with period_*.json files (default: <last --evaluation-dir>/dispatch when present)",
    )
    parser.add_argument(
        "--layout", type=Path, default=Path("data/teaching/activsg2000_geo_layout_v1.json"),
        help="stored bus layout (created if missing)",
    )
    parser.add_argument("--title", default="Grid map")
    parser.add_argument("--subtitle", default="")
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.artifact_dir is None:
        from .release_config import canonical_release_artifact_dir

        args.artifact_dir = canonical_release_artifact_dir()
    dispatch_dir = args.dispatch_dir
    if dispatch_dir is None and (args.evaluation_dir[-1] / "dispatch").is_dir():
        dispatch_dir = args.evaluation_dir[-1] / "dispatch"
    svg = build_map(
        artifact_dir=args.artifact_dir,
        evaluation_dirs=args.evaluation_dir,
        layout_path=args.layout,
        dispatch_dir=dispatch_dir,
        title=args.title,
        subtitle=args.subtitle,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(svg, encoding="utf-8")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
