/* global document, fetch */

const SVG_NS = "http://www.w3.org/2000/svg";
const MAX_TIME_HORIZON = 168;
const GEOGRAPHIC_VIEWPORT = { width: 960, height: 760 };
let TEXAS_BOUNDARY = { source: "texas-boundary.json", rings: [], error: "Texas boundary asset has not loaded." };
let TEXAS_COUNTIES = { source: "web/texas-counties.json", features: [] };
const DEFAULT_ERCOT_FOOTPRINT = { type: "Polygon", coordinates: [[[-106, 29], [-106, 36.5], [-93.5, 36.5], [-93.5, 29], [-106, 29]]] };
const DEFAULT_US_LOCATOR = { outline: [[-125, 24.5], [-125, 49.5], [-66, 49.5], [-66, 24.5], [-125, 24.5]], ercot_marker: [-99, 31] };
const requiredScoreFields = ["it_value", "energy_cost", "generator_cost", "flexibility_fee", "curtailment_cost", "unserved_penalty", "total"];
const state = { scenario: null, result: null, selectedResource: null, period: 0, publicNetwork: null, publicNetworkError: "", publicMetrics: { fetchMs: null, parseMs: null, renderMs: null, lastRenderZoom: null, lastTransmissionCount: 0, lastGenerationCount: 0, selectionMs: null, planningRenderMs: null, publicRenderMs: null, publicCandidateMs: null, countyRenderMs: null, geographicRenderMs: null, publicRenderCount: 0, countyRenderCount: 0 }, publicLayers: { transmission: true, teaching: true, generation: false }, geographicZoom: 1, geographicPan: { x: 0, y: 0 }, geographicDrag: null, submitting: false, connectionSerial: 0, generatorSerial: 0, planRevision: 0, scenarioRevision: 0, scenarioRequestToken: 0, scenarioRequestController: null, evaluationRequestToken: 0, evaluationRequestController: null, classroom: { token: null, roundId: null, session: null, sessionIdentity: null, sessionGeneration: 0, actionGeneration: 0, round: null, submission: null, leaderboard: null, saving: false, submitting: false, hydrated: false, saveRequestToken: 0, retry: null, retryAction: null, activeAction: null, instructorActionInFlight: false, instructorActionToken: 0, savedFingerprint: null, submittedFingerprint: null, pendingSubmissionKey: null, pendingSubmissionFingerprint: null, currentFingerprint: null, dirty: false, editRevision: 0, roundRequestToken: 0 } };

const resourceElementMaps = { schematic: new Map(), geographic: new Map() };

// Lightweight browser-only snapshot for release/performance audits; it does not
// participate in application behavior or evaluator requests.
window.__ercotMapMetrics = () => ({ ...state.publicMetrics });

