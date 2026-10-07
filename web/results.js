(function () {
  "use strict";

  const RESULTS_SCHEMA_VERSION = "results.v1";
  const RESULT_ARTIFACTS = [
    ["round", "/data/results/round_metadata.json"],
    ["network", "/data/results/public_network.json"],
    ["team_report", "/data/results/team_report.json"],
    ["aggregate", "/data/results/aggregate_grid_summary.json"],
  ];

  const DEFAULT_ARTIFACTS = {
    round: {
      schema_version: RESULTS_SCHEMA_VERSION,
      round_id: "unpublished",
      round_name: "No published round",
      team_id: "—",
      horizon_label: "—",
      status: "unavailable",
    },
    network: {
      schema_version: RESULTS_SCHEMA_VERSION,
      network_id: "zenodo-public-network",
      buses: [],
      branches: [],
    },
    team_report: {
      schema_version: RESULTS_SCHEMA_VERSION,
      team_id: "—",
      feasibility: "not_evaluated",
      service_fraction: null,
      score: null,
      score_breakdown: {},
      sites: [],
      generators: [],
      storage: [],
    },
    aggregate: {
      schema_version: RESULTS_SCHEMA_VERSION,
      privacy_policy: "team-level strategies are not disclosed",
      metrics: {},
      stress_periods: [],
    },
  };

  function element(id) {
    return document.getElementById(id);
  }

  function setText(id, value) {
    const node = element(id);
    if (node) node.textContent = value == null || value === "" ? "—" : String(value);
  }

  function formatNumber(value, digits = 2) {
    return typeof value === "number" && Number.isFinite(value)
      ? value.toLocaleString(undefined, { maximumFractionDigits: digits })
      : "—";
  }

  function formatPercent(value) {
    return typeof value === "number" && Number.isFinite(value)
      ? `${(value * 100).toFixed(1)}%`
      : "—";
  }

  function isObject(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

  const RESULTS_MAP_VIEWBOX = { width: 960, height: 520 };
  const RESULTS_MAP_ZOOM = { min: 1, max: 6 };
  let resultsMapView = { zoom: 1, x: 0, y: 0, drag: null };
  let resultsMapModel = null;
  let resultsMapProjection = null;
  let resultsMapSelection = null;
  let resultsMapGeography = { boundary: [], counties: [] };

  function finite(value) {
    return typeof value === "number" && Number.isFinite(value);
  }

  function resultsMapPoint(bus) {
    const lon = Number(bus?.lon ?? bus?.longitude);
    const lat = Number(bus?.lat ?? bus?.latitude);
    return finite(lon) && finite(lat) ? [lon, lat] : null;
  }

  function resultsMapResource(kind, record, busIds) {
    if (!isObject(record)) return null;
    const id = String(record[`${kind}_id`] || "").trim();
    const busId = String(record.bus_id || "").trim();
    if (!id || !busIds.has(busId)) return null;
    const resource = { kind, id, bus_id: busId };
    if (kind === "site" && finite(Number(record.load_mw))) resource.load_mw = Number(record.load_mw);
    if (kind === "generator" && finite(Number(record.capacity_mw))) resource.capacity_mw = Number(record.capacity_mw);
    if (kind === "storage") {
      if (finite(Number(record.power_mw))) resource.power_mw = Number(record.power_mw);
      if (finite(Number(record.energy_mwh))) resource.energy_mwh = Number(record.energy_mwh);
    }
    return resource;
  }

  function resultsMapStressRecord(record, busById) {
    if (!isObject(record)) return null;
    const utilization = Number(record.utilization ?? record.utilization_fraction ?? record.headroom_utilization);
    if (!finite(utilization)) return null;
    const id = String(record.region_id || record.bus_id || "").trim();
    const reference = String(record.bus_id || record.region_id || "").trim();
    const bus = reference && busById.has(reference) ? busById.get(reference) : null;
    const lon = Number(record.lon ?? record.longitude ?? record.center_lon ?? record.centroid_lon);
    const lat = Number(record.lat ?? record.latitude ?? record.center_lat ?? record.centroid_lat);
    const point = bus ? [bus.lon, bus.lat] : finite(lon) && finite(lat) ? [lon, lat] : null;
    if (!id || !point) return null;
    return { id, utilization: Math.max(0, Math.min(1, utilization)), point, bus_id: bus?.bus_id || null };
  }

  function resultsMapStressRecords(aggregate, busById) {
    const source = isObject(aggregate) ? aggregate : {};
    const records = Array.isArray(source.region_utilization) ? source.region_utilization : [];
    return records.map((record) => resultsMapStressRecord(record, busById)).filter(Boolean);
  }

  function resultsMapAggregatePlan(aggregate) {
    const records = isObject(aggregate) && Array.isArray(aggregate.aggregate_plan) ? aggregate.aggregate_plan : [];
    return records.map((record) => {
      if (!isObject(record) || !finite(Number(record.lat)) || !finite(Number(record.lon))) return null;
      const teams = Number(record.contributing_teams);
      if (!finite(teams) || teams < 2) return null;
      return {
        cell_id: String(record.cell_id || "aggregate-cell"),
        lat: Number(record.lat),
        lon: Number(record.lon),
        contributing_teams: teams,
        requested_load_mw: finite(Number(record.requested_load_mw)) ? Number(record.requested_load_mw) : null,
        resource_count: finite(Number(record.resource_count)) ? Number(record.resource_count) : null,
      };
    }).filter(Boolean);
  }

  // Adapter boundary: only the public network and selected-team allowlisted
  // records enter the browser map. Unknown report fields are never copied.
  function adaptResultsNetwork(network, teamReport, aggregate) {
    const source = isObject(network) ? network : {};
    const report = isObject(teamReport) ? teamReport : {};
    const buses = [];
    const busById = new Map();
    (Array.isArray(source.buses) ? source.buses : []).forEach((bus) => {
      const busId = String(bus?.bus_id || "").trim();
      const point = resultsMapPoint(bus);
      if (!busId || !point || busById.has(busId)) return;
      const mapped = { bus_id: busId, lon: point[0], lat: point[1] };
      busById.set(busId, mapped);
      buses.push(mapped);
    });
    const branches = [];
    (Array.isArray(source.branches) ? source.branches : []).forEach((branch) => {
      const branchId = String(branch?.branch_id || "").trim();
      const fromBus = busById.get(String(branch?.from_bus || "").trim());
      const toBus = busById.get(String(branch?.to_bus || "").trim());
      if (!branchId || !fromBus || !toBus) return;
      const mapped = { branch_id: branchId, from_bus: fromBus.bus_id, to_bus: toBus.bus_id, geometry: [[fromBus.lon, fromBus.lat], [toBus.lon, toBus.lat]], focusable: false };
      if (finite(Number(branch.capacity_mw))) mapped.capacity_mw = Number(branch.capacity_mw);
      branches.push(mapped);
    });
    const teamResources = [];
    [
      ["site", report.sites],
      ["generator", report.generators],
      ["storage", report.storage],
    ].forEach(([kind, records]) => (Array.isArray(records) ? records : []).forEach((record) => {
      const resource = resultsMapResource(kind, record, busById);
      if (resource) teamResources.push(resource);
    }));
    return { buses, branches, teamResources, stressRecords: resultsMapStressRecords(aggregate, busById), aggregatePlan: resultsMapAggregatePlan(aggregate) };
  }

  function resultsMapBounds(model, geography = resultsMapGeography) {
    const points = model.buses.map((bus) => [bus.lon, bus.lat]);
    geography.boundary.forEach((ring) => points.push(...ring));
    geography.counties.forEach((ring) => points.push(...ring));
    if (!points.length) return { minLon: -106, maxLon: -93, minLat: 28, maxLat: 37 };
    const longs = points.map((point) => point[0]);
    const lats = points.map((point) => point[1]);
    const lonPad = Math.max((Math.max(...longs) - Math.min(...longs)) * 0.06, 0.2);
    const latPad = Math.max((Math.max(...lats) - Math.min(...lats)) * 0.08, 0.2);
    return { minLon: Math.min(...longs) - lonPad, maxLon: Math.max(...longs) + lonPad, minLat: Math.min(...lats) - latPad, maxLat: Math.max(...lats) + latPad };
  }

  function createResultsProjection(model, geography = resultsMapGeography) {
    const bounds = resultsMapBounds(model, geography);
    const width = RESULTS_MAP_VIEWBOX.width - 56;
    const height = RESULTS_MAP_VIEWBOX.height - 56;
    const latitudeScale = Math.cos(((bounds.minLat + bounds.maxLat) / 2) * Math.PI / 180);
    const projectedMinLon = bounds.minLon * latitudeScale;
    const projectedMaxLon = bounds.maxLon * latitudeScale;
    const scale = Math.min(width / (projectedMaxLon - projectedMinLon), height / (bounds.maxLat - bounds.minLat));
    const contentWidth = (projectedMaxLon - projectedMinLon) * scale;
    const contentHeight = (bounds.maxLat - bounds.minLat) * scale;
    const left = (RESULTS_MAP_VIEWBOX.width - contentWidth) / 2;
    const top = (RESULTS_MAP_VIEWBOX.height - contentHeight) / 2;
    return (point) => [left + (point[0] * latitudeScale - projectedMinLon) * scale, top + (bounds.maxLat - point[1]) * scale];
  }

  function resultsMapGeometryCulling(points, view = resultsMapView) {
    const projected = points.map(resultsMapProjection);
    const xs = projected.map((point) => point[0] * view.zoom + view.x);
    const ys = projected.map((point) => point[1] * view.zoom + view.y);
    return Math.max(...xs) >= 0 && Math.min(...xs) <= RESULTS_MAP_VIEWBOX.width && Math.max(...ys) >= 0 && Math.min(...ys) <= RESULTS_MAP_VIEWBOX.height;
  }

  function clampResultsMapPan(x, y, zoom) {
    const minX = RESULTS_MAP_VIEWBOX.width - RESULTS_MAP_VIEWBOX.width * zoom;
    const minY = RESULTS_MAP_VIEWBOX.height - RESULTS_MAP_VIEWBOX.height * zoom;
    return { x: Math.min(0, Math.max(minX, x)), y: Math.min(0, Math.max(minY, y)) };
  }

  function resultsMapLabelCulling(bus, index, view = resultsMapView) {
    if (view.zoom >= 2.2) return true;
    if (view.zoom >= 1.35) return index % 8 === 0;
    return index % 28 === 0;
  }

  function resultsMapBusCulling(index, view = resultsMapView) {
    if (view.zoom >= 2.2) return true;
    if (view.zoom >= 1.35) return index % 4 === 0;
    return index % 10 === 0;
  }

  function resultsSvg(name, attributes = {}) {
    const node = document.createElementNS("http://www.w3.org/2000/svg", name);
    Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, String(value)));
    return node;
  }

  function resultsPath(points) {
    return points.map((point, index) => `${index ? "L" : "M"}${point[0].toFixed(1)} ${point[1].toFixed(1)}`).join(" ");
  }

  function resultsMapFrame() {
    return element("results-map-mount") || element("results-map");
  }

  function resultsMapPointer(event) {
    const map = element("results-map");
    const rect = map?.getBoundingClientRect?.();
    if (!rect || !rect.width || !rect.height) return { x: RESULTS_MAP_VIEWBOX.width / 2, y: RESULTS_MAP_VIEWBOX.height / 2 };
    return { x: (event.clientX - rect.left) * RESULTS_MAP_VIEWBOX.width / rect.width, y: (event.clientY - rect.top) * RESULTS_MAP_VIEWBOX.height / rect.height };
  }

  function setResultsMapView(next = {}) {
    const previousZoom = resultsMapView.zoom;
    const zoom = Math.min(RESULTS_MAP_ZOOM.max, Math.max(RESULTS_MAP_ZOOM.min, Number(next.zoom ?? previousZoom)));
    const anchor = next.anchor || { x: RESULTS_MAP_VIEWBOX.width / 2, y: RESULTS_MAP_VIEWBOX.height / 2 };
    const ratio = zoom / previousZoom;
    const pan = clampResultsMapPan(Number(next.x ?? anchor.x - (anchor.x - resultsMapView.x) * ratio), Number(next.y ?? anchor.y - (anchor.y - resultsMapView.y) * ratio), zoom);
    const nextView = {
      zoom,
      x: pan.x,
      y: pan.y,
      drag: resultsMapView.drag,
    };
    resultsMapView = nextView;
    if (resultsMapModel) renderResultsMapModel();
  }

  function resetResultsMapView() {
    resultsMapView = { zoom: 1, x: 0, y: 0, drag: null };
    if (resultsMapModel) renderResultsMapModel();
  }

  function ensureResultsMapControls() {
    const mount = resultsMapFrame();
    if (!mount || document.getElementById("results-map-controls")) return;
    const controls = document.createElement("div");
    controls.id = "results-map-controls";
    controls.className = "results-map-controls";
    controls.setAttribute("role", "group");
    controls.setAttribute("aria-label", "Results map controls");
    [["results-map-zoom-in", "+", "Zoom in results map"], ["results-map-zoom-out", "−", "Zoom out results map"], ["results-map-reset", "Reset view", "Reset results map view"]].forEach(([id, label, aria]) => {
      const button = document.createElement("button");
      button.id = id; button.type = "button"; button.className = "secondary-button map-control-button"; button.textContent = label; button.setAttribute("aria-label", aria);
      if (id === "results-map-zoom-in") button.addEventListener("click", () => setResultsMapView({ zoom: resultsMapView.zoom * 1.25 }));
      if (id === "results-map-zoom-out") button.addEventListener("click", () => setResultsMapView({ zoom: resultsMapView.zoom / 1.25 }));
      if (id === "results-map-reset") button.addEventListener("click", resetResultsMapView);
      controls.appendChild(button);
    });
    mount.appendChild(controls);
  }

  function bindResultsMapInteractions() {
    const map = element("results-map");
    if (!map || map.dataset.interactionsBound === "true") return;
    map.dataset.interactionsBound = "true";
    map.tabIndex = 0;
    map.removeAttribute("aria-hidden");
    map.setAttribute("role", "group");
    map.setAttribute("aria-label", "Read-only public network and selected-team results map");
    map.addEventListener("wheel", (event) => { event.preventDefault(); setResultsMapView({ zoom: resultsMapView.zoom * (event.deltaY < 0 ? 1.15 : 1 / 1.15), anchor: resultsMapPointer(event) }); }, { passive: false });
    map.addEventListener("pointerdown", (event) => {
      if (event.target.closest?.("[data-results-resource]")) return;
      const point = resultsMapPointer(event);
      resultsMapView.drag = { pointerId: event.pointerId, point, x: resultsMapView.x, y: resultsMapView.y };
      map.setPointerCapture?.(event.pointerId);
    });
    map.addEventListener("pointermove", (event) => {
      const drag = resultsMapView.drag;
      if (!drag || drag.pointerId !== event.pointerId) return;
      const point = resultsMapPointer(event);
      const pan = clampResultsMapPan(drag.x + point.x - drag.point.x, drag.y + point.y - drag.point.y, resultsMapView.zoom);
      resultsMapView.x = pan.x;
      resultsMapView.y = pan.y;
      renderResultsMapModel();
    });
    ["pointerup", "pointercancel", "lostpointercapture"].forEach((name) => map.addEventListener(name, () => { resultsMapView.drag = null; }));
    map.addEventListener("keydown", (event) => {
      if (event.key === "+" || event.key === "=") setResultsMapView({ zoom: resultsMapView.zoom * 1.25 });
      else if (event.key === "-" || event.key === "_") setResultsMapView({ zoom: resultsMapView.zoom / 1.25 });
      else if (event.key === "ArrowLeft") setResultsMapView({ x: resultsMapView.x - 32, y: resultsMapView.y, zoom: resultsMapView.zoom });
      else if (event.key === "ArrowRight") setResultsMapView({ x: resultsMapView.x + 32, y: resultsMapView.y, zoom: resultsMapView.zoom });
      else if (event.key === "ArrowUp") setResultsMapView({ x: resultsMapView.x, y: resultsMapView.y - 32, zoom: resultsMapView.zoom });
      else if (event.key === "ArrowDown") setResultsMapView({ x: resultsMapView.x, y: resultsMapView.y + 32, zoom: resultsMapView.zoom });
      else return;
      event.preventDefault();
    });
  }

  function selectResultsResource(resource) {
    resultsMapSelection = resource;
    const status = element("results-map-status");
    if (status) status.textContent = `${resource.kind} ${resource.id} · ${resource.bus_id}`;
    const report = element("results-team-report");
    if (report) {
      const detail = document.createElement("p");
      detail.className = "results-selected-resource";
      detail.textContent = `Selected ${resource.kind}: ${resource.id} at bus ${resource.bus_id}.`;
      report.querySelector(".results-selected-resource")?.remove();
      report.appendChild(detail);
    }
    renderResultsMapModel();
  }

  function renderResultsMapModel() {
    const svg = element("results-map");
    if (!svg || !resultsMapModel || !resultsMapProjection) return;
    svg.replaceChildren(resultsSvg("rect", { class: "results-map-surface", x: 0, y: 0, width: RESULTS_MAP_VIEWBOX.width, height: RESULTS_MAP_VIEWBOX.height }));
    const viewport = resultsSvg("g", { id: "results-map-viewport", transform: `translate(${resultsMapView.x.toFixed(1)} ${resultsMapView.y.toFixed(1)}) scale(${resultsMapView.zoom.toFixed(3)})` });
    const geographyLayer = resultsSvg("g", { id: "results-geography-layer", "aria-hidden": "true" });
    const countyLayer = resultsSvg("g", { id: "results-county-layer", "aria-hidden": "true" });
    const publicLayer = resultsSvg("g", { id: "results-public-network-layer", "aria-label": "Public network branches" });
    const stressLayer = resultsSvg("g", { id: "results-aggregate-stress-layer", "aria-hidden": "true" });
    const aggregatePlanLayer = resultsSvg("g", { id: "results-aggregate-plan-layer", "aria-hidden": "true" });
    const busLayer = resultsSvg("g", { id: "results-public-bus-layer", "aria-hidden": "true" });
    const teamLayer = resultsSvg("g", { id: "results-team-resource-layer", "aria-label": "Selected team resources" });
    resultsMapGeography.counties.forEach((ring) => {
      if (!resultsMapGeometryCulling(ring)) return;
      countyLayer.appendChild(resultsSvg("path", { class: "results-county-boundary", d: `${resultsPath(ring.map(resultsMapProjection))} Z` }));
    });
    resultsMapGeography.boundary.forEach((ring) => {
      if (!resultsMapGeometryCulling(ring)) return;
      geographyLayer.appendChild(resultsSvg("path", { class: "results-texas-fill", d: `${resultsPath(ring.map(resultsMapProjection))} Z` }));
      geographyLayer.appendChild(resultsSvg("path", { class: "results-texas-outline", d: resultsPath(ring.map(resultsMapProjection)) }));
    });
    resultsMapModel.stressRecords.forEach((stress) => {
      if (!resultsMapGeometryCulling([stress.point])) return;
      const [x, y] = resultsMapProjection(stress.point);
      const radius = 5 + stress.utilization * 10;
      stressLayer.appendChild(resultsSvg("circle", {
        class: "results-stress-overlay",
        cx: x.toFixed(1), cy: y.toFixed(1), r: radius.toFixed(1),
        "data-stress-id": stress.id, "data-utilization": stress.utilization.toFixed(3),
      }));
    });
    resultsMapModel.aggregatePlan.forEach((cell) => {
      if (!resultsMapGeometryCulling([[cell.lon, cell.lat]])) return;
      const [x, y] = resultsMapProjection([cell.lon, cell.lat]);
      const radius = 12 + Math.min(12, Math.max(0, Number(cell.resource_count || 0) * 2));
      aggregatePlanLayer.appendChild(resultsSvg("circle", {
        class: "results-aggregate-plan-cell", cx: x.toFixed(1), cy: y.toFixed(1), r: radius.toFixed(1),
        "data-aggregate-cell": cell.cell_id,
      }));
    });
    resultsMapModel.branches.forEach((branch) => {
      const points = branch.geometry.map(resultsMapProjection);
      if (!resultsMapGeometryCulling(branch.geometry)) return;
      publicLayer.appendChild(resultsSvg("path", { class: "results-public-branch", d: resultsPath(points), "aria-hidden": "true", "data-public-id": branch.branch_id }));
    });
    resultsMapModel.buses.forEach((bus, index) => {
      const point = resultsMapProjection([bus.lon, bus.lat]);
      if (resultsMapBusCulling(index) && resultsMapGeometryCulling([[bus.lon, bus.lat]])) {
        busLayer.appendChild(resultsSvg("rect", {
          class: "results-public-bus", x: (point[0] - 2).toFixed(1), y: (point[1] - 2).toFixed(1),
          width: 4, height: 4, "data-public-bus-id": bus.bus_id,
        }));
      }
    });
    resultsMapModel.teamResources.forEach((resource) => {
      const bus = resultsMapModel.buses.find((candidate) => candidate.bus_id === resource.bus_id);
      if (!bus) return;
      const [x, y] = resultsMapProjection([bus.lon, bus.lat]);
      const selected = resultsMapSelection?.id === resource.id && resultsMapSelection?.kind === resource.kind;
      const marker = resultsSvg("g", { class: `results-team-resource results-team-${resource.kind}${selected ? " is-selected" : ""}`, transform: `translate(${x.toFixed(1)} ${y.toFixed(1)})`, role: "button", tabindex: 0, "aria-label": `Select your ${resource.kind} ${resource.id} at bus ${resource.bus_id}`, "data-results-resource": resource.id });
      const label = resultsSvg("text", { class: "results-team-label", x: 10, y: 4, "aria-hidden": "true" });
      label.textContent = resource.id;
      marker.append(resultsSvg("rect", { class: "results-team-hit", x: -18, y: -18, width: 36, height: 36 }), resultsSvg("rect", { class: "results-team-marker", x: -6, y: -6, width: 12, height: 12 }), label);
      marker.addEventListener("click", () => selectResultsResource(resource));
      marker.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); selectResultsResource(resource); } });
      teamLayer.appendChild(marker);
    });
    viewport.append(geographyLayer, countyLayer, aggregatePlanLayer, stressLayer, publicLayer, busLayer, teamLayer);
    svg.appendChild(viewport);
  }

  function renderResultsMap(pkg) {
    const svg = element("results-map");
    if (!svg) return;
    resultsMapModel = adaptResultsNetwork(pkg.network, pkg.team_report, pkg.aggregate);
    resultsMapProjection = createResultsProjection(resultsMapModel, resultsMapGeography);
    resultsMapSelection = null;
    ensureResultsMapControls();
    bindResultsMapInteractions();
    renderResultsMapModel();
  }

  function resultsError(state, message) {
    const error = new Error(message);
    error.state = state;
    return error;
  }

  function validateBrowserPackage(pkg) {
    if (!isObject(pkg)) throw resultsError("malformed", "Results package must be an object.");
    if (pkg.schema_version !== RESULTS_SCHEMA_VERSION) {
      throw resultsError("malformed", `Unsupported results schema: ${pkg.schema_version || "missing"}.`);
    }
    for (const [name] of RESULT_ARTIFACTS) {
      if (!isObject(pkg[name])) throw resultsError("malformed", `Results package is missing ${name}.`);
      if (pkg[name].schema_version !== RESULTS_SCHEMA_VERSION) {
        throw resultsError("malformed", `Unsupported ${name} artifact schema.`);
      }
    }
    if (!Array.isArray(pkg.network.buses) || !Array.isArray(pkg.network.branches)) {
      throw resultsError("malformed", "Public network artifact must contain buses and branches.");
    }
    if (!Array.isArray(pkg.team_report.sites) || !Array.isArray(pkg.team_report.generators) || !Array.isArray(pkg.team_report.storage)) {
      throw resultsError("malformed", "Team report must contain sites, generators, and storage arrays.");
    }
    if (typeof pkg.aggregate.privacy_policy !== "string") {
      throw resultsError("malformed", "Aggregate artifact must declare a privacy policy.");
    }
    return pkg;
  }

  async function fetchResultArtifact(url) {
    let response;
    try {
      response = await fetch(url, { cache: "no-store" });
    } catch (_error) {
      throw resultsError("unavailable", "Results package could not be reached.");
    }
    if (response.status === 404) return { status: "missing", value: null };
    if (!response.ok) throw resultsError("unavailable", `Results request failed (${response.status}).`);
    try {
      return { status: "present", value: await response.json() };
    } catch (_error) {
      throw resultsError("malformed", "A results artifact is not valid JSON.");
    }
  }

  async function loadResultsPackage() {
    const artifacts = await Promise.all(RESULT_ARTIFACTS.map(([, url]) => fetchResultArtifact(url)));
    const missing = artifacts.filter((artifact) => artifact.status === "missing").length;
    if (missing === RESULT_ARTIFACTS.length) {
      const defaults = Object.fromEntries(
        RESULT_ARTIFACTS.map(([name]) => [name, JSON.parse(JSON.stringify(DEFAULT_ARTIFACTS[name]))])
      );
      return validateBrowserPackage({ schema_version: RESULTS_SCHEMA_VERSION, ...defaults });
    }
    if (missing > 0) {
      throw resultsError("malformed", "Results package is incomplete: all four artifacts are required.");
    }
    const packagePayload = {
      schema_version: RESULTS_SCHEMA_VERSION,
      round: artifacts[0].value,
      network: artifacts[1].value,
      team_report: artifacts[2].value,
      aggregate: artifacts[3].value,
    };
    return validateBrowserPackage(packagePayload);
  }

  async function loadResultsGeography() {
    let boundary = {};
    let counties = {};
    try {
      const [boundaryResponse, countiesResponse] = await Promise.all([
        fetch("/texas-boundary.json", { cache: "no-store" }),
        fetch("/texas-counties.json", { cache: "no-store" }),
      ]);
      boundary = boundaryResponse.ok ? await boundaryResponse.json() : {};
      counties = countiesResponse.ok ? await countiesResponse.json() : {};
    } catch (_error) {
      // Geography is presentation context; it must not invalidate the
      // evaluator-authoritative results package.
      resultsMapGeography = { boundary: [], counties: [] };
      return resultsMapGeography;
    }
    const boundaryRings = Array.isArray(boundary.rings) ? boundary.rings : [];
    const countyRings = Array.isArray(counties.features)
      ? counties.features.flatMap((feature) => Array.isArray(feature.coordinates) ? [feature.coordinates] : [])
      : [];
    resultsMapGeography = {
      boundary: boundaryRings.filter((ring) => Array.isArray(ring) && ring.length >= 3),
      counties: countyRings.filter((ring) => Array.isArray(ring) && ring.length >= 3),
    };
    return resultsMapGeography;
  }

  function renderResultsSummary(pkg) {
    const round = pkg.round;
    const team = pkg.team_report;
    setText("results-round-name", round.round_name || round.round_id);
    setText("results-team-name", team.team_id || round.team_id);
    setText("results-horizon", round.horizon_label);
    setText("results-feasibility", team.feasibility);
    setText("results-service-fraction", formatPercent(team.service_fraction));
    setText("results-score", formatNumber(team.score));
    setText("results-status", team.feasibility === "feasible" ? "Feasible" : team.feasibility === "not_evaluated" ? "Not evaluated" : "Projected");
    const list = element("results-score-breakdown");
    if (!list) return;
    list.replaceChildren();
    Object.entries(team.score_breakdown || {}).forEach(([label, value]) => {
      const term = document.createElement("dt");
      term.textContent = label.replaceAll("_", " ");
      const detail = document.createElement("dd");
      detail.textContent = formatNumber(value);
      list.append(term, detail);
    });
  }

  function renderTeamReport(pkg) {
    const report = element("results-team-report");
    if (!report) return;
    report.replaceChildren();
    const summary = document.createElement("p");
    summary.textContent = `${pkg.team_report.sites.length} connection site(s), ${pkg.team_report.generators.length} generator(s), and ${pkg.team_report.storage.length} storage device(s).`;
    report.append(summary);
    const list = document.createElement("dl");
    list.className = "results-metric-list";
    [["Sites", pkg.team_report.sites.length], ["Generators", pkg.team_report.generators.length], ["Storage devices", pkg.team_report.storage.length]].forEach(([label, value]) => {
      const term = document.createElement("dt");
      term.textContent = label;
      const detail = document.createElement("dd");
      detail.textContent = formatNumber(value, 0);
      list.append(term, detail);
    });
    report.append(list);
  }

  function renderAggregateSummary(pkg) {
    const report = element("results-aggregate-report");
    if (!report) return;
    report.replaceChildren();
    const note = document.createElement("p");
    note.textContent = pkg.aggregate.privacy_policy;
    report.append(note);
    const list = document.createElement("dl");
    list.className = "results-metric-list";
    Object.entries(pkg.aggregate.metrics || {}).forEach(([label, value]) => {
      const term = document.createElement("dt");
      term.textContent = label.replaceAll("_", " ");
      const detail = document.createElement("dd");
      detail.textContent = typeof value === "number" ? formatNumber(value) : String(value);
      list.append(term, detail);
    });
    report.append(list);
  }

  function renderResultsState(state, message) {
    const states = ["loading", "unavailable", "malformed"];
    states.forEach((name) => {
      const node = element(`results-${name}-state`);
      if (node) node.hidden = name !== state;
    });
    const contentVisible = state === "ready";
    ["results-summary", "results-map-panel", "results-team-inspector", "results-aggregate-summary"].forEach((id) => {
      const node = element(id);
      if (node) node.hidden = !contentVisible;
    });
    if (message && state !== "loading") {
      const node = element(`results-${state}-state`);
      if (node) node.textContent = message;
    }
  }

  function enterResultsMode() {
    document.body.classList.add("results-mode");
    const view = element("results-view");
    if (view) view.hidden = false;
    [".site-header", ".section-nav", "#status-banner", "#classroom-error-region", "#round-panel", "#workspace"].forEach((selector) => {
      const node = document.querySelector(selector);
      if (node) node.hidden = true;
    });
  }

  async function initializeResultsView() {
    enterResultsMode();
    renderResultsState("loading");
    try {
      const pkg = await loadResultsPackage();
      await loadResultsGeography();
      renderResultsSummary(pkg);
      renderTeamReport(pkg);
      renderAggregateSummary(pkg);
      renderResultsMap(pkg);
      const mapStatus = element("results-map-status");
      if (mapStatus) mapStatus.textContent = `${pkg.network.buses.length} buses · ${pkg.network.branches.length} branches`;
      const empty = element("results-map-empty");
      if (empty) empty.hidden = pkg.network.buses.length > 0 || pkg.network.branches.length > 0;
      renderResultsState(pkg.round.status === "unavailable" ? "unavailable" : "ready");
    } catch (error) {
      const state = error && error.state ? error.state : "unavailable";
      renderResultsState(state, error.message || "Results are unavailable.");
    }
  }

  window.loadResultsPackage = loadResultsPackage;
  window.validateBrowserPackage = validateBrowserPackage;
  window.renderResultsSummary = renderResultsSummary;
  window.renderTeamReport = renderTeamReport;
  window.renderAggregateSummary = renderAggregateSummary;
  window.renderResultsState = renderResultsState;
  window.adaptResultsNetwork = adaptResultsNetwork;
  window.renderResultsMap = renderResultsMap;
  window.setResultsMapView = setResultsMapView;
  window.loadResultsGeography = loadResultsGeography;

  const isResultsRoute = window.location.pathname.replace(/\/$/, "").endsWith("/results") || new URLSearchParams(window.location.search).get("view") === "results";
  if (isResultsRoute) {
    window.addEventListener("DOMContentLoaded", initializeResultsView, { once: true });
  }
})();
