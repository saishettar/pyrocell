let meta = null;
let map = null;
let imageOverlay = null;
let playing = false;
let playTimer = null;
let perimeterLayer = null;
let ignitionMarker = null;
let pickedMarker = null;
let picking = false;
let mode = "demo"; // "demo" | "custom"
let currentFire = "soberanes";

const FIRE_LABELS = {
  soberanes: { title: "Soberanes Fire", ignitionPopup: "2016-07-22 8:48am PDT" },
  dolan: { title: "Dolan Fire", ignitionPopup: "2020-08-18 8:15pm PDT" },
};

const slider = document.getElementById("slider");
const playBtn = document.getElementById("playBtn");
const hourLabel = document.getElementById("hourLabel");
const maxHourLabel = document.getElementById("maxHourLabel");
const acresLabel = document.getElementById("acresLabel");
const perimeterToggle = document.getElementById("perimeterToggle");
const pickBtn = document.getElementById("pickBtn");
const pickStatus = document.getElementById("pickStatus");
const hoursSelect = document.getElementById("hoursSelect");
const dateInput = document.getElementById("dateInput");
const runBtn = document.getElementById("runBtn");
const simStatus = document.getElementById("simStatus");
const resetBtn = document.getElementById("resetBtn");
const titleEl = document.getElementById("title");
const subtitleEl = document.getElementById("subtitle");
const mapDiv = document.getElementById("map");
const fireSelect = document.getElementById("fireSelect");

async function init() {
  map = L.map("map", { zoomControl: true });

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap contributors",
    maxZoom: 17,
  }).addTo(map);

  imageOverlay = L.imageOverlay("", [[0, 0], [0, 0]], { opacity: 0.85 }).addTo(map);

  slider.addEventListener("input", () => setHour(parseInt(slider.value, 10)));
  playBtn.addEventListener("click", togglePlay);
  pickBtn.addEventListener("click", togglePicking);
  map.on("click", onMapClick);
  runBtn.addEventListener("click", runCustomSimulation);
  resetBtn.addEventListener("click", () => loadDemo(currentFire));
  fireSelect.addEventListener("change", () => {
    if (picking) togglePicking();
    if (pickedMarker) { map.removeLayer(pickedMarker); pickedMarker = null; }
    runBtn.disabled = true;
    pickStatus.textContent = "";
    simStatus.textContent = "";
    loadDemo(fireSelect.value);
  });

  await loadDemo(currentFire);
}

async function loadDemo(fireSlug) {
  currentFire = fireSlug;
  mode = "demo";
  if (playing) togglePlay();

  meta = await fetch(`/api/meta?fire=${fireSlug}`).then((r) => r.json());
  applyMeta(meta);

  const bounds = [
    [meta.bounds.south, meta.bounds.west],
    [meta.bounds.north, meta.bounds.east],
  ];
  map.invalidateSize();
  map.fitBounds(bounds, { padding: [40, 40] });

  const label = FIRE_LABELS[fireSlug] || { title: meta.fire_name, ignitionPopup: meta.ignition_time_utc };
  titleEl.textContent = `${label.title} — simulated spread`;
  subtitleEl.textContent = "Real terrain, fuel, and hourly wind · calibrated CA model";
  resetBtn.style.display = "none";

  if (ignitionMarker) map.removeLayer(ignitionMarker);
  ignitionMarker = L.marker([meta.ignition.lat, meta.ignition.lon])
    .addTo(map)
    .bindPopup(`${label.title} ignition point<br>${label.ignitionPopup}`);

  if (perimeterLayer) map.removeLayer(perimeterLayer);
  const perimeterGeojson = await fetch(`/api/perimeter?fire=${fireSlug}`).then((r) => r.json());
  perimeterLayer = L.geoJSON(perimeterGeojson, {
    style: { color: "#2255ff", weight: 2.5, fillOpacity: 0 },
  });
  if (perimeterToggle.checked) perimeterLayer.addTo(map);

  setHour(0);
}

perimeterToggle.addEventListener("change", () => {
  if (!perimeterLayer) return;
  if (perimeterToggle.checked) perimeterLayer.addTo(map);
  else map.removeLayer(perimeterLayer);
});

function applyMeta(m) {
  slider.max = m.n_hours;
  maxHourLabel.textContent = m.n_hours;
}

function frameUrl(hour) {
  if (mode === "custom" && meta.frames) return meta.frames[hour];
  return `/frames/${currentFire}/frame_${String(hour).padStart(4, "0")}.png`;
}

function setHour(hour) {
  hour = Math.max(0, Math.min(meta.n_hours, hour));
  slider.value = hour;
  hourLabel.textContent = hour;
  imageOverlay.setUrl(frameUrl(hour));
  const entry = meta.hours[hour];
  acresLabel.textContent = entry ? entry.acres.toLocaleString() : "0";
}

function togglePlay() {
  playing = !playing;
  playBtn.innerHTML = playing ? "&#10074;&#10074;" : "&#9654;";
  if (playing) {
    playTimer = setInterval(() => {
      let next = parseInt(slider.value, 10) + 1;
      if (next > meta.n_hours) next = 0;
      setHour(next);
    }, 120);
  } else {
    clearInterval(playTimer);
  }
}

function togglePicking() {
  picking = !picking;
  mapDiv.classList.toggle("picking", picking);
  pickBtn.textContent = picking ? "Click anywhere on the map..." : "Click map to choose start point";
  if (!picking) pickStatus.textContent = "";
}

function onMapClick(e) {
  if (!picking) return;
  const { lat, lng } = e.latlng;

  if (pickedMarker) map.removeLayer(pickedMarker);
  pickedMarker = L.marker([lat, lng], { opacity: 0.9 }).addTo(map);

  pickStatus.textContent = `start point: ${lat.toFixed(4)}, ${lng.toFixed(4)}`;
  runBtn.disabled = false;
  togglePicking();
}

async function runCustomSimulation() {
  if (!pickedMarker) return;
  const { lat, lng } = pickedMarker.getLatLng();
  const hours = parseInt(hoursSelect.value, 10);
  const dateVal = dateInput.value; // "" if blank

  runBtn.disabled = true;
  simStatus.textContent = `running ${hours}h simulation... (can take 10-30s)`;
  if (playing) togglePlay();

  const body = { lat, lon: lng, hours, fire: currentFire };
  if (dateVal) body.start_time = dateVal + ":00";

  let resp;
  try {
    resp = await fetch("/api/simulate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (err) {
    simStatus.textContent = `network error: ${err}`;
    runBtn.disabled = false;
    return;
  }

  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    simStatus.textContent = `error: ${err.detail || resp.statusText}`;
    runBtn.disabled = false;
    return;
  }

  const result = await resp.json();
  mode = "custom";
  meta = result; // { ignition, n_hours, hours, frames, wind_source, start_time }
  applyMeta(meta);

  titleEl.textContent = "Custom simulation";
  subtitleEl.textContent = `wind: ${result.wind_source} · start: ${result.start_time}`;
  resetBtn.style.display = "block";
  simStatus.textContent = `done — ${result.hours[result.hours.length - 1].acres.toLocaleString()} acres at hour ${result.n_hours}`;
  runBtn.disabled = false;

  setHour(0);
}

init();