const $ = (id) => document.getElementById(id);
const numberFormat = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 });
const moneyFormat = new Intl.NumberFormat(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const arrayOrEmpty = (value) => Array.isArray(value) ? value : [];
const objectOrEmpty = (value) => value && typeof value === "object" && !Array.isArray(value) ? value : {};
const isFiniteNumber = (value) => typeof value === "number" && Number.isFinite(value);
const isFiniteNumberArray = (value) => Array.isArray(value) && value.every(isFiniteNumber);
const isFiniteNumberArrayOfLength = (value, length) => isFiniteNumberArray(value) && value.length === length;
const isNonNegativeNumberArray = (value) => isFiniteNumberArray(value) && value.every((number) => number >= 0);

function displayNumber(value, suffix = "") {
  if (value === null || value === undefined || value === "") return "—";
  const number = Number(value);
  return Number.isFinite(number) ? `${numberFormat.format(number)}${suffix}` : "—";
}

function displayMoney(value) {
  const number = Number(value);
  return Number.isFinite(number) ? moneyFormat.format(number) : "—";
}

function displaySeries(values, suffix = "") {
  return Array.isArray(values) && values.length ? values.map((value) => displayNumber(value, suffix)).join(" · ") : "—";
}

function setStatus(message, tone = "") {
  const banner = $("status-banner");
  banner.textContent = message;
  banner.className = `status-banner${tone ? ` is-${tone}` : ""}`;
}

function updateScenarioMetadata(scenario) {
  const metadata = $("scenario-metadata");
  const value = metadata?.querySelector("strong");
  if (value) value.textContent = scenario?.scenario_id ? scenario.scenario_id : "Unavailable";
  const periods = $("header-periods");
  if (periods) periods.textContent = scenario?.time_horizon ? String(scenario.time_horizon).padStart(2, "0") : "—";
}

function setupSectionNavigation() {
  const links = [...document.querySelectorAll(".section-nav a[data-section-target]")];
  const sections = links.map((link) => document.getElementById(link.dataset.sectionTarget)).filter(Boolean);
  const activate = (id) => links.forEach((link) => {
    if (link.dataset.sectionTarget === id) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  links.forEach((link) => link.addEventListener("click", () => activate(link.dataset.sectionTarget)));
  if ("IntersectionObserver" in window) {
    const observer = new IntersectionObserver((entries) => {
      const visible = entries.filter((entry) => entry.isIntersecting && (entry.target.id !== "classroom-section" || !( $("round-panel")?.hidden ))).sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
      if (visible) activate(visible.target.id);
    }, { rootMargin: "-18% 0px -62% 0px", threshold: [0.05, 0.25, 0.6] });
    sections.forEach((section) => observer.observe(section));
  }
}

function appendMetric(parent, label, value) {
  const term = document.createElement("dt");
  term.textContent = label;
  const definition = document.createElement("dd");
  definition.textContent = value;
  parent.append(term, definition);
}

function resourceTypeForId(id) {
  if (arrayOrEmpty(state.scenario?.buses).some((bus) => bus.bus_id === id)) return "bus";
  if (arrayOrEmpty(state.scenario?.corridors).some((corridor) => corridor.corridor_id === id)) return "corridor";
  return "";
}

function focusResource(type, id) {
  openResourceDrawer(type, id);
  document.getElementById("network-section")?.scrollIntoView({ behavior: "smooth", block: "start" });
  window.setTimeout(() => {
    const selector = `[data-resource-type="${type}"][data-resource-id="${CSS.escape(id)}"]`;
    document.querySelector(selector)?.focus();
  }, 260);
}

function appendResourceMetric(parent, label, values) {
  const term = document.createElement("dt"); term.textContent = label;
  const definition = document.createElement("dd");
  const ids = arrayOrEmpty(values).map(String).filter(Boolean);
  if (!ids.length) definition.textContent = "None reported";
  ids.forEach((id, index) => {
    const resourceId = mapResourceId(id) || id;
    const type = resourceTypeForId(resourceId);
    if (!type) { if (index) definition.append(", "); definition.append(id); return; }
    const link = document.createElement("button"); link.type = "button"; link.className = "resource-link"; link.textContent = id; link.setAttribute("aria-label", `Show ${type} ${id} on the network`); link.addEventListener("click", () => focusResource(type, resourceId));
    if (index) definition.append(", "); definition.appendChild(link);
  });
  parent.append(term, definition);
}

function appendTextElement(parent, tagName, className, text) {
  const element = document.createElement(tagName);
  if (className) element.className = className;
  element.textContent = text;
  parent.appendChild(element);
  return element;
}

function makeSvgElement(name, attributes = {}) {
  const element = document.createElementNS(SVG_NS, name);
  Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, String(value)));
  return element;
}

function createSemanticIcon(iconId) {
  const icon = makeSvgElement("svg", { class: "semantic-icon", viewBox: "0 0 24 24", "aria-hidden": "true" });
  icon.appendChild(makeSvgElement("use", { href: `#${iconId}`, "aria-hidden": "true" }));
  return icon;
}

function coordinatePairs(value, output = []) {
  if (!Array.isArray(value)) return output;
  if (value.length >= 2 && typeof value[0] === "number" && Number.isFinite(value[0]) && typeof value[1] === "number" && Number.isFinite(value[1])) {
    output.push([value[0], value[1]]);
    return output;
  }
  value.forEach((child) => coordinatePairs(child, output));
  return output;
}

function polygonRings(footprint) {
  const value = objectOrEmpty(footprint);
  const coordinates = Array.isArray(value.coordinates) ? value.coordinates : footprint;
  if (!Array.isArray(coordinates)) return [];
  const rings = coordinates[0]?.[0]?.[0] !== undefined ? coordinates[0] : coordinates;
  return Array.isArray(rings) ? rings.filter((ring) => coordinatePairs(ring).length >= 3) : [];
}

function busPresentation(bus) {
  const mapped = objectOrEmpty(state.scenario?.map?.bus_coordinates?.[bus.bus_id]);
  return Object.keys(mapped).length ? mapped : objectOrEmpty(bus.presentation);
}

function humanizePlanningRegionId(value) {
  return String(value || "Region").replaceAll("_", " ").toLowerCase().replace(/(^|\s)\S/g, (letter) => letter.toUpperCase());
}

function busPoint(bus) {
  const presentation = busPresentation(bus);
  const longitude = Number(presentation.longitude ?? presentation.lon);
  const latitude = Number(presentation.latitude ?? presentation.lat);
  if (Number.isFinite(longitude) && Number.isFinite(latitude)) return [longitude, latitude];
  const coordinates = coordinatePairs(presentation.coordinates);
  if (coordinates[0]) return coordinates[0];
  const index = state.scenario?.buses?.findIndex((candidate) => candidate.bus_id === bus.bus_id) ?? -1;
  return [-101 + (Math.max(index, 0) % 8) * 1.1, 35 - (Math.max(index, 0) % 5) * 1.2];
}

function corridorPath(corridor) {
  const mapped = state.scenario?.map?.corridor_paths?.[corridor.corridor_id];
  if (Array.isArray(mapped) && coordinatePairs(mapped).length >= 2) return mapped;
  const presentation = objectOrEmpty(corridor.presentation);
  if (Array.isArray(presentation.path) && coordinatePairs(presentation.path).length >= 2) return presentation.path;
  const geometryPath = coordinatePairs(presentation.geometry?.coordinates);
  if (geometryPath.length >= 2) return geometryPath;
  const buses = arrayOrEmpty(state.scenario?.buses);
  const index = state.scenario?.corridors?.findIndex((candidate) => candidate.corridor_id === corridor.corridor_id) ?? 0;
  return buses.length >= 2 ? [busPoint(buses[index % buses.length]), busPoint(buses[(index + 1) % buses.length])] : [];
}

function pathData(points, project) {
  return points.map((point, index) => { const [x, y] = project(point); return `${index === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`; }).join(" ");
}

function normalizeBindingId(value) {
  const resourceId = String(value);
  const prefixed = /^(?:bus|corridor):(.+)$/.exec(resourceId);
  return prefixed ? prefixed[1] : resourceId;
}

function mapResourceId(value) {
  if (typeof value !== "string") return "";
  const prefixed = /^(?:bus|corridor):(.+)$/.exec(value);
  return prefixed ? prefixed[1] : "";
}

function bindingResourceIds() {
  const aggregate = objectOrEmpty(state.result?.aggregate_diagnostics);
  const team = state.result?.team_results?.[0] || {};
  const diagnostics = objectOrEmpty(team.diagnostics);
  const violations = [...arrayOrEmpty(aggregate.violations), ...arrayOrEmpty(diagnostics.violations)].flatMap((violation) => {
    if (typeof violation === "string") return [violation];
    const item = objectOrEmpty(violation);
    return [item.resource_id, item.resource, item.id].filter((value) => value !== undefined && value !== null);
  });
  return new Set([...arrayOrEmpty(aggregate.binding_resources), ...arrayOrEmpty(diagnostics.binding_resources), ...violations].map(mapResourceId).filter(Boolean));
}

function selectedPeriodValue(items, id, field, fallback = 0) {
  const selected = arrayOrEmpty(state.scenario?.selected_period?.[items]).find((item) => item?.[`${items === "buses" ? "bus" : "corridor"}_id`] === id);
  if (selected && isFiniteNumber(Number(selected[field]))) return Number(selected[field]);
  const item = state.scenario?.[items]?.find((candidate) => candidate?.[`${items === "buses" ? "bus" : "corridor"}_id`] === id);
  return Number(item?.[field === "headroom_mw" ? "selected_period_headroom_mw" : "selected_period_capacity_mw"] ?? fallback);
}

function mapBounds(buses, corridors, footprintPositions) {
  const points = [...footprintPositions, ...buses.map(busPoint), ...corridors.flatMap(corridorPath)];
  if (!points.length) return { minLon: -106, maxLon: -93, minLat: 28, maxLat: 37 };
  const longitudes = points.map((point) => point[0]);
  const latitudes = points.map((point) => point[1]);
  const minLon = Math.min(...longitudes); const maxLon = Math.max(...longitudes); const minLat = Math.min(...latitudes); const maxLat = Math.max(...latitudes);
  return { minLon: minLon === maxLon ? minLon - 1 : minLon, maxLon: minLon === maxLon ? maxLon + 1 : maxLon, minLat: minLat === maxLat ? minLat - 1 : minLat, maxLat: minLat === maxLat ? maxLat + 1 : maxLat };
}

function projectPoint(point, bounds, frame = { x: 55, y: 75, width: 850, height: 470 }) {
  return [frame.x + ((point[0] - bounds.minLon) / (bounds.maxLon - bounds.minLon)) * frame.width, frame.y + (1 - (point[1] - bounds.minLat) / (bounds.maxLat - bounds.minLat)) * frame.height];
}

function geographicBoundaryRings() {
  return arrayOrEmpty(TEXAS_BOUNDARY.rings).filter((ring) => coordinatePairs(ring).length >= 3);
}

function geographicBounds() {
  const points = geographicBoundaryRings().flatMap((ring) => coordinatePairs(ring));
  if (!points.length) return { minLon: -106.65, maxLon: -93.5, minLat: 25.8, maxLat: 36.5 };
  const longitudes = points.map((point) => point[0]);
  const latitudes = points.map((point) => point[1]);
  const lonSpan = Math.max(...longitudes) - Math.min(...longitudes);
  const latSpan = Math.max(...latitudes) - Math.min(...latitudes);
  const lonPadding = Math.max(lonSpan * 0.08, 0.15);
  const latPadding = Math.max(latSpan * 0.08, 0.15);
  return { minLon: Math.min(...longitudes) - lonPadding, maxLon: Math.max(...longitudes) + lonPadding, minLat: Math.min(...latitudes) - latPadding, maxLat: Math.max(...latitudes) + latPadding };
}

function projectGeographicPoint(point, frame = { x: 55, y: 40, width: 850, height: 680 }) {
  // Correct longitude distances by the representative latitude so the physical locator
  // does not stretch Texas horizontally as an unprojected degree grid would.
  const bounds = geographicBounds();
  const longitudeSpan = bounds.maxLon - bounds.minLon;
  const latitudeSpan = bounds.maxLat - bounds.minLat;
  const referenceLatitude = ((bounds.minLat + bounds.maxLat) / 2) * Math.PI / 180;
  const longitudeCorrection = Math.cos(referenceLatitude);
  const projectedLongitudeSpan = longitudeSpan * longitudeCorrection;
  const scale = Math.min(frame.width / projectedLongitudeSpan, frame.height / latitudeSpan);
  const contentWidth = projectedLongitudeSpan * scale;
  const contentHeight = latitudeSpan * scale;
  const offsetX = frame.x + (frame.width - contentWidth) / 2;
  const offsetY = frame.y + (frame.height - contentHeight) / 2;
  const normalizedLatitude = (point[1] - bounds.minLat) / latitudeSpan;
  return [offsetX + (point[0] - bounds.minLon) * longitudeCorrection * scale, offsetY + (1 - normalizedLatitude) * contentHeight];
}

function publicVoltageClass(voltage) {
  const value = Number(voltage);
  if (!Number.isFinite(value)) return "unknown";
  if (value >= 230) return "very-high";
  if (value >= 115) return "high";
  return "lower";
}

function publicNetworkVisibleBounds() {
  const bounds = geographicBounds();
  const frame = { x: 55, y: 40, width: 850, height: 680 };
  const referenceLatitude = ((bounds.minLat + bounds.maxLat) / 2) * Math.PI / 180;
  const correction = Math.cos(referenceLatitude);
  const scale = Math.min(frame.width / ((bounds.maxLon - bounds.minLon) * correction), frame.height / (bounds.maxLat - bounds.minLat));
  const contentWidth = (bounds.maxLon - bounds.minLon) * correction * scale;
  const contentHeight = (bounds.maxLat - bounds.minLat) * scale;
  const offsetX = frame.x + (frame.width - contentWidth) / 2;
  const offsetY = frame.y + (frame.height - contentHeight) / 2;
  const left = (-state.geographicPan.x / state.geographicZoom - offsetX) / (correction * scale) + bounds.minLon;
  const right = ((GEOGRAPHIC_VIEWPORT.width - state.geographicPan.x) / state.geographicZoom - offsetX) / (correction * scale) + bounds.minLon;
  const top = bounds.maxLat - (((-state.geographicPan.y / state.geographicZoom) - offsetY) / scale);
  const bottom = bounds.maxLat - ((((GEOGRAPHIC_VIEWPORT.height - state.geographicPan.y) / state.geographicZoom) - offsetY) / scale);
  return { minLon: Math.min(left, right), maxLon: Math.max(left, right), minLat: Math.min(bottom, top), maxLat: Math.max(bottom, top) };
}

function publicBboxVisible(bbox, visible) {
  return Array.isArray(bbox) && bbox.length === 4 && bbox[2] >= visible.minLon && bbox[0] <= visible.maxLon && bbox[3] >= visible.minLat && bbox[1] <= visible.maxLat;
}

function publicLineCandidates() {
  const startedAt = performance.now();
  const branches = arrayOrEmpty(state.publicNetwork?.branches);
  const zoom = state.geographicZoom;
  const visible = publicNetworkVisibleBounds();
  const candidates = branches.filter((branch) => {
    if (!publicBboxVisible(branch.bbox, visible)) return false;
    if (zoom <= 1.3) return Number(branch.nominal_kv) >= 230;
    if (zoom <= 2) return Number(branch.nominal_kv) >= 115 || branch.nominal_kv === null;
    return true;
  });
  state.publicMetrics.publicCandidateMs = performance.now() - startedAt;
  return candidates;
}

function publicPlantCandidates() {
  const plants = arrayOrEmpty(state.publicNetwork?.plants);
  const generators = arrayOrEmpty(state.publicNetwork?.generators);
  const aggregate = new Map();
  generators.forEach((generator) => {
    const current = aggregate.get(generator.plant_id) || { capacity: 0, count: 0, technologies: new Set() };
    current.capacity += Number(generator.nameplate_capacity_mw) || 0;
    current.count += 1;
    if (generator.technology) current.technologies.add(generator.technology);
    aggregate.set(generator.plant_id, current);
  });
  const visible = publicNetworkVisibleBounds();
  const minimumCapacity = state.geographicZoom <= 1.3 ? 100 : state.geographicZoom <= 2 ? 25 : 0;
  return plants.filter((plant) => {
    const capacity = aggregate.get(plant.plant_id)?.capacity || 0;
    return Number.isFinite(plant.longitude) && Number.isFinite(plant.latitude) && capacity >= minimumCapacity && inVisibleCoordinate(plant.longitude, plant.latitude, visible);
  }).map((plant) => ({ plant, aggregate: aggregate.get(plant.plant_id) || { capacity: 0, count: 0, technologies: new Set() } }));
}

function inVisibleCoordinate(longitude, latitude, visible) {
  return longitude >= visible.minLon && longitude <= visible.maxLon && latitude >= visible.minLat && latitude <= visible.maxLat;
}

function showPublicTooltip(kind, item, event, anchor) {
  const tooltip = ensureGeographicTooltip();
  tooltip.replaceChildren();
  const heading = document.createElement("strong");
  if (kind === "transmission") heading.textContent = `Public transmission ${item.branch_id}`;
  else heading.textContent = item.plant.name || item.plant.plant_id;
  tooltip.appendChild(heading);
  const lines = kind === "transmission"
    ? [["Source", "HIFLD public transmission geography"], ["Voltage", item.nominal_kv ? `${displayNumber(item.nominal_kv, " kV")}` : "Not reported"], ["Topology", "Geographic line; not an ERCOT bus-branch connection"]]
    : [["EIA plant ID", item.plant.plant_id.replace(/^eia_plant_/, "")], ["Generation", `${displayNumber(item.aggregate.capacity, " MW")} · ${item.aggregate.count} generators`], ["Technology", [...item.aggregate.technologies].slice(0, 2).join(", ") || "Not reported"]];
  lines.forEach(([label, value]) => appendTextElement(tooltip, "span", "", `${label}: ${value}`));
  tooltip.hidden = false;
  positionMapTooltip(tooltip, event, anchor, $("geographic-map-frame"));
}

function geographicTransform() {
  const { x, y } = state.geographicPan;
  return `translate(${x.toFixed(1)} ${y.toFixed(1)}) scale(${state.geographicZoom.toFixed(3)})`;
}

function geographicPanBounds(zoom) {
    const content = { left: 55, right: 905, top: 40, bottom: 720 };
  return {
    minX: Math.min(0, GEOGRAPHIC_VIEWPORT.width - content.right * zoom),
    maxX: Math.max(0, -content.left * zoom),
    minY: Math.min(0, GEOGRAPHIC_VIEWPORT.height - content.bottom * zoom),
    maxY: Math.max(0, -content.top * zoom),
  };
}

function clampGeographicPan(pan, zoom = state.geographicZoom) {
  const bounds = geographicPanBounds(zoom);
  return {
    x: Math.min(bounds.maxX, Math.max(bounds.minX, pan.x)),
    y: Math.min(bounds.maxY, Math.max(bounds.minY, pan.y)),
  };
}

function setGeographicZoom(nextZoom, anchor = { x: 480, y: 250 }) {
  const previous = state.geographicZoom;
  const zoom = Math.min(3.2, Math.max(1, nextZoom));
  const scale = zoom / previous;
  state.geographicPan = clampGeographicPan({
    x: anchor.x - (anchor.x - state.geographicPan.x) * scale,
    y: anchor.y - (anchor.y - state.geographicPan.y) * scale,
  }, zoom);
  state.geographicZoom = zoom;
  renderGeographicMap();
}

function resetGeographicViewport() {
  cancelGeographicDrag();
  state.geographicZoom = 1;
  state.geographicPan = { x: 0, y: 0 };
  renderGeographicMap();
}

function headroomClass(bus) {
  const value = selectedPeriodValue("buses", bus.bus_id, "headroom_mw");
  if (value < 35) return "headroom-low";
  if (value < 65) return "headroom-mid";
  return "headroom-high";
}

function positionMapTooltip(tooltip, event, anchor, frameElement) {
  const frame = (frameElement || $("map-frame")).getBoundingClientRect();
  const tooltipWidth = tooltip.offsetWidth;
  const tooltipHeight = tooltip.offsetHeight;
  const padding = 8;
  let left = padding;
  let top = padding;
  const pointerX = Number(event?.clientX);
  const pointerY = Number(event?.clientY);
  if (Number.isFinite(pointerX) && Number.isFinite(pointerY)) {
    left = pointerX - frame.left + 12;
    top = pointerY - frame.top - tooltipHeight - 12;
    if (top < padding) top = pointerY - frame.top + 12;
  } else {
    const anchorRect = anchor?.getBoundingClientRect();
    if (anchorRect) {
      left = anchorRect.right - frame.left + padding;
      top = anchorRect.top - frame.top - tooltipHeight - padding;
      if (left + tooltipWidth > frame.width - padding) left = anchorRect.left - frame.left - tooltipWidth - padding;
      if (top < padding) top = anchorRect.bottom - frame.top + padding;
    }
  }
  const maxLeft = Math.max(padding, frame.width - tooltipWidth - padding);
  const maxTop = Math.max(padding, frame.height - tooltipHeight - padding);
  tooltip.style.left = `${Math.min(Math.max(padding, left), maxLeft)}px`;
  tooltip.style.top = `${Math.min(Math.max(padding, top), maxTop)}px`;
}

function showMapTooltip(resource, event) {
  const tooltip = resource.map === "geographic" ? ensureGeographicTooltip() : $("map-tooltip");
  const planningMode = Boolean(state.scenario?.planning_model?.model_id);
  const kind = resource.type === "bus" ? (planningMode ? "Planning Region" : "Synthetic teaching bus") : (planningMode ? "Planning Interface" : "Teaching corridor");
  const item = objectOrEmpty(resource?.item);
  const presentation = resourcePresentation(resource);
  const value = resource.type === "bus" ? selectedPeriodValue("buses", item.bus_id, "headroom_mw") : selectedPeriodValue("corridors", item.corridor_id, "capacity_mw");
  const endpointSummary = resource.type === "corridor"
    ? `${planningMode ? "Planning regions" : "Teaching endpoints"}: ${presentation.from_region || presentation.from_bus_id || "Unknown endpoint"} → ${presentation.to_region || presentation.to_bus_id || "Unknown endpoint"}`
    : `${presentation.label || presentation.zone || (planningMode ? "Planning region" : "Teaching zone")}${planningMode ? "" : " · synthetic location"}`;
  const measureLabel = resource.type === "bus" ? (planningMode ? "Scenario headroom" : "Headroom") : (planningMode ? "Scenario transfer limit" : "Capacity");
  tooltip.setAttribute("aria-live", "polite");
  tooltip.replaceChildren();
  appendTextElement(tooltip, "strong", "", `${kind}: ${resource.id}`);
  appendTextElement(tooltip, "span", "", endpointSummary);
  appendTextElement(tooltip, "span", "", `Selected period ${state.period + 1}: ${measureLabel} ${displayNumber(value, " MW")}`);
  appendTextElement(tooltip, "span", "", resourceHint(resource));
  tooltip.hidden = false;
  const frame = resource.map === "geographic" ? $("geographic-map-frame") : $("map-frame");
  positionMapTooltip(tooltip, event, resource.node, frame);
}

function ensureGeographicTooltip() {
  const frame = $("geographic-map-frame");
  if (!frame) return $("map-tooltip");
  const existing = $("geographic-map-tooltip");
  if (existing) return existing;
  const tooltip = document.createElement("div");
  tooltip.id = "geographic-map-tooltip";
  tooltip.className = "map-tooltip";
  tooltip.setAttribute("role", "tooltip");
  tooltip.setAttribute("aria-live", "polite");
  tooltip.hidden = true;
  frame.appendChild(tooltip);
  return tooltip;
}

function hideGeographicTooltip() {
  const tooltip = $("geographic-map-tooltip");
  if (!tooltip) return;
  tooltip.hidden = true;
  tooltip.replaceChildren();
}

function hideMapTooltip(resource) {
  const tooltipId = resource?.map === "geographic" ? "geographic-map-tooltip" : "map-tooltip";
  if (document.activeElement?.getAttribute("aria-describedby") === tooltipId) return;
  $(tooltipId).hidden = true;
}

function resourcePresentation(resource) {
  const item = objectOrEmpty(resource?.item);
  return resource?.type === "bus" ? busPresentation(item) : objectOrEmpty(item.presentation);
}

function resourceElementKey(type, id) {
  return `${type}:${id}`;
}

function registerResourceElement(mapName, type, id, element) {
  resourceElementMaps[mapName].set(resourceElementKey(type, id), element);
}

function updateResourceElementState(element, type, selected) {
  if (!element) return;
  if (type === "bus") {
    element.classList.toggle("is-selected", selected);
    const frame = element.querySelector(".bus-selection-frame");
    if (selected && !frame) element.appendChild(makeSvgElement("rect", { class: "bus-selection-frame", x: -19, y: -19, width: 38, height: 38 }));
    if (!selected) frame?.remove();
    element.setAttribute("aria-pressed", selected ? "true" : "false");
    return;
  }
  element.querySelectorAll(".map-corridor").forEach((path) => path.classList.toggle("is-selected", selected));
  element.querySelector('[role="button"]')?.setAttribute("aria-pressed", selected ? "true" : "false");
}

function updateResourceSelectionState() {
  const startedAt = performance.now();
  for (const [mapName, elements] of Object.entries(resourceElementMaps)) {
    elements.forEach((element, key) => {
      const separator = key.indexOf(":");
      const type = key.slice(0, separator);
      const id = key.slice(separator + 1);
      updateResourceElementState(element, type, state.selectedResource?.type === type && state.selectedResource.id === id);
    });
    if (mapName === "geographic") {
      const selected = state.selectedResource;
      $("geographic-map")?.setAttribute("data-selected-resource", selected ? `${selected.type}:${selected.id}` : "none");
    }
  }
  state.publicMetrics.selectionMs = performance.now() - startedAt;
}

function resourceHint(resource) {
  const planningMode = Boolean(state.scenario?.planning_model?.model_id);
  return resourcePresentation(resource).tutorial_hint || (resource.type === "bus" ? "Compare this period's headroom with the capacity of a proposed site." : planningMode ? "A shared planning interface can bind when several sites select this path in the same period." : "A shared corridor can bind when several sites select this path in the same period.");
}

function openResourceDrawer(type, id) {
  // Plan mutations from this drawer route through addConnectionAtBus, which calls markClassroomDirty().
  const items = type === "bus" ? state.scenario?.buses : state.scenario?.corridors;
  const item = arrayOrEmpty(items).find((candidate) => candidate?.[type === "bus" ? "bus_id" : "corridor_id"] === id);
  if (!item) return;
  state.selectedResource = { type, id };
  const presentation = objectOrEmpty(item.presentation);
  const value = type === "bus" ? selectedPeriodValue("buses", id, "headroom_mw") : selectedPeriodValue("corridors", id, "capacity_mw");
  $("resource-drawer-heading").textContent = presentation.label || id;
  const content = $("resource-drawer-content");
  content.replaceChildren();
  if (type === "bus") content.appendChild(createSemanticIcon("icon-bus"));
  if (type === "corridor") content.appendChild(createSemanticIcon("icon-corridor"));
  const metrics = document.createElement("div"); metrics.className = "drawer-metrics";
  const planningMode = Boolean(state.scenario?.planning_model?.model_id);
  const details = type === "bus" ? [[planningMode ? "Planning Region ID" : "Synthetic ID", id], [planningMode ? "Planning Region" : "Teaching zone", presentation.label || presentation.zone || "—"], [planningMode ? "Scenario headroom" : "Headroom", displayNumber(value, " MW")]] : [[planningMode ? "Planning Interface ID" : "Teaching ID", id], [planningMode ? "From planning region" : "From teaching bus", presentation.from_region || presentation.from_bus_id || "—"], [planningMode ? "Scenario transfer limit" : "Capacity", displayNumber(value, " MW")]];
  details.forEach(([label, detail]) => { const block = document.createElement("div"); const term = document.createElement("dt"); term.textContent = label; const definition = document.createElement("dd"); definition.textContent = detail; block.append(term, definition); metrics.append(block); });
  content.appendChild(metrics);
  if (type === "corridor") { const to = document.createElement("p"); to.className = "drawer-hint"; to.textContent = `${planningMode ? "To planning region" : "To teaching bus"}: ${presentation.to_region || presentation.to_bus_id || "—"}`; content.appendChild(to); }
  const publicEvidence = objectOrEmpty(presentation.public_evidence);
  if (planningMode && Object.keys(publicEvidence).length) {
    const publicBlock = document.createElement("section"); publicBlock.className = "drawer-provenance drawer-provenance-public";
    const publicTitle = document.createElement("strong"); publicTitle.textContent = "PUBLIC-DERIVED / PLANNING CONTEXT"; publicBlock.appendChild(publicTitle);
    const publicText = document.createElement("p"); publicText.textContent = type === "bus" ? `${publicEvidence.transmission_geometry_count ?? 0} public transmission geometries · ${displayNumber(publicEvidence.transmission_length_km, " km")} · ${publicEvidence.plant_count ?? 0} public plants` : `${publicEvidence.public_geometry_count ?? 0} public crossing geometries · ${publicEvidence.high_voltage_geometry_count ?? 0} high-voltage evidence geometries`;
    publicBlock.appendChild(publicText); content.appendChild(publicBlock);
    const teachingBlock = document.createElement("section"); teachingBlock.className = "drawer-provenance drawer-provenance-teaching";
    const teachingTitle = document.createElement("strong"); teachingTitle.textContent = "TEACHING SCENARIO"; teachingBlock.appendChild(teachingTitle);
    const teachingText = document.createElement("p"); teachingText.textContent = type === "bus" ? "Headroom is an instructional scenario condition, not a public physical rating." : "Transfer limit is an instructional scenario condition, not the rating of a single physical transmission line.";
    teachingBlock.appendChild(teachingText); content.appendChild(teachingBlock);
  }
  if (state.result) { const status = document.createElement("p"); status.className = `drawer-evaluator-status ${bindingResourceIds().has(normalizeBindingId(id)) ? "is-flagged" : "is-clear"}`; status.textContent = bindingResourceIds().has(normalizeBindingId(id)) ? "Evaluator status: Binding / flagged" : "Evaluator status: Clear"; content.appendChild(status); }
  const hint = document.createElement("p"); hint.className = "drawer-hint"; hint.textContent = resourceHint({ type, item }); content.appendChild(hint);
  if (type === "bus") { const button = document.createElement("button"); button.type = "button"; button.className = "secondary-button"; button.textContent = `Add connection at ${id}`; button.addEventListener("click", () => addConnectionAtBus(id)); content.appendChild(button); }
  $("map-selection").textContent = `${planningMode ? (type === "bus" ? "Planning region" : "Planning interface") : (type === "bus" ? "Teaching bus" : "Teaching corridor")} selected: ${id}`;
  updateResourceSelectionState();
}

function openSiteDrawer(card) {
  const draft = connectionDrafts()[[...document.querySelectorAll(".connection-card")].indexOf(card)];
  if (!draft) return;
  state.selectedResource = { type: "site", id: draft.connection_id };
  $("resource-drawer-heading").textContent = draft.connection_id || "Unnamed connection site";
  const content = $("resource-drawer-content");
  content.replaceChildren();
  content.appendChild(createSemanticIcon("icon-connection"));
  const metrics = document.createElement("div"); metrics.className = "drawer-metrics";
  [["Bus", draft.bus_id || "—"], ["Capacity", displayNumber(draft.capacity_mw, " MW")], ["Path", draft.path_corridors.length ? draft.path_corridors.join(", ") : "No corridors"]].forEach(([label, value]) => { const block = document.createElement("div"); const term = document.createElement("dt"); term.textContent = label; const definition = document.createElement("dd"); definition.textContent = value; block.append(term, definition); metrics.append(block); });
  content.appendChild(metrics);
  const profile = document.createElement("p"); profile.className = "drawer-hint"; profile.textContent = `Profile by period: ${draft.profile.map((value) => displayNumber(value)).join(" · ")}`; content.appendChild(profile);
  const hint = document.createElement("p"); hint.className = "drawer-hint"; hint.textContent = "This site is part of the canonical plan sent to the server evaluator."; content.appendChild(hint);
  $("map-selection").textContent = `Connection site selected: ${draft.connection_id || "Unnamed"}`;
  updateResourceSelectionState();
}

function renderLocator(layer, locator) {
  const outline = coordinatePairs(locator.outline); if (outline.length < 3) return;
  const frame = { x: 730, y: 28, width: 180, height: 92 }; layer.appendChild(makeSvgElement("rect", { class: "locator-box", x: frame.x, y: frame.y, width: frame.width, height: frame.height, rx: 8 }));
  const longs = outline.map((point) => point[0]); const lats = outline.map((point) => point[1]); const bounds = { minLon: Math.min(...longs), maxLon: Math.max(...longs), minLat: Math.min(...lats), maxLat: Math.max(...lats) }; const project = (point) => projectPoint(point, bounds, { x: frame.x + 10, y: frame.y + 18, width: frame.width - 20, height: frame.height - 30 });
  layer.appendChild(makeSvgElement("path", { class: "locator-outline", d: `${pathData(outline, project)} Z` })); const marker = coordinatePairs(locator.ercot_marker)[0]; if (marker) { const [x, y] = project(marker); layer.appendChild(makeSvgElement("circle", { class: "locator-marker", cx: x, cy: y, r: 5 })); }
  const label = makeSvgElement("text", { class: "locator-label", x: frame.x + 11, y: frame.y + 14 }); label.textContent = locator.ercot_label || "US locator · ERCOT"; layer.appendChild(label);
}

function renderLegend() {
  const evaluated = Boolean(state.result); $("legend-low-item").hidden = evaluated; $("legend-high-item").hidden = evaluated; $("legend-clear-item").hidden = !evaluated; $("legend-binding-label").textContent = evaluated ? "Evaluator binding / violation" : "Binding / flagged";
  if ($("legend-public-transmission")) $("legend-public-transmission").hidden = !state.publicLayers.transmission || !state.publicNetwork;
  if ($("legend-public-generation")) $("legend-public-generation").hidden = !state.publicLayers.generation || !state.publicNetwork;
}

function resourceEventHandlers(node, resource) {
  resource.map = resource.map || "schematic";
  resource.node = node;
  node.setAttribute("aria-describedby", resource.map === "geographic" ? "geographic-map-tooltip" : "map-tooltip");
  node.addEventListener("mouseenter", (event) => showMapTooltip(resource, event)); node.addEventListener("mousemove", (event) => showMapTooltip(resource, event)); node.addEventListener("mouseleave", () => hideMapTooltip(resource)); node.addEventListener("focus", () => showMapTooltip(resource)); node.addEventListener("blur", () => hideMapTooltip(resource)); node.addEventListener("click", () => openResourceDrawer(resource.type, resource.id));
  node.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); openResourceDrawer(resource.type, resource.id); } });
}

function renderMap() {
  if (!state.scenario) return;
  const tooltip = $("map-tooltip");
  if (tooltip) {
    tooltip.hidden = true;
    tooltip.replaceChildren();
  }
  resourceElementMaps.schematic.clear();
  const layers = ["map-grid-layer", "map-footprint-layer", "map-zones-layer", "map-corridors-layer", "map-buses-layer", "map-locator-layer"].map($); layers.forEach((layer) => layer?.replaceChildren());
  renderLegend(); const buses = arrayOrEmpty(state.scenario.buses); const corridors = arrayOrEmpty(state.scenario.corridors); const footprint = state.scenario.map?.footprint || state.scenario.presentation?.footprint || DEFAULT_ERCOT_FOOTPRINT; const locator = objectOrEmpty(state.scenario.map?.locator || state.scenario.presentation?.locator); const locatorForRender = coordinatePairs(locator.outline).length >= 3 ? locator : DEFAULT_US_LOCATOR; const footprintPositions = coordinatePairs(footprint?.coordinates || footprint); const bounds = mapBounds(buses, corridors, footprintPositions); const project = (point) => projectPoint(point, bounds); const binding = bindingResourceIds();
  const grid = $("map-grid-layer"); for (let x = 1; x < 7; x += 1) grid.appendChild(makeSvgElement("line", { class: "map-grid-line", x1: 55 + x * 141.7, x2: 55 + x * 141.7, y1: 75, y2: 545 })); for (let y = 1; y < 5; y += 1) grid.appendChild(makeSvgElement("line", { class: "map-grid-line", x1: 55, x2: 905, y1: 75 + y * 94, y2: 75 + y * 94 }));
  const ring = polygonRings(footprint)[0] || footprintPositions; if (ring.length >= 3) $("map-footprint-layer").appendChild(makeSvgElement("path", { class: "map-footprint", d: `${pathData(ring, project)} Z`, "aria-label": "ERCOT teaching footprint" }));
  const zones = arrayOrEmpty(state.scenario.map?.zones || state.scenario.zones); const zonePositions = {}; buses.forEach((bus) => { const zone = busPresentation(bus).zone; if (zone && !zonePositions[zone]) zonePositions[zone] = []; zonePositions[zone]?.push(busPoint(bus)); });
  Object.entries(zonePositions).forEach(([zone, points]) => { const point = points.reduce((sum, current) => [sum[0] + current[0], sum[1] + current[1]], [0, 0]).map((value) => value / points.length); const [x, y] = project(point); const label = makeSvgElement("text", { class: "map-zone-label", x, y }); label.textContent = zones.find((item) => item.zone === zone)?.label || `${zone} zone`; $("map-zones-layer").appendChild(label); });
  corridors.forEach((corridor) => { const points = corridorPath(corridor); if (points.length < 2) return; const selected = state.selectedResource?.type === "corridor" && state.selectedResource.id === corridor.corridor_id; const flagged = binding.has(normalizeBindingId(corridor.corridor_id)); const evaluationClass = state.result ? (flagged ? " is-binding" : " is-clear") : ""; const d = pathData(points, project); const group = makeSvgElement("g", { class: "map-corridor-group" }); const path = makeSvgElement("path", { class: `map-corridor${evaluationClass}${selected ? " is-selected" : ""}`, d, "aria-hidden": "true", "pointer-events": "none" }); const hitPath = makeSvgElement("path", { class: "map-corridor-hit", d, role: "button", tabindex: "0", "aria-label": `Select ${state.scenario?.planning_model?.model_id ? "planning interface" : "teaching corridor"} ${corridor.corridor_id}`, "data-resource-type": "corridor", "data-resource-id": corridor.corridor_id }); resourceEventHandlers(hitPath, { type: "corridor", id: corridor.corridor_id, item: corridor }); group.append(path, hitPath); const midpoint = project(points[Math.floor(points.length / 2)]); const label = makeSvgElement("text", { class: "map-corridor-label", x: midpoint[0] + 7, y: midpoint[1] - 8 }); label.textContent = corridor.corridor_id; group.appendChild(label); $("map-corridors-layer").appendChild(group); registerResourceElement("schematic", "corridor", corridor.corridor_id, group); });
  buses.forEach((bus) => { const point = busPoint(bus); const [x, y] = project(point); const presentation = busPresentation(bus); const selected = state.selectedResource?.type === "bus" && state.selectedResource.id === bus.bus_id; const flagged = binding.has(normalizeBindingId(bus.bus_id)); const evaluationClass = state.result ? (flagged ? " is-binding" : " is-clear") : ` ${headroomClass(bus)}`; const node = makeSvgElement("g", { class: `map-bus${evaluationClass}${selected ? " is-selected" : ""}`, transform: `translate(${x.toFixed(1)} ${y.toFixed(1)})`, role: "button", tabindex: "0", "aria-label": `Select ${bus.bus_id}${presentation.zone ? `, ${presentation.zone} zone` : ""}`, "aria-pressed": selected ? "true" : "false", "data-resource-type": "bus", "data-resource-id": bus.bus_id }); node.append(makeSvgElement("rect", { class: "bus-hit", x: -24, y: -24, width: 48, height: 48 }), ...(selected ? [makeSvgElement("rect", { class: "bus-selection-frame", x: -22, y: -22, width: 44, height: 44 })] : []), makeSvgElement("rect", { class: "bus-ring", x: -17, y: -17, width: 34, height: 34 }), makeSvgElement("rect", { class: "bus-core", x: -9, y: -9, width: 18, height: 18 })); const label = makeSvgElement("text", { class: "bus-label", x: 23, y: 5 }); label.textContent = presentation.short_label || presentation.label || bus.bus_id; node.appendChild(label); resourceEventHandlers(node, { type: "bus", id: bus.bus_id, item: bus }); $("map-buses-layer").appendChild(node); registerResourceElement("schematic", "bus", bus.bus_id, node); });
  renderLocator($("map-locator-layer"), locatorForRender);
  renderGeographicMap();
}

function renderGeographicBasemap(layer, project) {
  const context = $("geographic-context-layer");
  context?.appendChild(makeSvgElement("rect", {
    class: "geographic-map-background",
    x: 0,
    y: 0,
    width: GEOGRAPHIC_VIEWPORT.width,
    height: GEOGRAPHIC_VIEWPORT.height,
    "aria-hidden": "true",
  }));
  const boundaryRings = geographicBoundaryRings();
  boundaryRings.forEach((ring) => {
    const d = pathData(ring, project) + " Z";
    context?.appendChild(makeSvgElement("path", { class: "geographic-texas-fill", d, "aria-hidden": "true" }));
    layer.appendChild(makeSvgElement("path", { class: "geographic-texas-outline", d: pathData(ring, project), "aria-hidden": "true" }));
  });

  const cities = [
    { label: "El Paso", point: [-106.49, 31.76] },
    { label: "San Antonio", point: [-98.49, 29.42] },
    { label: "Austin", point: [-97.74, 30.27] },
    { label: "Houston", point: [-95.37, 29.76] },
    { label: "Dallas", point: [-96.80, 32.78] },
  ];
  cities.forEach(({ label, point }) => {
    const [x, y] = project(point);
    layer.appendChild(makeSvgElement("circle", { class: "geographic-city-marker", cx: x, cy: y, r: 3.5, "aria-hidden": "true" }));
    const cityLabel = makeSvgElement("text", { class: "geographic-city-label", x: x + 7, y: y + 4, "aria-hidden": "true" });
    cityLabel.textContent = label;
    layer.appendChild(cityLabel);
  });
}

function renderGeographicMap() {
  const startedAt = performance.now();
  if (!state.scenario) return;
  const viewport = $("geographic-map-viewport");
  if (!viewport) return;
  const mapStatus = $("geographic-map-status");
  const boundaryReady = geographicBoundaryRings().length > 0 && !TEXAS_BOUNDARY.error;
  if (mapStatus) {
    mapStatus.hidden = boundaryReady;
    mapStatus.textContent = boundaryReady ? "" : `Geographic map unavailable: ${TEXAS_BOUNDARY.error || "Texas boundary data is invalid."}`;
  }
  hideGeographicTooltip();
  applyGeographicTransform();
  ensureGeographicTooltip();
  resourceElementMaps.geographic.clear();
  ["geographic-basemap-layer", "geographic-context-layer", "geographic-counties-layer", "geographic-public-transmission-layer", "geographic-public-generation-layer", "geographic-footprint-layer", "geographic-zones-layer", "geographic-corridors-layer", "geographic-buses-layer"].map($).forEach((layer) => layer?.replaceChildren());
  ["geographic-footprint-layer", "geographic-zones-layer", "geographic-corridors-layer", "geographic-buses-layer"].map($).forEach((layer) => { if (layer) layer.style.display = state.publicLayers.teaching ? "" : "none"; });

  const buses = arrayOrEmpty(state.scenario.buses);
  const corridors = arrayOrEmpty(state.scenario.corridors);
  const project = (point) => projectGeographicPoint(point);
  const binding = bindingResourceIds();
  const planningMode = Boolean(state.scenario?.planning_model?.model_id);
  const planningStartedAt = performance.now();

  renderGeographicBasemap($("geographic-basemap-layer"), project);
  renderGeographicCounties($("geographic-counties-layer"), project);
  renderPublicTransmission($("geographic-public-transmission-layer"), project);
  renderPublicGeneration($("geographic-public-generation-layer"), project);

  const zones = arrayOrEmpty(state.scenario.map?.zones || state.scenario.zones);
  const zonePositions = {};
  buses.forEach((bus) => { const zone = busPresentation(bus).zone; if (zone && !zonePositions[zone]) zonePositions[zone] = []; zonePositions[zone]?.push(busPoint(bus)); });
  Object.entries(zonePositions).filter(() => !planningMode).forEach(([zone, points]) => {
    const point = points.reduce((sum, current) => [sum[0] + current[0], sum[1] + current[1]], [0, 0]).map((value) => value / points.length);
    const [x, y] = project(point);
    const label = makeSvgElement("text", { class: "geographic-zone-label", x, y });
    label.textContent = zones.find((item) => item.zone === zone)?.label || `${zone} zone`;
    $("geographic-zones-layer").appendChild(label);
  });

  corridors.forEach((corridor) => {
    const points = corridorPath(corridor);
    if (points.length < 2) return;
    const selected = state.selectedResource?.type === "corridor" && state.selectedResource.id === corridor.corridor_id;
    const flagged = binding.has(normalizeBindingId(corridor.corridor_id));
    const evaluationClass = state.result ? (flagged ? " is-binding" : " is-clear") : "";
    const d = pathData(points, project);
    const group = makeSvgElement("g", { class: "geographic-map-corridor-group" });
    const path = makeSvgElement("path", { class: `geographic-map-corridor map-corridor${evaluationClass}${selected ? " is-selected" : ""}`, d, "aria-hidden": "true", "pointer-events": "none" });
    const hitPath = makeSvgElement("path", { class: "map-corridor-hit", d, role: "button", tabindex: "0", "aria-label": `Select geographic ${state.scenario?.planning_model?.model_id ? "planning interface" : "teaching corridor"} ${corridor.corridor_id}`, "data-resource-type": "corridor", "data-resource-id": corridor.corridor_id });
    resourceEventHandlers(hitPath, { type: "corridor", id: corridor.corridor_id, item: corridor, map: "geographic" });
    group.append(path, hitPath);
    $("geographic-corridors-layer").appendChild(group);
    registerResourceElement("geographic", "corridor", corridor.corridor_id, group);
  });

  buses.forEach((bus) => {
    const [x, y] = project(busPoint(bus));
    const presentation = busPresentation(bus);
    const selected = state.selectedResource?.type === "bus" && state.selectedResource.id === bus.bus_id;
    const flagged = binding.has(normalizeBindingId(bus.bus_id));
    const evaluationClass = state.result ? (flagged ? " is-binding" : " is-clear") : ` ${headroomClass(bus)}`;
    const node = makeSvgElement("g", { class: `geographic-map-bus map-bus${evaluationClass}${selected ? " is-selected" : ""}`, transform: `translate(${x.toFixed(1)} ${y.toFixed(1)})`, role: "button", tabindex: "0", "aria-label": `Select geographic ${state.scenario?.planning_model?.model_id ? "planning region" : "Synthetic teaching bus"} ${bus.bus_id}${presentation.zone ? `, ${presentation.zone} zone` : ""}`, "aria-pressed": selected ? "true" : "false", "data-resource-type": "bus", "data-resource-id": bus.bus_id });
    node.append(makeSvgElement("rect", { class: "bus-hit", x: -20, y: -20, width: 40, height: 40 }), ...(selected ? [makeSvgElement("rect", { class: "bus-selection-frame", x: -19, y: -19, width: 38, height: 38 })] : []), makeSvgElement("rect", { class: "bus-ring", x: -14, y: -14, width: 28, height: 28 }), makeSvgElement("rect", { class: "bus-core", x: -7, y: -7, width: 14, height: 14 }));
    const label = makeSvgElement("text", { class: "bus-label", x: 19, y: 5 });
    label.textContent = planningMode ? humanizePlanningRegionId(presentation.planning_region_id || presentation.zone || bus.bus_id) : (presentation.short_label || presentation.label || bus.bus_id);
    node.appendChild(label);
    resourceEventHandlers(node, { type: "bus", id: bus.bus_id, item: bus, map: "geographic" });
    $("geographic-buses-layer").appendChild(node);
    registerResourceElement("geographic", "bus", bus.bus_id, node);
  });
  state.publicMetrics.planningRenderMs = performance.now() - planningStartedAt;
  state.publicMetrics.geographicRenderMs = performance.now() - startedAt;
}

function renderGeographicCounties(layer, project) {
  if (!layer) return;
  const startedAt = performance.now();
  arrayOrEmpty(TEXAS_COUNTIES.features).forEach((county) => {
    const coordinates = coordinatePairs(county.coordinates);
    if (coordinates.length < 3) return;
    layer.appendChild(makeSvgElement("path", {
      class: "geographic-county-boundary",
      d: `${pathData(coordinates, project)} Z`,
      "aria-hidden": "true",
    }));
  });
  state.publicMetrics.countyRenderMs = performance.now() - startedAt;
  state.publicMetrics.countyRenderCount += 1;
}

function renderPublicTransmission(layer, project) {
  if (!layer || !state.publicLayers.transmission || !state.publicNetwork) { state.publicMetrics.lastTransmissionCount = 0; return; }
  const startedAt = performance.now();
  const candidates = publicLineCandidates();
  state.publicMetrics.lastTransmissionCount = candidates.length;
  candidates.forEach((branch) => {
    const points = coordinatePairs(branch.geometry);
    if (points.length < 2) return;
    const path = makeSvgElement("path", {
      class: `public-transmission-line public-voltage-${publicVoltageClass(branch.nominal_kv)}`,
      d: pathData(points, project),
      "data-layer": "public-transmission",
      "data-public-id": branch.branch_id,
      "aria-hidden": "true",
    });
    path.addEventListener("pointerenter", (event) => showPublicTooltip("transmission", branch, event, path));
    path.addEventListener("pointermove", (event) => positionMapTooltip($("geographic-map-tooltip"), event, path, $("geographic-map-frame")));
    path.addEventListener("pointerleave", hideGeographicTooltip);
    path.addEventListener("click", (event) => showPublicTooltip("transmission", branch, event, path));
    layer.appendChild(path);
  });
  const status = $("public-network-load-status");
  if (status) status.textContent = `${candidates.length.toLocaleString()} public lines visible`;
  state.publicMetrics.publicRenderMs = performance.now() - startedAt;
  state.publicMetrics.publicRenderCount += 1;
}

function renderPublicGeneration(layer, project) {
  if (!layer || !state.publicLayers.generation || !state.publicNetwork) { state.publicMetrics.lastGenerationCount = 0; return; }
  const candidates = publicPlantCandidates();
  state.publicMetrics.lastGenerationCount = candidates.length;
  candidates.forEach(({ plant, aggregate }) => {
    const [x, y] = project([plant.longitude, plant.latitude]);
    const size = aggregate.capacity >= 500 ? 7 : aggregate.capacity >= 100 ? 5 : 3.5;
    const marker = makeSvgElement("rect", { class: "public-generation-marker", x: x - size, y: y - size, width: size * 2, height: size * 2, "data-layer": "public-generation", "aria-hidden": "true" });
    marker.addEventListener("pointerenter", (event) => showPublicTooltip("generation", { plant, aggregate }, event, marker));
    marker.addEventListener("pointermove", (event) => positionMapTooltip($("geographic-map-tooltip"), event, marker, $("geographic-map-frame")));
    marker.addEventListener("pointerleave", hideGeographicTooltip);
    marker.addEventListener("click", (event) => showPublicTooltip("generation", { plant, aggregate }, event, marker));
    layer.appendChild(marker);
  });
}

function geographicPointerPosition(event) {
  const map = $("geographic-map");
  const rect = map.getBoundingClientRect();
  const scale = Math.min(rect.width / GEOGRAPHIC_VIEWPORT.width, rect.height / GEOGRAPHIC_VIEWPORT.height);
  const renderedWidth = GEOGRAPHIC_VIEWPORT.width * scale;
  const renderedHeight = GEOGRAPHIC_VIEWPORT.height * scale;
  const offsetX = (rect.width - renderedWidth) / 2;
  const offsetY = (rect.height - renderedHeight) / 2;
  return { x: (event.clientX - rect.left - offsetX) / scale, y: (event.clientY - rect.top - offsetY) / scale };
}

function applyGeographicTransform() {
  const viewport = $("geographic-map-viewport");
  if (viewport) viewport.setAttribute("transform", geographicTransform());
}

function beginGeographicDrag(event) {
  if (event.target.closest?.('[role="button"]')) return;
  const point = geographicPointerPosition(event);
  state.geographicDrag = { pointerId: event.pointerId, start: point, pan: { ...state.geographicPan } };
  $("geographic-map").setPointerCapture?.(event.pointerId);
  $("geographic-map-frame")?.classList.add("is-dragging");
}

function continueGeographicDrag(event) {
  if (!state.geographicDrag || state.geographicDrag.pointerId !== event.pointerId) return;
  const point = geographicPointerPosition(event);
  state.geographicPan = clampGeographicPan({ x: state.geographicDrag.pan.x + point.x - state.geographicDrag.start.x, y: state.geographicDrag.pan.y + point.y - state.geographicDrag.start.y });
  applyGeographicTransform();
}

function endGeographicDrag(event) {
  if (!state.geographicDrag) return;
  const pointerId = event?.pointerId ?? state.geographicDrag.pointerId;
  if (pointerId !== undefined && state.geographicDrag.pointerId !== pointerId) return;
  const map = $("geographic-map");
  try {
    if (pointerId !== undefined && map?.releasePointerCapture) {
      if (!map.hasPointerCapture || map.hasPointerCapture(pointerId)) map.releasePointerCapture(pointerId);
    }
  } finally {
    $("geographic-map-frame")?.classList.remove("is-dragging");
    state.geographicDrag = null;
  }
}

function cancelGeographicDrag() {
  endGeographicDrag();
}

function handleGeographicKeydown(event) {
  const panStep = 32;
  let handled = true;
  if (event.key === "ArrowLeft") state.geographicPan.x -= panStep;
  else if (event.key === "ArrowRight") state.geographicPan.x += panStep;
  else if (event.key === "ArrowUp") state.geographicPan.y -= panStep;
  else if (event.key === "ArrowDown") state.geographicPan.y += panStep;
  else if (event.key === "+" || event.key === "=") setGeographicZoom(state.geographicZoom * 1.25);
  else if (event.key === "-" || event.key === "_") setGeographicZoom(state.geographicZoom / 1.25);
  else handled = false;
  if (!handled) return;
  event.preventDefault();
  if (event.key.startsWith("Arrow")) {
    state.geographicPan = clampGeographicPan(state.geographicPan);
    applyGeographicTransform();
  }
}

function setupGeographicMapControls() {
  const map = $("geographic-map");
  if (!map) return;
  const zoomIn = $("geographic-zoom-in");
  const zoomOut = $("geographic-zoom-out");
  const reset = $("geographic-reset");
  zoomIn?.setAttribute("title", "Zoom in geographic map");
  zoomOut?.setAttribute("title", "Zoom out geographic map");
  reset?.setAttribute("title", "Reset geographic map view");
  zoomIn?.addEventListener("click", () => setGeographicZoom(state.geographicZoom * 1.25));
  zoomOut?.addEventListener("click", () => setGeographicZoom(state.geographicZoom / 1.25));
  reset?.addEventListener("click", resetGeographicViewport);
  map.addEventListener("wheel", (event) => { event.preventDefault(); setGeographicZoom(state.geographicZoom * (event.deltaY < 0 ? 1.15 : 1 / 1.15), geographicPointerPosition(event)); }, { passive: false });
  map.addEventListener("pointerdown", beginGeographicDrag);
  map.addEventListener("pointermove", continueGeographicDrag);
  map.addEventListener("pointerup", endGeographicDrag);
  map.addEventListener("pointercancel", endGeographicDrag);
  map.addEventListener("lostpointercapture", cancelGeographicDrag);
  window.addEventListener("blur", cancelGeographicDrag);
  document.addEventListener("visibilitychange", () => { if (document.hidden) cancelGeographicDrag(); });
  document.addEventListener("pointerup", endGeographicDrag);
  document.addEventListener("pointercancel", cancelGeographicDrag);
  map.addEventListener("keydown", handleGeographicKeydown);
}

async function loadCountyAsset() {
  try {
    const response = await fetch("/texas-counties.json");
    if (!response.ok) throw new Error(`county asset request failed: ${response.status}`);
    const payload = await response.json();
    if (!payload || !Array.isArray(payload.features)) throw new Error("county asset is malformed");
    TEXAS_COUNTIES = payload;
    renderGeographicMap();
  } catch (error) {
    // The locator remains usable without boundaries if the bundled optional asset cannot be read.
    console.warn(error instanceof Error ? error.message : "county asset unavailable");
  }
}

async function loadTexasBoundaryAsset() {
  try {
    const response = await fetch("/texas-boundary.json");
    if (!response.ok) throw new Error(`Texas boundary asset request failed: ${response.status}`);
    const payload = await response.json();
    if (!payload || !Array.isArray(payload.rings)) throw new Error("Texas boundary asset is malformed");
    const rings = payload.rings.filter((ring) => coordinatePairs(ring).length >= 3 && coordinatePairs(ring).every(([longitude, latitude]) => Number.isFinite(longitude) && Number.isFinite(latitude)));
    if (!rings.length) throw new Error("Texas boundary asset has no valid longitude/latitude rings");
    TEXAS_BOUNDARY = { ...payload, rings, error: "" };
    renderGeographicMap();
  } catch (error) {
    TEXAS_BOUNDARY = { ...TEXAS_BOUNDARY, error: error instanceof Error ? error.message : "Texas boundary asset unavailable." };
    renderGeographicMap();
    console.warn(error instanceof Error ? error.message : "Texas boundary asset unavailable");
  }
}

async function loadPublicNetwork() {
  const status = $("public-network-load-status");
  if (status) status.textContent = "Loading public context…";
  const startedAt = performance.now();
  try {
    const response = await fetch("/data/ercot-public-network.json");
    if (!response.ok) throw new Error(`public network request failed: ${response.status}`);
    state.publicMetrics.fetchMs = performance.now() - startedAt;
    const parseStartedAt = performance.now();
    const payload = JSON.parse(await response.text());
    state.publicMetrics.parseMs = performance.now() - parseStartedAt;
    if (!payload || !Array.isArray(payload.branches) || !Array.isArray(payload.plants) || !Array.isArray(payload.generators)) throw new Error("public network artifact is malformed");
    state.publicNetwork = payload;
    state.publicNetworkError = "";
    if (status) status.textContent = `${payload.branches.length.toLocaleString()} public lines ready`;
    renderLegend();
    const renderStartedAt = performance.now();
    renderGeographicMap();
    state.publicMetrics.renderMs = performance.now() - renderStartedAt;
    state.publicMetrics.lastRenderZoom = state.geographicZoom;
  } catch (error) {
    state.publicNetwork = null;
    state.publicNetworkError = error instanceof Error ? error.message : "public network context unavailable";
    if (status) status.textContent = "Public context unavailable";
    status?.classList.add("is-warning");
    renderLegend();
    renderGeographicMap();
    console.warn(state.publicNetworkError);
  }
}

function clearStaleResult() {
  const hadResult = Boolean(state.result) || !$('results-content').hidden || !$('results-error').hidden; state.result = null; $("results-empty").hidden = false; $("results-content").hidden = true; $("results-error").hidden = true; $("result-status").textContent = "Not evaluated"; $("result-status").className = "pill pill-muted"; renderLegend(); renderMap(); if (hadResult) setStatus("Plan changed. Run the practice evaluator again to refresh the result.");
}

function invalidateEvaluation() { state.planRevision += 1; state.evaluationRequestToken += 1; state.submitting = false; state.evaluationRequestController?.abort(); $("evaluate-button").disabled = !state.scenario; $("evaluate-button").textContent = "Run practice evaluation"; $("results-panel").setAttribute("aria-busy", "false"); clearStaleResult(); }
function handlePlanInputChange(event) { updateConnectionCardSummaries(); updatePlanSummary(); invalidateEvaluation(); markClassroomDirty(); }

function selectBus(busId) { openResourceDrawer("bus", busId); }

function makeField(labelText, input, errorId, helpText = "") {
  const label = document.createElement("label"); label.htmlFor = input.id; const span = document.createElement("span"); span.textContent = labelText; label.appendChild(span); label.appendChild(input); const error = document.createElement("small"); error.id = errorId; error.className = "field-error"; label.appendChild(error); if (helpText) { const help = document.createElement("small"); help.className = "range-help"; help.textContent = helpText; label.appendChild(help); } input.setAttribute("aria-describedby", errorId); input.setAttribute("aria-errormessage", errorId); return label;
}

function nextConnectionId() { let id; do { state.connectionSerial += 1; id = `site-${state.connectionSerial}`; } while ([...document.querySelectorAll(".connection-id")].some((field) => field.value.trim() === id)); return id; }
function nextGeneratorId() { let id; do { state.generatorSerial += 1; id = `generator-${state.generatorSerial}`; } while ([...document.querySelectorAll(".generator-id")].some((field) => field.value.trim() === id)); return id; }
function connectionDrafts() { return [...document.querySelectorAll(".connection-card")].map((card) => ({ connection_id: card.querySelector(".connection-id")?.value || "", bus_id: card.querySelector(".connection-bus")?.value || "", capacity_mw: card.querySelector(".connection-capacity")?.value || "", profile: [...card.querySelectorAll(".connection-profile")].map((field) => field.value), path_corridors: [...card.querySelectorAll(".connection-corridor:checked")].map((field) => field.value) })); }
function generatorDrafts() { return [...document.querySelectorAll(".generator-card")].map((card) => ({ generator_id: card.querySelector(".generator-id")?.value || "", connection_id: card.querySelector(".generator-connection")?.value || "", capacity_mw: card.querySelector(".generator-capacity")?.value || "", marginal_cost_per_mwh: card.querySelector(".generator-cost")?.value || "" })); }

function updateConnectionCardSummaries() {
  document.querySelectorAll(".connection-card").forEach((card) => {
    const title = card.querySelector(".connection-card-summary");
    if (!title) return;
    const draft = connectionDrafts()[[...document.querySelectorAll(".connection-card")].indexOf(card)];
    const capacity = Number(draft?.capacity_mw);
    const corridors = arrayOrEmpty(draft?.path_corridors);
    title.textContent = `${draft?.connection_id || "Unnamed"} · ${draft?.bus_id || "Bus not selected"} · ${Number.isFinite(capacity) ? displayNumber(capacity, " MW") : "—"} · ${corridors.length} corridor${corridors.length === 1 ? "" : "s"}`;
  });
}

function updatePlanSummary() {
  const connections = connectionDrafts(); const generators = generatorDrafts();
  const capacity = connections.reduce((sum, draft) => { const value = Number(draft.capacity_mw); return Number.isFinite(value) ? sum + value : sum; }, 0);
  const budget = $("intervention-budget")?.value || "0"; const mu = $("curtailment-depth")?.value || "0";
  if ($("plan-summary-sites")) $("plan-summary-sites").textContent = `${connections.length} site${connections.length === 1 ? "" : "s"}`;
  if ($("plan-summary-capacity")) $("plan-summary-capacity").textContent = `${displayNumber(capacity, " MW")} total`;
  if ($("plan-summary-generators")) $("plan-summary-generators").textContent = `${generators.length} generator${generators.length === 1 ? "" : "s"}`;
  if ($("plan-summary-budget")) $("plan-summary-budget").textContent = `K = ${budget}`;
  if ($("plan-summary-curtailment")) $("plan-summary-curtailment").textContent = `μ = ${mu}`;
}

function busOptions(selected = "") { return arrayOrEmpty(state.scenario?.buses).map((bus) => { const option = document.createElement("option"); option.value = bus.bus_id; const presentation = busPresentation(bus); option.textContent = presentation.zone ? `${bus.bus_id} · ${presentation.zone}` : bus.bus_id; option.selected = bus.bus_id === selected; return option; }); }
function corridorChoices(selected = [], key) { const wrap = document.createElement("div"); wrap.className = "choice-grid"; arrayOrEmpty(state.scenario?.corridors).forEach((corridor) => { const label = document.createElement("label"); label.className = "choice-card"; const input = document.createElement("input"); input.type = "checkbox"; input.className = "connection-corridor"; input.value = corridor.corridor_id; input.checked = selected.includes(corridor.corridor_id); input.id = `corridor-${key}-${corridor.corridor_id}`; const text = document.createElement("span"); text.textContent = corridor.corridor_id; label.htmlFor = input.id; label.append(input, text); wrap.appendChild(label); }); return wrap; }

function createConnectionCard(draft = {}) {
  const key = `connection-${++state.connectionSerial}`; const card = document.createElement("article"); card.className = "repeatable-card connection-card"; card.dataset.cardKey = key;
  const heading = document.createElement("div"); heading.className = "card-heading"; const title = document.createElement("h3"); title.className = "connection-card-summary"; title.textContent = "Connection site"; const actions = document.createElement("div"); actions.className = "card-actions";
  const details = document.createElement("button"); details.type = "button"; details.className = "card-button"; details.dataset.action = "view-site"; details.textContent = "Details";
  const duplicate = document.createElement("button"); duplicate.type = "button"; duplicate.className = "card-button"; duplicate.dataset.action = "duplicate-connection"; duplicate.textContent = "Duplicate";
  const remove = document.createElement("button"); remove.type = "button"; remove.className = "card-button danger"; remove.dataset.action = "remove-connection"; remove.textContent = "Remove"; actions.append(details, duplicate, remove); heading.append(title, actions); card.appendChild(heading);
  const grid = document.createElement("div"); grid.className = "card-grid";
  const id = document.createElement("input"); id.className = "connection-id"; id.id = `${key}-id`; id.type = "text"; id.value = draft.connection_id || nextConnectionId(); id.autocomplete = "off"; grid.appendChild(makeField("Connection ID", id, `${key}-id-error`));
  const planningMode = Boolean(state.scenario?.planning_model?.model_id);
  const bus = document.createElement("select"); bus.className = "connection-bus"; bus.id = `${key}-bus`; bus.setAttribute("aria-label", planningMode ? "Planning region" : "Bus"); bus.append(...busOptions(draft.bus_id || state.scenario?.buses?.[0]?.bus_id || "")); grid.appendChild(makeField(planningMode ? "Planning region" : "Bus", bus, `${key}-bus-error`));
  const capacity = document.createElement("input"); capacity.className = "connection-capacity"; capacity.id = `${key}-capacity`; capacity.type = "number"; capacity.min = "0"; capacity.step = "0.1"; capacity.value = draft.capacity_mw ?? 10; grid.appendChild(makeField("Capacity (MW)", capacity, `${key}-capacity-error`, "Capacity: finite, non-negative MW.")); card.appendChild(grid);
  const corridorLabel = document.createElement("span"); corridorLabel.className = "card-section-label"; corridorLabel.textContent = planningMode ? "Planning interfaces" : "Path corridors"; card.appendChild(corridorLabel); const corridorHelp = document.createElement("p"); corridorHelp.className = "field-help"; corridorHelp.textContent = planningMode ? "Select the planning interfaces used by this connection site." : "Checkboxes are this site's selected transmission path."; card.appendChild(corridorHelp); const corridorError = document.createElement("small"); corridorError.className = "field-error connection-corridor-error"; corridorError.id = `${key}-corridor-error`; card.append(corridorChoices(draft.path_corridors || [], key), corridorError);
  const profileLabel = document.createElement("span"); profileLabel.className = "card-section-label"; profileLabel.textContent = "Profile per period"; card.appendChild(profileLabel); const profileGrid = document.createElement("div"); profileGrid.className = "profile-grid"; const profile = draft.profile || []; for (let index = 0; index < Number(state.scenario?.time_horizon || 0); index += 1) { const value = profile[index] ?? 1; const input = document.createElement("input"); input.className = "connection-profile"; input.id = `${key}-profile-${index}`; input.type = "number"; input.min = "0"; input.max = "1"; input.step = "0.05"; input.value = value; input.dataset.profileIndex = String(index); profileGrid.appendChild(makeField(`Period ${index + 1}`, input, `${key}-profile-${index}-error`)); } card.appendChild(profileGrid); return card;
}

function renderConnectionCards(drafts = connectionDrafts()) { const container = $("connection-cards"); container.replaceChildren(); drafts.forEach((draft) => container.appendChild(createConnectionCard(draft))); refreshGeneratorConnectionOptions(); updateConnectionCardSummaries(); updatePlanSummary(); }
function addConnectionCard(draft = {}, options = {}) { const drafts = connectionDrafts(); drafts.push({ connection_id: draft.connection_id || "", bus_id: draft.bus_id || state.scenario?.buses?.[0]?.bus_id || "", capacity_mw: draft.capacity_mw ?? 10, profile: draft.profile || Array(Number(state.scenario?.time_horizon || 0)).fill(1), path_corridors: draft.path_corridors || [] }); renderConnectionCards(drafts); invalidateEvaluation(); markClassroomDirty(); const card = $("connection-cards .connection-card:last-child"); (card?.querySelector(options.focusSelector || ".connection-id"))?.focus(); return card; }
function addConnectionAtBus(busId) { const card = addConnectionCard({ bus_id: busId }, { focusSelector: ".connection-bus" }); card?.scrollIntoView({ behavior: "smooth", block: "center" }); card?.classList.add("is-new"); window.setTimeout(() => card?.classList.remove("is-new"), 900); setStatus(`Added a connection site at ${busId}.`, "success"); }
function duplicateConnectionCard(card) { const draft = connectionDrafts().find((item, index) => document.querySelectorAll(".connection-card")[index] === card); if (draft) { draft.connection_id = ""; addConnectionCard(draft); } }
function repairGeneratorReferences(removedConnectionId, generators) {
  const fallbackConnectionId = connectionDrafts().filter((connection) => connection.connection_id.trim() !== removedConnectionId).map((connection) => connection.connection_id.trim()).find(Boolean) || "";
  const repairedGenerators = [];
  const reassigned = [];
  let removedGeneratorCount = 0;
  generators.forEach((generator) => {
    if (generator.connection_id !== removedConnectionId) {
      repairedGenerators.push(generator);
      return;
    }
    if (fallbackConnectionId) {
      generator.connection_id = fallbackConnectionId;
      repairedGenerators.push(generator);
      reassigned.push(`${generator.generator_id || "Unnamed generator"} reassigned from removed connection ${removedConnectionId} to the first remaining connection ${fallbackConnectionId}.`);
    } else {
      removedGeneratorCount += 1;
    }
  });
  const notice = reassigned.join(" ") || (removedGeneratorCount ? `${removedGeneratorCount} generator${removedGeneratorCount === 1 ? " was" : "s were"} removed because no connection site remains. Add a connection site before adding generators.` : "");
  return { generators: repairedGenerators, notice };
}
function removeConnectionCard(card) { const cards = [...document.querySelectorAll(".connection-card")]; const index = cards.indexOf(card); const removedDraft = connectionDrafts()[index]; const drafts = connectionDrafts().filter((_, draftIndex) => draftIndex !== index); const repaired = repairGeneratorReferences(removedDraft?.connection_id || "", generatorDrafts()); renderConnectionCards(drafts); renderGeneratorCards(repaired.generators); invalidateEvaluation(); markClassroomDirty(); if (repaired.notice) setEditorNotice(repaired.notice); }

function connectionOptions(selected = "") { return connectionDrafts().map((connection) => { const option = document.createElement("option"); option.value = connection.connection_id.trim(); option.textContent = connection.connection_id.trim() || "Unnamed connection"; option.selected = option.value === selected; return option; }); }
function createGeneratorCard(draft = {}) { const key = `generator-${++state.generatorSerial}`; const card = document.createElement("article"); card.className = "repeatable-card generator-card"; card.dataset.cardKey = key; const heading = document.createElement("div"); heading.className = "card-heading"; heading.appendChild(createSemanticIcon("icon-generator")); const title = document.createElement("h3"); title.textContent = "Generator"; const remove = document.createElement("button"); remove.type = "button"; remove.className = "card-button danger"; remove.dataset.action = "remove-generator"; remove.textContent = "Remove"; heading.append(title, remove); card.appendChild(heading); const grid = document.createElement("div"); grid.className = "card-grid";
  const id = document.createElement("input"); id.className = "generator-id"; id.id = `${key}-id`; id.type = "text"; id.value = draft.generator_id || nextGeneratorId(); grid.appendChild(makeField("Generator ID", id, `${key}-id-error`)); const connection = document.createElement("select"); connection.className = "generator-connection"; connection.id = `${key}-connection`; connection.append(...connectionOptions(draft.connection_id || connectionDrafts()[0]?.connection_id || "")); grid.appendChild(makeField("Connection site", connection, `${key}-connection-error`)); const capacity = document.createElement("input"); capacity.className = "generator-capacity"; capacity.id = `${key}-capacity`; capacity.type = "number"; capacity.min = "0"; capacity.step = "0.1"; capacity.value = draft.capacity_mw ?? 5; grid.appendChild(makeField("Capacity (MW)", capacity, `${key}-capacity-error`, "Capacity: finite, non-negative MW.")); const cost = document.createElement("input"); cost.className = "generator-cost"; cost.id = `${key}-cost`; cost.type = "number"; cost.min = "0"; cost.step = "0.1"; cost.value = draft.marginal_cost_per_mwh ?? 80; grid.appendChild(makeField("Marginal cost ($/MWh)", cost, `${key}-cost-error`, "Generator cost: finite, non-negative $/MWh.")); card.appendChild(grid); return card; }
function renderGeneratorCards(drafts = generatorDrafts()) { const container = $("generator-cards"); container.replaceChildren(); drafts.forEach((draft) => container.appendChild(createGeneratorCard(draft))); refreshGeneratorConnectionOptions(); updatePlanSummary(); }
function addGeneratorCard() { const connections = connectionDrafts(); if (!connections.length) { setEditorNotice("Add a connection site before adding a generator."); $("add-connection")?.focus(); return; } const drafts = generatorDrafts(); drafts.push({ generator_id: "", connection_id: connections[0]?.connection_id || "", capacity_mw: 5, marginal_cost_per_mwh: 80 }); renderGeneratorCards(drafts); invalidateEvaluation(); markClassroomDirty(); $("generator-cards .generator-card:last-child .generator-id")?.focus(); }
function removeGeneratorCard(card) { const drafts = generatorDrafts().filter((_, index) => document.querySelectorAll(".generator-card")[index] !== card); renderGeneratorCards(drafts); invalidateEvaluation(); markClassroomDirty(); }
function refreshGeneratorConnectionOptions() { document.querySelectorAll(".generator-card").forEach((card) => { const select = card.querySelector(".generator-connection"); const current = select.value; select.replaceChildren(...connectionOptions(current)); }); }
function setEditorNotice(message) { const notice = $("generators-error"); notice.textContent = message; notice.setAttribute("role", "status"); notice.setAttribute("aria-live", "polite"); }

function clearFormErrors() { document.querySelectorAll("[aria-invalid=true]").forEach((field) => field.removeAttribute("aria-invalid")); document.querySelectorAll(".field-error").forEach((field) => { field.textContent = ""; }); $("form-message").textContent = ""; $("validation-summary").hidden = true; $("validation-summary").replaceChildren(); document.querySelectorAll(".repeatable-card.is-invalid").forEach((card) => card.classList.remove("is-invalid")); }
function setFieldError(field, message) { if (field) { const card = field.closest(".connection-card,.generator-card"); if (card) { const cards = [...document.querySelectorAll(field.closest(".connection-card") ? ".connection-card" : ".generator-card")]; const index = cards.indexOf(card) + 1; const kind = field.closest(".connection-card") ? "Connection site" : "Generator"; message = `${kind} ${index}: ${message}`; } field.setAttribute("aria-invalid", "true"); const errorId = field.getAttribute("aria-errormessage") || field.getAttribute("aria-describedby")?.split(" ")[0]; if (errorId && $(errorId)) $(errorId).textContent = message; field.closest(".repeatable-card")?.classList.add("is-invalid"); } }
function renderValidationSummary() { const summary = $("validation-summary"); if (!summary) return; const errors = [...document.querySelectorAll("[aria-invalid=true]")].map((field) => { const errorId = field.getAttribute("aria-errormessage") || field.getAttribute("aria-describedby")?.split(" ")[0]; return errorId && $(errorId)?.textContent.trim(); }).filter(Boolean); ["connections-error", "generators-error"].forEach((id) => { const message = $(id)?.textContent.trim(); if (message && !errors.includes(message)) errors.push(message); }); if (!errors.length) return; summary.replaceChildren(); const title = document.createElement("strong"); title.append(createSemanticIcon("icon-error"), document.createTextNode("Plan needs attention")); summary.appendChild(title); const count = document.createElement("p"); count.textContent = `${errors.length} field${errors.length === 1 ? "" : "s"} must be fixed before evaluation can run.`; summary.appendChild(count); const list = document.createElement("ul"); errors.forEach((message) => { const item = document.createElement("li"); item.textContent = message; list.appendChild(item); }); summary.appendChild(list); summary.hidden = false; const firstInvalid = document.querySelector("[aria-invalid=true]") || $("add-connection"); if (firstInvalid) { const reduced = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)").matches : false; firstInvalid.scrollIntoView?.({ behavior: reduced ? "auto" : "smooth", block: "center" }); firstInvalid.focus?.({ preventScroll: true }); } }
function readNumericField(field, label, { integer = false, min = null, max = null } = {}) { const rawValue = field.value; if (rawValue.trim() === "") { setFieldError(field, `${label} is required.`); return null; } const value = Number(rawValue); if (!Number.isFinite(value) || (min !== null && value < min) || (max !== null && value > max) || (integer && !Number.isInteger(value))) { const message = max !== null && min !== null ? `${label} must be within [${min}, ${max}].` : integer ? `${label} must be a non-negative whole number.` : min !== null ? `${label} must be finite and non-negative.` : `${label} must be finite.`; setFieldError(field, message); return null; } return value; }

function buildCanonicalPlan() { clearFormErrors(); let valid = true; const teamId = $("team-id").value.trim(); if (!teamId) { setFieldError($("team-id"), "Team ID is required."); valid = false; } const budget = readNumericField($("intervention-budget"), "Intervention budget K", { integer: true, min: 0, max: state.scenario.time_horizon }); if (budget === null) valid = false; const mu = readNumericField($("curtailment-depth"), "Curtailment depth μ", { min: 0, max: 1 }); if (mu === null) valid = false; const fee = readNumericField($("flexibility-fee"), "Flexibility fee", { min: 0 }); if (fee === null) valid = false;
  const connections = []; const seenConnections = new Set(); document.querySelectorAll(".connection-card").forEach((card) => { const idField = card.querySelector(".connection-id"); const busField = card.querySelector(".connection-bus"); const capacityField = card.querySelector(".connection-capacity"); const connectionId = idField.value.trim(); if (!connectionId) { setFieldError(idField, "Connection ID is required."); valid = false; } else if (seenConnections.has(connectionId)) { setFieldError(idField, "Duplicate connection IDs are not allowed."); $("connections-error").textContent = "Duplicate connection IDs must be unique."; valid = false; } else { seenConnections.add(connectionId); } const capacity = readNumericField(capacityField, "Connection capacity", { min: 0 }); if (capacity === null) valid = false; if (!busField.value) { setFieldError(busField, "Choose a bus."); valid = false; } const profile = []; card.querySelectorAll(".connection-profile").forEach((field, index) => { const value = readNumericField(field, `Profile period ${index + 1}`, { min: 0, max: 1 }); if (value === null) valid = false; else profile.push(value); }); connections.push({ connection_id: connectionId, bus_id: busField.value, path_corridors: [...card.querySelectorAll(".connection-corridor:checked")].map((field) => field.value), capacity_mw: capacity, profile }); }); if (!connections.length) { $("connections-error").textContent = "Add at least one connection site; the evaluator requires a non-empty connections array."; valid = false; }
  const generators = []; const seenGenerators = new Set(); document.querySelectorAll(".generator-card").forEach((card) => { const idField = card.querySelector(".generator-id"); const connectionField = card.querySelector(".generator-connection"); const capacityField = card.querySelector(".generator-capacity"); const costField = card.querySelector(".generator-cost"); const generatorId = idField.value.trim(); if (!generatorId) { setFieldError(idField, "Generator ID is required."); valid = false; } else if (seenGenerators.has(generatorId)) { setFieldError(idField, "Duplicate generator IDs are not allowed."); $("generators-error").textContent = "Duplicate generator IDs must be unique."; valid = false; } else seenGenerators.add(generatorId); if (!connectionField.value || !seenConnections.has(connectionField.value)) { setFieldError(connectionField, "Generator connection must reference an existing connection."); valid = false; } const capacity = readNumericField(capacityField, "Generator capacity", { min: 0 }); const cost = readNumericField(costField, "Generator marginal cost", { min: 0 }); if (capacity === null || cost === null) valid = false; generators.push({ generator_id: generatorId, connection_id: connectionField.value, capacity_mw: capacity, marginal_cost_per_mwh: cost }); });
  if (!valid) { $("form-message").textContent = "Fix the highlighted fields before evaluating."; setStatus("Plan needs attention. Fix the highlighted fields before evaluating.", "error"); renderValidationSummary(); return null; }
  return { team_id: teamId, connections, generators, intervention_budget_k: budget, curtailment_depth_mu: mu, flexibility_fee_per_mwh: fee };
}

function validateScenarioPayload(payload) { if (!payload || typeof payload !== "object" || Array.isArray(payload)) return "response must be an object"; if (typeof payload.scenario_id !== "string" || typeof payload.evaluator_version !== "string") return "scenario identity fields are malformed"; if (!Number.isInteger(payload.time_horizon) || payload.time_horizon < 1 || payload.time_horizon > MAX_TIME_HORIZON) return `time_horizon must be an integer within [1, ${MAX_TIME_HORIZON}]`; if (!Array.isArray(payload.buses) || payload.buses.length === 0 || payload.buses.some((bus) => !bus || typeof bus.bus_id !== "string" || !isNonNegativeNumberArray(bus.headroom_mw_by_time) || bus.headroom_mw_by_time.length !== payload.time_horizon)) return "scenario buses are malformed"; if (!Array.isArray(payload.corridors) || payload.corridors.some((corridor) => !corridor || typeof corridor.corridor_id !== "string" || !isNonNegativeNumberArray(corridor.capacity_mw_by_time) || corridor.capacity_mw_by_time.length !== payload.time_horizon)) return "scenario corridors are malformed"; const prices = objectOrEmpty(payload.prices); if (!isNonNegativeNumberArray(prices.energy_price_per_mwh) || prices.energy_price_per_mwh.length !== payload.time_horizon || !isNonNegativeNumberArray(prices.it_value_per_mwh) || prices.it_value_per_mwh.length !== payload.time_horizon) return "scenario prices are malformed"; if (!payload.rules || typeof payload.rules !== "object" || Array.isArray(payload.rules)) return "scenario rules are malformed"; if (payload.rules.base_load_mw_by_time !== undefined && (!isNonNegativeNumberArray(payload.rules.base_load_mw_by_time) || payload.rules.base_load_mw_by_time.length !== payload.time_horizon)) return "scenario base load is malformed"; return null; }

function isPlainRecord(value) { return value && typeof value === "object" && !Array.isArray(value); }
function isNonEmptyString(value) { return typeof value === "string" && value.trim().length > 0; }
function isStringArray(value) { return Array.isArray(value) && value.every(isNonEmptyString); }
function validateDiagnosticItems(items, label, { ids = [], arrays = [], objects = [], numbers = [], booleans = [] } = {}) {
  if (!Array.isArray(items)) return `${label} must be an array`;
  const malformed = items.some((item) => !isPlainRecord(item)
    || ids.some((field) => !isNonEmptyString(item[field]))
    || arrays.some((field) => !isFiniteNumberArray(item[field]))
    || objects.some((field) => !isPlainRecord(item[field]))
    || numbers.some((field) => !isFiniteNumber(item[field]))
    || booleans.some((field) => typeof item[field] !== "boolean"));
  return malformed ? `${label} items are malformed` : null;
}

function validateEvaluationPayload(payload) {
  if (!isPlainRecord(payload)) return "response must be an object";
  if (!isNonEmptyString(payload.evaluator_version) || !isNonEmptyString(payload.scenario_id) || !isNonEmptyString(payload.input_hash)) return "response identity fields are malformed";
  if (!Array.isArray(payload.team_results) || payload.team_results.length === 0) return "canonical team results are malformed";
  const topLevelChecks = [
    [payload.connection_results, "connection results", { ids: ["team_id", "connection_id", "bus_id"], arrays: ["path_corridors"], objects: ["allocation", "recourse", "score_breakdown", "diagnostics"] }],
    [payload.generator_dispatch, "generator dispatch", { ids: ["team_id", "generator_id", "connection_id"], arrays: ["dispatch_mw"], numbers: ["total_mwh"] }],
    [payload.site_diagnostics, "site diagnostics", { ids: ["team_id", "connection_id", "bus_id"], objects: ["diagnostics"] }],
    [payload.team_totals, "team totals", { ids: ["team_id"], numbers: ["total"], booleans: ["feasible"] }],
  ];
  for (const [items, label, options] of topLevelChecks) {
    const error = validateDiagnosticItems(items, label, options);
    if (error) return error;
  }
  if (!isPlainRecord(payload.aggregate_diagnostics)) return "aggregate diagnostics are malformed";
  const team = payload.team_results[0];
  if (!isPlainRecord(team) || !isNonEmptyString(team.team_id)) return "team result is malformed";
  const teamConnectionError = validateDiagnosticItems(team.connection_results, "team connection results", { ids: ["connection_id", "bus_id"], arrays: ["path_corridors"], objects: ["allocation", "recourse", "score_breakdown", "diagnostics"] });
  if (teamConnectionError) return teamConnectionError;
  const teamGeneratorError = validateDiagnosticItems(team.generator_dispatch_results, "team generator dispatch", { ids: ["generator_id", "connection_id"], arrays: ["dispatch_mw"], numbers: ["total_mwh"] });
  if (teamGeneratorError) return teamGeneratorError;
  const teamSiteError = validateDiagnosticItems(team.site_diagnostics, "team site diagnostics", { ids: ["connection_id", "bus_id"], objects: ["diagnostics"] });
  if (teamSiteError) return teamSiteError;
  const allocation = team.allocation;
  if (!isPlainRecord(allocation) || !isFiniteNumber(allocation.allocated_capacity_mw) || !isStringArray(allocation.binding_resources)) return "allocation diagnostics are malformed";
  const recourse = team.recourse;
  const horizon = state.scenario?.time_horizon;
  if (!isPlainRecord(recourse) || typeof recourse.feasible !== "boolean" || !isFiniteNumberArrayOfLength(recourse.served_mw, horizon) || !isFiniteNumberArrayOfLength(recourse.curtailed_mw, horizon) || !isFiniteNumberArrayOfLength(recourse.residual_unserved_mw, horizon) || !isFiniteNumber(recourse.total_curtailed_mwh) || !isFiniteNumber(recourse.total_unserved_mwh)) return "recourse diagnostics are malformed";
  const score = team.score_breakdown;
  if (!isPlainRecord(score)) return "score breakdown is malformed";
  const missingScoreField = requiredScoreFields.find((field) => !isFiniteNumber(score[field]));
  if (missingScoreField) return `score breakdown is missing numeric field: ${missingScoreField}`;
  const diagnostics = team.diagnostics;
  if (!isPlainRecord(diagnostics) || typeof diagnostics.feasible !== "boolean" || !isStringArray(diagnostics.binding_site_ids) || !isStringArray(diagnostics.curtailed_site_ids) || !isFiniteNumberArrayOfLength(diagnostics.requested_load_mw, horizon) || !isFiniteNumberArrayOfLength(diagnostics.network_available_capacity_mw, horizon) || !isFiniteNumberArrayOfLength(diagnostics.effective_available_capacity_mw, horizon) || !isFiniteNumberArrayOfLength(diagnostics.grid_supply_mw, horizon) || !isFiniteNumberArrayOfLength(diagnostics.balance_error_mw, horizon)) return "team diagnostics are malformed";
  return null;
}

function renderEvaluationSummary(team, allocation, recourse, diagnostics, feasible) {
  const summary = $("evaluation-summary"); if (!summary) return;
  const resources = arrayOrEmpty(allocation.binding_resources); const flagged = [...arrayOrEmpty(diagnostics.binding_site_ids), ...arrayOrEmpty(diagnostics.curtailed_site_ids)];
  const resourceText = resources.length ? `${resources.length} binding resource${resources.length === 1 ? "" : "s"}` : (flagged.length ? `${new Set(flagged).size} flagged site${new Set(flagged).size === 1 ? "" : "s"}` : "No flagged resources");
  const curtailed = Number(recourse.total_curtailed_mwh);
  summary.className = `evaluation-summary ${feasible ? "is-success" : "is-warning"}`;
  summary.replaceChildren(...(feasible ? [createSemanticIcon("icon-success")] : []), document.createTextNode(`${feasible ? "Feasible" : "Infeasible"} · ${resourceText}${Number.isFinite(curtailed) ? ` · ${displayNumber(curtailed, " MWh")} curtailed` : ""}`));
}

function renderDiagnostics(result) { const team = result.team_results?.[0] || {}; const allocation = objectOrEmpty(team.allocation); const recourse = objectOrEmpty(team.recourse); const score = objectOrEmpty(team.score_breakdown); const diagnostics = objectOrEmpty(team.diagnostics); const feasible = diagnostics.feasible === true; $("result-total").textContent = displayMoney(score.total); $("result-accepted").textContent = displayNumber(allocation.allocated_capacity_mw, " MW"); $("result-curtailed").textContent = displayNumber(recourse.total_curtailed_mwh, " MWh"); $("result-revenue").textContent = displayMoney(score.it_value); $("result-feasibility").textContent = feasible ? "Feasible" : "Infeasible"; renderEvaluationSummary(team, allocation, recourse, diagnostics, feasible);
  const scoreList = $("score-components"); scoreList.replaceChildren(); [["IT value", score.it_value], ["Energy cost", -score.energy_cost], ["Generator cost", -score.generator_cost], ["Flexibility fee", -score.flexibility_fee], ["Curtailment cost", -score.curtailment_cost], ["Unserved penalty", -score.unserved_penalty]].forEach(([label, value]) => appendMetric(scoreList, label, displayMoney(value)));
  const gridList = $("grid-diagnostics"); gridList.replaceChildren(); appendResourceMetric(gridList, "Binding resources", allocation.binding_resources); appendMetric(gridList, "Residual unserved", displayNumber(recourse.total_unserved_mwh, " MWh")); appendMetric(gridList, "Intervention periods", arrayOrEmpty(recourse.intervention_times).join(", ") || "None"); appendMetric(gridList, "Balance error", displaySeries(diagnostics.balance_error_mw, " MW"));
  const sites = $("site-diagnostics"); sites.replaceChildren(); const site_diagnostics = arrayOrEmpty(result.site_diagnostics); const siteResults = arrayOrEmpty(team.connection_results || team.site_results || site_diagnostics || result.connection_results); siteResults.forEach((site) => { const card = document.createElement("article"); card.className = "diagnostic-card"; const siteScore = objectOrEmpty(site.score_breakdown); appendTextElement(card, "strong", "", site.connection_id); appendTextElement(card, "p", "", `${site.bus_id} · accepted ${displayNumber(site.allocation?.allocated_capacity_mw, " MW")} · score ${displayMoney(siteScore.total)}`); sites.appendChild(card); }); if (!siteResults.length) sites.textContent = "No site diagnostics returned.";
  const generators = arrayOrEmpty(team.generator_dispatch_results || result.generator_dispatch); const generatorList = $("generator-diagnostics"); generatorList.replaceChildren(); generators.forEach((generator) => { const card = document.createElement("article"); card.className = "diagnostic-card"; appendTextElement(card, "strong", "", generator.generator_id); appendTextElement(card, "p", "", `${generator.connection_id} · dispatched ${displayNumber(generator.total_mwh, " MWh")}`); generatorList.appendChild(card); }); if (!generators.length) generatorList.textContent = "No generators submitted.";
  const binding = $("binding-diagnostics"); binding.replaceChildren(); appendResourceMetric(binding, "Binding site IDs", diagnostics.binding_site_ids); appendResourceMetric(binding, "Curtailed site IDs", diagnostics.curtailed_site_ids); appendResourceMetric(binding, "Binding resources", allocation.binding_resources);
  const identity = $("evaluation-identity"); identity.replaceChildren(); const team_totals = arrayOrEmpty(result.team_totals); appendMetric(identity, "Evaluator", result.evaluator_version || "—"); appendMetric(identity, "Scenario", result.scenario_id || "—"); appendMetric(identity, "Input hash", result.input_hash || "—"); appendMetric(identity, "Team total", team_totals[0]?.total !== undefined ? displayMoney(team_totals[0].total) : displayMoney(score.total));
}

function renderResult(result) { state.result = result; const team = result.team_results?.[0] || {}; const diagnostics = objectOrEmpty(team.diagnostics); const feasible = diagnostics.feasible === true; $("results-empty").hidden = true; $("results-error").hidden = true; $("results-content").hidden = false; $("result-status").textContent = feasible ? "Feasible" : "Needs attention"; $("result-status").className = `pill ${feasible ? "pill-success" : "pill-danger"}`; renderDiagnostics(result); $("result-notes").textContent = feasible ? "Server evaluation complete. Use the site and generator cards above to compare the returned diagnostics." : "Review the returned diagnostics and adjust the plan; the server evaluator is the source of truth."; $("raw-results").textContent = JSON.stringify(result, null, 2); renderMap(); }
function renderEvaluationError(message) { state.result = null; renderLegend(); renderMap(); $("results-empty").hidden = true; $("results-content").hidden = true; $("results-error").hidden = false; $("results-error").replaceChildren(createSemanticIcon("icon-error"), document.createTextNode(`Evaluation could not be completed: ${message}`)); $("result-status").textContent = "Request error"; $("result-status").className = "pill pill-danger"; }

async function evaluatePlan(event) {
  event.preventDefault();
  if (state.submitting) return;
  const plan = buildCanonicalPlan();
  if (!plan) return;
  const requestToken = ++state.evaluationRequestToken;
  const planRevision = state.planRevision;
  const scenarioRevision = state.scenarioRevision;
  const controller = new AbortController();
  state.evaluationRequestController = controller;
  state.submitting = true;
  const button = $("evaluate-button");
  button.disabled = true;
  button.textContent = "Evaluating…";
  $("results-panel").setAttribute("aria-busy", "true");
  setStatus("Submitting the canonical multi-site plan to the server evaluator…");
  try {
    const response = await fetch("/api/evaluate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ plan }), signal: controller.signal });
    const payload = await response.json();
    if (requestToken !== state.evaluationRequestToken || planRevision !== state.planRevision || scenarioRevision !== state.scenarioRevision) return;
    if (!response.ok) throw new Error(payload.error?.message || "The server rejected the plan.");
    const schemaError = validateEvaluationPayload(payload);
    if (schemaError) throw new Error(`server returned an invalid evaluation response: ${schemaError}`);
    renderResult(payload);
    setStatus("Practice evaluation complete. Results below are server-generated.", "success");
  } catch (error) {
    if (requestToken !== state.evaluationRequestToken || planRevision !== state.planRevision || scenarioRevision !== state.scenarioRevision || error?.name === "AbortError") return;
    renderEvaluationError(error instanceof Error ? error.message : "Unexpected request error.");
    setStatus("The practice request returned an error. Your form values were preserved.", "error");
  } finally {
    if (requestToken !== state.evaluationRequestToken) return;
    state.submitting = false;
    state.evaluationRequestController = null;
    button.disabled = !state.scenario;
    button.textContent = "Run practice evaluation";
    $("results-panel").setAttribute("aria-busy", "false");
  }
}

function classroomSession() {
  const embedded = window.ERCOT_CLASSROOM_SESSION;
  if (embedded && typeof embedded === "object") return embedded;
  try {
    const stored = window.sessionStorage.getItem("ercot-classroom-session");
    return stored ? JSON.parse(stored) : null;
  } catch (error) {
    return null;
  }
}

function classroomHeaders(options = {}) {
  const headers = new Headers(options.headers || {});
  if (state.classroom.token) headers.set("Authorization", `Bearer ${state.classroom.token}`);
  if (options.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  return headers;
}

async function classroomFetch(path, options = {}) {
  const method = String(options.method || "GET").toUpperCase();
  const retryableMethods = new Set(["GET", "HEAD", "OPTIONS", "PUT"]);
  const retryable = retryableMethods.has(method);
  const maxAttempts = retryable ? 1 : 0;
  const request = { ...options, headers: classroomHeaders(options) };
  for (let attempt = 0; attempt <= maxAttempts; attempt += 1) {
    try {
      const response = await fetch(path, request);
      let payload = null;
      try { payload = await response.json(); } catch (error) { payload = null; }
      if (!response.ok) {
        const detail = payload?.error || {};
        const failure = new Error(detail.message || `Request failed (${response.status})`);
        failure.code = detail.code || "request_failed";
        failure.requestId = detail.request_id || "";
        failure.status = response.status;
        if (failure.status === 401 || failure.status === 403) {
          invalidateClassroomSession();
          announceClassroomAuthFailure(failure);
        }
        throw failure;
      }
      return payload || {};
    } catch (error) {
      if (attempt === maxAttempts || error?.name === "AbortError" || error?.code) throw error;
    }
  }
  throw new Error("request failed after bounded retry attempts");
}

function beginClassroomAction(action) {
  state.classroom.activeAction = action;
  state.classroom.retryAction = null;
  state.classroom.retry = null;
  clearStructuredError();
}

function setClassroomRetry(action, callback) {
  if (state.classroom.activeAction !== action) return;
  state.classroom.retryAction = { action, callback };
  state.classroom.retry = callback;
}

function renderStructuredError(error, context = "Classroom request failed", action = state.classroom.activeAction) {
  const target = $("structured-error");
  if (action !== state.classroom.activeAction) return;
  const code = error?.code || "network_error";
  const requestId = error?.requestId ? ` Request ID: ${error.requestId}.` : "";
  const message = `${context}: ${error?.message || "The server could not be reached."} (${code}).${requestId}`;
  if (target) {
    target.textContent = message;
    target.hidden = false;
  }
  const canRetry = Boolean(state.classroom.retryAction?.action === state.classroom.activeAction && (state.classroom.token || action === "auth"));
  $("classroom-retry-button").hidden = !canRetry;
  $("classroom-error-region").hidden = false;
  $("classroom-error-message").textContent = message;
  $("classroom-global-retry-button").hidden = !canRetry;
  $("server-diagnostics").textContent = "Retry is safe; the current editor draft remains local until the server accepts it.";
}

function announceClassroomAuthFailure(error) {
  state.classroom.activeAction = "auth";
  state.classroom.retryAction = { action: "auth", callback: initializeClassroom };
  renderStructuredError(error, "Classroom authentication expired. Please sign in again, then retry.", "auth");
}

function retryClassroomAction() {
  const retry = state.classroom.retryAction;
  if (!retry || retry.action !== state.classroom.activeAction) {
    clearStructuredError();
    return;
  }
  retry.callback();
}

function clearStructuredError() {
  const target = $("structured-error");
  if (target) { target.hidden = true; target.textContent = ""; }
  $("classroom-retry-button").hidden = true;
  $("classroom-error-region").hidden = true;
  $("classroom-error-message").textContent = "";
  $("classroom-global-retry-button").hidden = true;
  $("server-diagnostics").textContent = "";
  state.classroom.retryAction = null;
  state.classroom.retry = null;
}

function formatDeadline(value) {
  if (!value) return "No deadline supplied";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString();
}

function classroomPlanFingerprint(plan) {
  return JSON.stringify(plan);
}

function currentClassroomFingerprint() {
  return classroomPlanFingerprint({
    team_id: $("team-id")?.value || "",
    intervention_budget_k: $("intervention-budget")?.value || "",
    curtailment_depth_mu: $("curtailment-depth")?.value || "",
    flexibility_fee_per_mwh: $("flexibility-fee")?.value || "",
    connections: connectionDrafts(),
    generators: generatorDrafts(),
  });
}

function submissionAttemptStorageKey() {
  const classroom = state.classroom;
  const team = classroom.session?.team_id || "instructor";
  const session = classroom.sessionIdentity || "anonymous";
  return `ercot-classroom-submission:${session}:${classroom.roundId || "unknown"}:${team}`;
}

function tokenIdentity(token) {
  let hash = 2166136261;
  for (let index = 0; index < token.length; index += 1) hash = Math.imul(hash ^ token.charCodeAt(index), 16777619);
  return `token-${(hash >>> 0).toString(16)}`;
}

function resetClassroomPlanForm() {
  $("team-id").value = "";
  $("intervention-budget").value = "0";
  $("curtailment-depth").value = "0";
  $("flexibility-fee").value = "0";
  renderConnectionCards([]);
  renderGeneratorCards([]);
  clearFormErrors();
  invalidateEvaluation();
}

function applyClassroomDefaultPlan() {
  $("team-id").value = state.classroom.session?.team_id || "";
  $("intervention-budget").value = "0";
  $("curtailment-depth").value = "0";
  $("flexibility-fee").value = "0";
  const firstBus = state.scenario?.buses?.[0]?.bus_id || "";
  const horizon = Number(state.scenario?.time_horizon || 0);
  renderConnectionCards(firstBus && horizon ? [{ connection_id: "site-1", bus_id: firstBus, capacity_mw: 10, profile: Array(horizon).fill(1), path_corridors: [] }] : []);
  renderGeneratorCards([]);
}

function invalidateClassroomSession() {
  clearSubmissionSnapshot();
  try { sessionStorage.removeItem("ercot-classroom-session"); } catch (error) { /* storage is optional */ }
  window.ERCOT_CLASSROOM_SESSION = null;
  state.classroom.sessionGeneration += 1;
  state.classroom.actionGeneration += 1;
  state.classroom.roundRequestToken += 1;
  state.classroom.saveRequestToken += 1;
  state.classroom.instructorActionToken += 1;
  state.classroom.activeAction = null;
  state.classroom.retryAction = null;
  state.classroom.token = null;
  state.classroom.roundId = null;
  state.classroom.session = null;
  state.classroom.sessionIdentity = null;
  state.classroom.round = null;
  state.classroom.submission = null;
  state.classroom.leaderboard = null;
  state.classroom.saving = false;
  state.classroom.submitting = false;
  state.classroom.hydrated = false;
  state.classroom.savedFingerprint = null;
  state.classroom.submittedFingerprint = null;
  state.classroom.currentFingerprint = null;
  state.classroom.dirty = false;
  state.classroom.editRevision = 0;
  $("draft-status").textContent = "Not saved";
  $("submission-status").textContent = "Not submitted";
  state.classroom.pendingSubmissionKey = null;
  state.classroom.pendingSubmissionFingerprint = null;
  state.classroom.instructorActionInFlight = false;
  resetClassroomPlanForm();
  $("round-panel").hidden = true;
  $("round-results").hidden = true;
  updateClassroomControls();
}

function readSubmissionSnapshot() {
  try {
    const raw = window.sessionStorage.getItem(submissionAttemptStorageKey());
    return raw ? JSON.parse(raw) : {};
  } catch (error) {
    return {};
  }
}

function writeSubmissionSnapshot(snapshot) {
  try { window.sessionStorage.setItem(submissionAttemptStorageKey(), JSON.stringify(snapshot)); } catch (error) { /* storage is optional */ }
}

function clearSubmissionSnapshot() {
  try { window.sessionStorage.removeItem(submissionAttemptStorageKey()); } catch (error) { /* storage is optional */ }
}

function markClassroomDirty() {
  const classroom = state.classroom;
  if (!classroom.token) return;
  classroom.editRevision += 1;
  const fingerprint = currentClassroomFingerprint();
  classroom.currentFingerprint = fingerprint;
  if (classroom.pendingSubmissionFingerprint && classroom.pendingSubmissionFingerprint !== fingerprint) {
    classroom.pendingSubmissionKey = null;
    classroom.pendingSubmissionFingerprint = null;
    const stored = readSubmissionSnapshot();
    writeSubmissionSnapshot({ ...stored, pendingSubmissionKey: null, pendingSubmissionFingerprint: null });
  }
  classroom.dirty = classroom.savedFingerprint === null || classroom.savedFingerprint !== fingerprint;
  updateClassroomControls();
}

function getSubmissionAttemptKey(fingerprint) {
  const classroom = state.classroom;
  const stored = readSubmissionSnapshot();
  if (!classroom.pendingSubmissionKey && stored.pendingSubmissionKey && stored.pendingSubmissionFingerprint === fingerprint) {
    classroom.pendingSubmissionKey = stored.pendingSubmissionKey;
    classroom.pendingSubmissionFingerprint = stored.pendingSubmissionFingerprint;
  }
  if (classroom.pendingSubmissionKey && classroom.pendingSubmissionFingerprint === fingerprint) return classroom.pendingSubmissionKey;
  classroom.pendingSubmissionKey = window.crypto?.randomUUID?.() || `submission-${Date.now()}`;
  classroom.pendingSubmissionFingerprint = fingerprint;
  writeSubmissionSnapshot({ ...stored, pendingSubmissionKey: classroom.pendingSubmissionKey, pendingSubmissionFingerprint: fingerprint });
  return classroom.pendingSubmissionKey;
}

function roundIsOpen() {
  return state.classroom.round?.state === "open";
}

function updateClassroomControls() {
  const classroom = state.classroom;
  const enabled = Boolean(classroom.roundId && classroom.token && classroom.hydrated);
  const student = classroom.session?.role === "student";
  const canEdit = enabled && student && roundIsOpen() && !classroom.saving && !classroom.submitting;
  const save = $("save-draft-button");
  const submit = $("submit-plan-button");
  const matchesSubmitted = Boolean(classroom.submission && classroom.submittedFingerprint && classroom.currentFingerprint === classroom.submittedFingerprint);
  if (save) save.hidden = !student;
  if (submit) submit.hidden = !student;
  if (save) save.disabled = !canEdit || !classroom.dirty;
  if (submit) submit.disabled = !canEdit || matchesSubmitted;
  if (classroom.submission && classroom.submittedFingerprint && !matchesSubmitted) {
    $("server-diagnostics").textContent = "Current edits differ from submitted snapshot; save the draft and submit again when ready.";
  } else if (classroom.submission && matchesSubmitted) {
    $("server-diagnostics").textContent = "Current plan matches the immutable submitted snapshot.";
  }
  const practice = $("evaluate-button");
  if (practice) practice.hidden = enabled;
  const instructor = $("instructor-controls");
  if (instructor) instructor.hidden = classroom.session?.role !== "instructor";
  ["instructor-transition-button", "instructor-evaluate-button", "instructor-publish-button"].forEach((id) => {
    const button = $(id);
    if (button) button.disabled = !enabled || classroom.instructorActionInFlight;
  });
  if (enabled && !roundIsOpen()) {
    $("server-diagnostics").textContent = `Submissions are disabled while this round is ${classroom.round?.state || "unavailable"}.`;
  }
}

function renderRound(payload, requestToken) {
  if (requestToken !== state.classroom.roundRequestToken) return;
  state.classroom.round = { ...(state.classroom.round || {}), ...payload, policy: payload.policy || state.classroom.round?.policy || {} };
  payload = state.classroom.round;
  const panel = $("round-panel");
  if (!panel) return;
  panel.hidden = false;
  $("round-state").textContent = payload.state || "Unknown";
  $("round-state").className = `pill ${payload.state === "open" ? "pill-success" : "pill-muted"}`;
  $("round-team").textContent = payload.team_id || state.classroom.session?.team_id || "Instructor view";
  $("round-deadline").textContent = formatDeadline(payload.policy?.deadline_at);
  updateClassroomControls();
}

function renderSubmission(payload, requestToken) {
  if (requestToken !== state.classroom.roundRequestToken) return;
  state.classroom.submission = payload?.submission || null;
  const submission = state.classroom.submission;
  if (submission) {
    const stored = readSubmissionSnapshot();
    const serverFingerprint = submission.submitted_fingerprint || null;
    const currentFingerprint = currentClassroomFingerprint();
    const verified = Boolean(serverFingerprint && serverFingerprint === currentFingerprint);
    state.classroom.submittedFingerprint = verified ? serverFingerprint : null;
    writeSubmissionSnapshot({ ...stored, submittedFingerprint: verified ? serverFingerprint : null, pendingSubmissionKey: null, pendingSubmissionFingerprint: null });
  } else {
    state.classroom.submittedFingerprint = null;
    const stored = readSubmissionSnapshot();
    if (!stored.pendingSubmissionKey) clearSubmissionSnapshot();
  }
  $("submission-status").textContent = submission ? `${submission.status || "submitted"}${submission.submitted_at ? ` · ${formatDeadline(submission.submitted_at)}` : ""}` : "Not submitted";
  $("submit-confirmation").hidden = !submission;
  if (submission) $("submit-confirmation").textContent = `Immutable submission received${submission.submitted_at ? ` at ${formatDeadline(submission.submitted_at)}` : ""}.`;
  updateClassroomControls();
}

function leaderboardVisibilityContract(payload) {
  const visibility = payload.visibility ?? payload.policy?.visibility ?? null;
  const audience = payload.audience ?? payload.policy?.audience ?? null;
  const normalizedVisibility = visibility === null ? null : String(visibility).toLowerCase();
  const normalizedAudience = audience === null ? null : String(audience).toLowerCase();
  const conflict = normalizedVisibility !== null && normalizedAudience !== null && normalizedVisibility !== normalizedAudience;
  return { visibility, audience, explicit: visibility !== null || audience !== null, conflict, visible: payload.visible !== false };
}

function leaderboardAudienceAllows(payload, visibility_contract) {
  visibility_contract = visibility_contract || leaderboardVisibilityContract(payload);
  if (!visibility_contract.visible) return false;
  if (!visibility_contract.explicit) return false;
  if (visibility_contract.conflict) return false;
  if (payload.published !== true) return false;
  const role = state.classroom.session?.role;
  const audience = String(visibility_contract.audience || visibility_contract.visibility || "").toLowerCase();
  const knownAudiences = new Set(["public", "all", "students", "team", "private", "aggregate", "instructor", "hidden", "none"]);
  if (!knownAudiences.has(audience)) return false;
  if (role === "instructor") return ["public", "all", "students", "team", "private", "aggregate", "instructor"].includes(audience);
  if (role !== "student") return false;
  if (["hidden", "none", "instructor"].includes(audience)) return false;
  if (audience === "team" || audience === "private") {
    const teamId = state.classroom.session?.team_id;
    const results = Array.isArray(payload.results) ? payload.results : [];
    return Boolean(teamId && results.length && results.every((item) => item.team_id === teamId));
  }
  return ["public", "all", "students", "aggregate"].includes(audience);
}

function renderLeaderboard(payload, requestToken) {
  if (requestToken !== state.classroom.roundRequestToken) return;
  state.classroom.leaderboard = payload;
  const panel = $("round-results");
  const list = $("leaderboard");
  if (!panel || !list) return;
  panel.hidden = false;
  list.replaceChildren();
  const visibility_contract = leaderboardVisibilityContract(payload);
  const visibilityLabel = visibility_contract.explicit ? `Visibility: ${visibility_contract.audience || visibility_contract.visibility}` : "Visibility: unavailable";
  $("leaderboard-visibility").textContent = visibilityLabel;
  $("leaderboard-status").textContent = payload.published && leaderboardAudienceAllows(payload, visibility_contract) ? "Published" : "Hidden";
  if (!leaderboardAudienceAllows(payload, visibility_contract)) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = visibility_contract.explicit ? "Results are hidden for this audience by the server visibility policy." : "Results are hidden because the server did not provide a visibility audience.";
    list.appendChild(empty);
    return;
  }
  (Array.isArray(payload.results) ? payload.results : []).forEach((item) => {
    const row = document.createElement("div");
    row.className = "leaderboard-row";
    [
      ["Team", item.team_id || "Aggregate"],
      ["Rank", item.rank ?? "—"],
      ["Server total", item.authoritative_total ?? "—"],
      ["Tie group", item.tie_group ?? "—"],
      ["Teams", item.team_count ?? "—"],
    ].forEach(([label, value]) => {
      const cell = document.createElement("span");
      cell.textContent = `${label}: ${value}`;
      row.appendChild(cell);
    });
    list.appendChild(row);
  });
}

async function loadRound() {
  if (!state.classroom.roundId || !state.classroom.token) return;
  const requestToken = ++state.classroom.roundRequestToken;
  state.classroom.hydrated = false;
  updateClassroomControls();
  beginClassroomAction("load-round");
  try {
    const round = await classroomFetch(`/api/rounds/${encodeURIComponent(state.classroom.roundId)}`);
    if (requestToken !== state.classroom.roundRequestToken) return;
    renderRound(round, requestToken);
    await loadDraft(requestToken);
    if (requestToken !== state.classroom.roundRequestToken) return;
    await loadSubmissionStatus(requestToken);
    if (requestToken !== state.classroom.roundRequestToken) return;
    await loadLeaderboard(requestToken);
    if (requestToken !== state.classroom.roundRequestToken) return;
    state.classroom.hydrated = true;
    updateClassroomControls();
  } catch (error) {
    if (requestToken !== state.classroom.roundRequestToken) return;
    state.classroom.hydrated = false;
    updateClassroomControls();
    setClassroomRetry("load-round", loadRound);
    renderStructuredError(error, "Round could not be loaded", "load-round");
  }
}

async function loadDraft(requestToken = state.classroom.roundRequestToken) {
  const hydrationRevision = state.classroom.editRevision;
  const payload = await classroomFetch(`/api/rounds/${encodeURIComponent(state.classroom.roundId)}/draft`);
  if (requestToken !== state.classroom.roundRequestToken) return;
  const draft = payload.draft;
  if (hydrationRevision !== state.classroom.editRevision) {
    $("server-diagnostics").textContent = "Your edits were preserved; the server draft was not applied over them.";
    return;
  }
  if (!draft?.payload) {
    applyClassroomDefaultPlan();
    state.classroom.savedFingerprint = null;
    state.classroom.currentFingerprint = currentClassroomFingerprint();
    state.classroom.dirty = true;
    updateClassroomControls();
    return;
  }
  const plan = draft.payload;
  $("team-id").value = plan.team_id || state.classroom.session?.team_id || "";
  $("intervention-budget").value = plan.intervention_budget_k ?? 0;
  $("curtailment-depth").value = plan.curtailment_depth_mu ?? 0;
  $("flexibility-fee").value = plan.flexibility_fee_per_mwh ?? 0;
  renderConnectionCards(plan.connections || []);
  renderGeneratorCards(plan.generators || []);
  state.classroom.currentFingerprint = currentClassroomFingerprint();
  state.classroom.savedFingerprint = state.classroom.currentFingerprint;
  state.classroom.dirty = false;
  $("draft-status").textContent = draft.updated_at ? `Saved · ${formatDeadline(draft.updated_at)}` : "Saved";
  updateClassroomControls();
}

async function saveDraft() {
  if (!roundIsOpen()) return;
  const editRevision = state.classroom.editRevision;
  const plan = buildCanonicalPlan();
  if (!plan) return;
  const fingerprint = currentClassroomFingerprint();
  const requestToken = ++state.classroom.saveRequestToken;
  beginClassroomAction("save-draft");
  state.classroom.saving = true;
  $("save-draft-button").textContent = "Saving…";
  updateClassroomControls();
  try {
    const payload = await classroomFetch(`/api/rounds/${encodeURIComponent(state.classroom.roundId)}/draft`, { method: "PUT", body: JSON.stringify({ plan }) });
    if (requestToken !== state.classroom.saveRequestToken) return;
    if (editRevision === state.classroom.editRevision) {
      state.classroom.currentFingerprint = fingerprint;
      state.classroom.savedFingerprint = fingerprint;
      state.classroom.dirty = false;
      $("draft-status").textContent = payload.draft?.updated_at ? `Saved · ${formatDeadline(payload.draft.updated_at)}` : "Saved";
    } else {
      $("draft-status").textContent = "Earlier draft saved; newer local edits remain unsaved.";
    }
  } catch (error) {
    if (requestToken !== state.classroom.saveRequestToken) return;
    setClassroomRetry("save-draft", saveDraft);
    renderStructuredError(error, "Draft was not saved", "save-draft");
  } finally {
    if (requestToken === state.classroom.saveRequestToken) {
      state.classroom.saving = false;
      $("save-draft-button").textContent = "Save draft";
      updateClassroomControls();
    }
  }
}

async function submitPlan() {
  if (!roundIsOpen()) return;
  const editRevision = state.classroom.editRevision;
  const plan = buildCanonicalPlan();
  if (!plan) return;
  const fingerprint = currentClassroomFingerprint();
  const idempotencyKey = getSubmissionAttemptKey(fingerprint);
  const sessionGeneration = state.classroom.sessionGeneration;
  const actionToken = ++state.classroom.actionGeneration;
  beginClassroomAction("submit-plan");
  state.classroom.submitting = true;
  $("submit-plan-button").textContent = "Submitting…";
  updateClassroomControls();
  let accepted = false;
  try {
    const payload = await classroomFetch(`/api/rounds/${encodeURIComponent(state.classroom.roundId)}/submit`, { method: "POST", headers: { "Idempotency-Key": idempotencyKey }, body: JSON.stringify({ plan }) });
    if (sessionGeneration !== state.classroom.sessionGeneration || actionToken !== state.classroom.actionGeneration) return;
    accepted = true;
    state.classroom.pendingSubmissionKey = null;
    state.classroom.pendingSubmissionFingerprint = null;
    renderSubmission(payload, state.classroom.roundRequestToken);
    if (editRevision !== state.classroom.editRevision) {
      $("server-diagnostics").textContent = "Submission accepted for the earlier snapshot; newer local edits remain separate.";
    }
  } catch (error) {
    if (sessionGeneration !== state.classroom.sessionGeneration || actionToken !== state.classroom.actionGeneration) return;
    setClassroomRetry("submit-plan", submitPlan);
    renderStructuredError(error, "Plan was not submitted", "submit-plan");
    if (["round_not_open", "deadline_passed"].includes(error?.code)) updateClassroomControls();
  } finally {
    if (sessionGeneration === state.classroom.sessionGeneration && actionToken === state.classroom.actionGeneration) {
      state.classroom.submitting = false;
      $("submit-plan-button").textContent = "Submit plan";
      updateClassroomControls();
    }
  }
  if (accepted && sessionGeneration === state.classroom.sessionGeneration && actionToken === state.classroom.actionGeneration) await refreshLeaderboardAfterSubmission(sessionGeneration, actionToken);
}

async function refreshLeaderboardAfterSubmission(expectedSessionGeneration, expectedActionToken) {
  const sessionGeneration = expectedSessionGeneration ?? state.classroom.sessionGeneration;
  if (sessionGeneration !== state.classroom.sessionGeneration) return;
  if (expectedActionToken !== undefined && expectedActionToken !== state.classroom.actionGeneration) return;
  const actionToken = ++state.classroom.actionGeneration;
  beginClassroomAction("leaderboard-refresh");
  try {
    await loadLeaderboard(state.classroom.roundRequestToken, actionToken, sessionGeneration);
    if (sessionGeneration !== state.classroom.sessionGeneration || actionToken !== state.classroom.actionGeneration) return;
  } catch (error) {
    if (sessionGeneration !== state.classroom.sessionGeneration || actionToken !== state.classroom.actionGeneration) return;
    setClassroomRetry("leaderboard-refresh", () => refreshLeaderboardAfterSubmission(sessionGeneration, actionToken));
    renderStructuredError(error, "Submission accepted, but results could not be refreshed", "leaderboard-refresh");
  }
}

async function loadSubmissionStatus(requestToken = state.classroom.roundRequestToken) {
  const payload = await classroomFetch(`/api/rounds/${encodeURIComponent(state.classroom.roundId)}/submission`);
  if (requestToken !== state.classroom.roundRequestToken) return;
  renderSubmission(payload, requestToken);
}

async function loadLeaderboard(requestToken = state.classroom.roundRequestToken, actionToken = null, sessionGeneration = state.classroom.sessionGeneration) {
  const payload = await classroomFetch(`/api/rounds/${encodeURIComponent(state.classroom.roundId)}/leaderboard`);
  if (requestToken !== state.classroom.roundRequestToken || sessionGeneration !== state.classroom.sessionGeneration || (actionToken !== null && actionToken !== state.classroom.actionGeneration)) return;
  renderLeaderboard(payload, requestToken);
}

async function transitionRound(targetState) {
  if (state.classroom.instructorActionInFlight) return;
  const action = `transition:${targetState}`;
  const actionToken = ++state.classroom.instructorActionToken;
  const renderToken = ++state.classroom.roundRequestToken;
  state.classroom.instructorActionInFlight = true;
  beginClassroomAction(action);
  try {
    try {
      const payload = await classroomFetch(`/api/instructor/rounds/${encodeURIComponent(state.classroom.roundId)}/transition`, { method: "POST", body: JSON.stringify({ state: targetState }) });
      if (actionToken !== state.classroom.instructorActionToken) return;
      renderRound(payload, renderToken);
    } catch (error) {
      if (actionToken !== state.classroom.instructorActionToken) return;
      setClassroomRetry(action, () => transitionRound(targetState));
      renderStructuredError(error, "Round transition failed", action);
      return;
    }
    if (actionToken !== state.classroom.instructorActionToken) return;
    try {
      await loadLeaderboard();
    } catch (error) {
      if (actionToken !== state.classroom.instructorActionToken) return;
      setClassroomRetry(action, () => loadLeaderboard());
      renderStructuredError(error, "Round transition succeeded, but results could not be refreshed", action);
    }
  } finally {
    if (actionToken === state.classroom.instructorActionToken) state.classroom.instructorActionInFlight = false;
  }
}

async function evaluateRound() {
  if (state.classroom.instructorActionInFlight) return;
  const action = "evaluate-round";
  const actionToken = ++state.classroom.instructorActionToken;
  const renderToken = ++state.classroom.roundRequestToken;
  state.classroom.instructorActionInFlight = true;
  beginClassroomAction(action);
  try {
    try {
      const payload = await classroomFetch(`/api/instructor/rounds/${encodeURIComponent(state.classroom.roundId)}/evaluate`, { method: "POST", body: JSON.stringify({}) });
      if (actionToken !== state.classroom.instructorActionToken) return;
      renderRound(payload, renderToken);
    } catch (error) {
      if (actionToken !== state.classroom.instructorActionToken) return;
      setClassroomRetry(action, evaluateRound);
      renderStructuredError(error, "Round evaluation failed", action);
      return;
    }
    if (actionToken !== state.classroom.instructorActionToken) return;
    try {
      await loadLeaderboard();
    } catch (error) {
      if (actionToken !== state.classroom.instructorActionToken) return;
      setClassroomRetry(action, () => loadLeaderboard());
      renderStructuredError(error, "Round evaluation succeeded, but results could not be refreshed", action);
    }
  } finally {
    if (actionToken === state.classroom.instructorActionToken) state.classroom.instructorActionInFlight = false;
  }
}

function initializeClassroom() {
  const session = classroomSession();
  const token = session?.token;
  const details = session?.session || session;
  if (typeof token !== "string" || !token.trim() || typeof details?.round_id !== "string" || !details.round_id.trim()) {
    invalidateClassroomSession();
    return;
  }
  if (!["student", "instructor"].includes(details?.role)) {
    invalidateClassroomSession();
    return;
  }
  const identity = details.session_id || tokenIdentity(token);
  if (state.classroom.sessionIdentity && state.classroom.sessionIdentity !== identity) {
    invalidateClassroomSession();
  }
  state.classroom.token = token;
  state.classroom.roundId = details.round_id;
  state.classroom.session = details;
  state.classroom.sessionIdentity = identity;
  state.classroom.currentFingerprint = currentClassroomFingerprint();
  state.classroom.dirty = true;
  loadRound();
}

function populatePeriodSelector(horizon) { const selector = $("period-selector"); selector.replaceChildren(); for (let index = 0; index < horizon; index += 1) { const option = document.createElement("option"); option.value = String(index); option.textContent = `Period ${index + 1}`; selector.appendChild(option); } selector.value = String(state.period); }
function populateScenario(scenario) {
  state.scenario = scenario;
  state.period = Number(scenario.selected_period?.index || 0);
  $("scenario-state").textContent = "Ready";
  $("scenario-state").className = "pill pill-success";
  const planningMode = Boolean(scenario.planning_model?.model_id);
  const title = planningMode ? "ERCOT Planning Model" : (scenario.presentation?.title || "ERCOT Teaching Network");
  $("map-heading").textContent = title;
  $("map-title").textContent = title;
  $("map-description-copy").textContent = planningMode ? "Inspect planning regions and shared planning interfaces for the selected period." : "Inspect synthetic teaching buses and shared teaching corridors for the selected period.";
  $("map-description").textContent = planningMode ? "Focusable planning regions and interfaces show instructional headroom and shared capacity for the selected period." : "Focusable buses and transmission corridors show teaching headroom and shared capacity for the selected period.";
  $("geographic-map-panel-title").textContent = planningMode ? "ERCOT planning-model geographic map" : "ERCOT teaching-network geographic map";
  $("geographic-map-title").textContent = planningMode ? "Geographic ERCOT planning-model map" : "Geographic ERCOT teaching-network map";
  $("geographic-map-description").textContent = planningMode ? "Planning regions and interfaces shown in geographic context within Texas." : "Synthetic teaching buses and corridors shown in geographic context within Texas. Bus and corridor resources are instructional and do not represent actual ERCOT facilities.";
  $("practice-disclaimer").querySelector(".teaching-network-disclosure").textContent = planningMode
    ? "Planning Model V1 regions and interfaces are derived from public ERCOT-region evidence; scenario headroom and transfer limits are instructional conditions, not operating ratings."
    : "Teaching network: Bus locations, names, and transmission corridors are synthetic and intended for instructional use; they do not represent actual ERCOT facilities.";
  $("map-buses-layer").setAttribute("aria-label", planningMode ? "Planning model regions" : "Synthetic teaching buses");
  $("map-corridors-layer").setAttribute("aria-label", planningMode ? "Planning model interfaces" : "Teaching transmission corridors");
  const hints = arrayOrEmpty(scenario.tutorial_hints);
  if (hints.length) $("map-meaning").textContent = hints[0];
  populatePeriodSelector(scenario.time_horizon);
  renderConnectionCards([{ connection_id: "site-1", bus_id: scenario.buses[0]?.bus_id || "", capacity_mw: 10, profile: Array(scenario.time_horizon).fill(1), path_corridors: [] }]);
  renderGeneratorCards([]);
  $("evaluate-button").disabled = false;
  $("workspace").setAttribute("aria-busy", "false");
  $("map-status").textContent = `Period ${state.period + 1} loaded. Select a planning region or interface for details.`;
  resetGeographicViewport();
  renderMap();
  setStatus("Scenario ready. Build a versioned planning plan and run a practice evaluation.", "success");
}

async function loadScenarioPeriod(period) {
  const requestToken = ++state.scenarioRequestToken;
  state.scenarioRevision += 1;
  state.scenarioRequestController?.abort();
  const controller = new AbortController();
  state.scenarioRequestController = controller;
  invalidateEvaluation();
  try {
    const response = await fetch(`/api/scenario?period=${period}`, { signal: controller.signal });
    const scenario = await response.json();
    if (requestToken !== state.scenarioRequestToken) return;
    if (!response.ok) throw new Error(scenario.error?.message || "Scenario period request failed.");
    const schemaError = validateScenarioPayload(scenario);
    if (schemaError) throw new Error(`server returned an invalid scenario response: ${schemaError}`);
    state.period = period;
    state.scenario = scenario;
    updateScenarioMetadata(scenario);
    $("period-selector").value = String(period);
    renderMap();
    $("map-status").textContent = `Period ${period + 1} loaded. Current connection and generator cards were preserved.`;
    setStatus(`Showing scenario period ${period + 1}; current plan state preserved.`, "success");
  } catch (error) {
    if (requestToken !== state.scenarioRequestToken || error?.name === "AbortError") return;
    $("period-selector").value = String(state.period);
    setStatus(`Unable to load that scenario period: ${error instanceof Error ? error.message : "request error"}`, "error");
  } finally {
    if (requestToken === state.scenarioRequestToken) state.scenarioRequestController = null;
  }
}

async function loadScenario() {
  const requestToken = ++state.scenarioRequestToken;
  state.scenarioRevision += 1;
  state.scenarioRequestController?.abort();
  const controller = new AbortController();
  state.scenarioRequestController = controller;
  setStatus("Loading the practice scenario…");
  try {
    const response = await fetch("/api/scenario?period=0", { signal: controller.signal });
    const scenario = await response.json();
    if (requestToken !== state.scenarioRequestToken) return;
    if (!response.ok) throw new Error(scenario.error?.message || "Scenario request failed.");
    const schemaError = validateScenarioPayload(scenario);
    if (schemaError) throw new Error(`server returned an invalid scenario response: ${schemaError}`);
    populateScenario(scenario);
    updateScenarioMetadata(scenario);
    return true;
  } catch (error) {
    if (requestToken !== state.scenarioRequestToken || error?.name === "AbortError") return;
    $("scenario-state").textContent = "Error";
    $("scenario-state").className = "pill pill-danger";
    $("map-status").textContent = "The map cannot render until scenario data is available.";
    $("evaluate-button").disabled = true;
    setStatus(`Unable to load the practice scenario: ${error instanceof Error ? error.message : "request error"}`, "error");
    return false;
  } finally {
    if (requestToken === state.scenarioRequestToken) state.scenarioRequestController = null;
  }
}

function bindEvents() { setupGeographicMapControls(); $("layer-public-transmission")?.addEventListener("change", (event) => { state.publicLayers.transmission = event.currentTarget.checked; renderLegend(); renderGeographicMap(); }); $("layer-teaching-network")?.addEventListener("change", (event) => { state.publicLayers.teaching = event.currentTarget.checked; renderGeographicMap(); }); $("layer-generation")?.addEventListener("change", (event) => { state.publicLayers.generation = event.currentTarget.checked; renderLegend(); renderGeographicMap(); }); $("plan-form").addEventListener("submit", evaluatePlan); $("plan-form").addEventListener("input", handlePlanInputChange); $("plan-form").addEventListener("change", handlePlanInputChange); $("period-selector").addEventListener("change", (event) => loadScenarioPeriod(Number(event.target.value))); $("add-connection").addEventListener("click", () => addConnectionCard()); $("add-generator").addEventListener("click", addGeneratorCard); $("save-draft-button").addEventListener("click", saveDraft); $("submit-plan-button").addEventListener("click", submitPlan); $("explore-network-button")?.addEventListener("click", () => { $("network-section")?.scrollIntoView({ behavior: "smooth", block: "start" }); $("geographic-map")?.focus(); }); $("instructor-transition-button").addEventListener("click", (event) => transitionRound(event.currentTarget.dataset.state)); $("instructor-evaluate-button").addEventListener("click", evaluateRound); $("instructor-publish-button").addEventListener("click", () => transitionRound("published")); $("close-drawer").addEventListener("click", () => { state.selectedResource = null; $("resource-drawer-heading").textContent = "No resource selected"; const placeholder = document.createElement("p"); placeholder.className = "muted"; placeholder.textContent = "Select a Planning Region, Planning Interface, or connection site to keep its details visible here."; $("resource-drawer-content").replaceChildren(placeholder); $("map-selection").textContent = "No resource selected"; updateResourceSelectionState(); }); $("plan-form").addEventListener("click", (event) => { const button = event.target.closest("button[data-action]"); if (!button) return; const card = button.closest(".repeatable-card"); if (button.dataset.action === "view-site") openSiteDrawer(card); if (button.dataset.action === "duplicate-connection") duplicateConnectionCard(card); if (button.dataset.action === "remove-connection") removeConnectionCard(card); if (button.dataset.action === "remove-generator") removeGeneratorCard(card); }); }

function isResultsViewActive() {
  return window.location.pathname.replace(/\/$/, "").endsWith("/results")
    || new URLSearchParams(window.location.search).get("view") === "results";
}

document.addEventListener("DOMContentLoaded", () => { if (isResultsViewActive()) return; bindEvents(); setupSectionNavigation(); $("classroom-retry-button").addEventListener("click", retryClassroomAction); $("classroom-global-retry-button").addEventListener("click", retryClassroomAction); loadScenario().then((scenarioReady) => { if (scenarioReady) initializeClassroom(); }); loadCountyAsset(); loadTexasBoundaryAsset(); loadPublicNetwork(); });
