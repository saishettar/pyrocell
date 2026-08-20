let meta = null;
let map = null;
let imageOverlay = null;
let playing = false;
let playTimer = null;

const slider = document.getElementById("slider");
const playBtn = document.getElementById("playBtn");
const hourLabel = document.getElementById("hourLabel");
const acresLabel = document.getElementById("acresLabel");
const perimeterToggle = document.getElementById("perimeterToggle");

async function init() {
  meta = await fetch("/api/meta").then((r) => r.json());

  const bounds = [
    [meta.bounds.south, meta.bounds.west],
    [meta.bounds.north, meta.bounds.east],
  ];

  map = L.map("map", { zoomControl: true });

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap contributors",
    maxZoom: 17,
  }).addTo(map);

  // Container layout isn't committed yet on first paint, so fitBounds run
  // synchronously here can compute against a zero-size map and fall back
  // to max zoom. Force a size recalculation first.
  map.invalidateSize();
  map.fitBounds(bounds, { padding: [40, 40] });

  imageOverlay = L.imageOverlay(frameUrl(0), bounds, { opacity: 0.85 }).addTo(map);

  L.marker([meta.ignition.lat, meta.ignition.lon])
    .addTo(map)
    .bindPopup("Ignition point<br>2016-07-22 8:48am PDT");

  const perimeterGeojson = await fetch("/api/perimeter").then((r) => r.json());
  const perimeterLayer = L.geoJSON(perimeterGeojson, {
    style: { color: "#2255ff", weight: 2.5, fillOpacity: 0 },
  });
  if (perimeterToggle.checked) perimeterLayer.addTo(map);
  perimeterToggle.addEventListener("change", () => {
    if (perimeterToggle.checked) perimeterLayer.addTo(map);
    else map.removeLayer(perimeterLayer);
  });

  slider.max = meta.n_hours;
  slider.addEventListener("input", () => setHour(parseInt(slider.value, 10)));

  playBtn.addEventListener("click", togglePlay);

  setHour(0);
}

function frameUrl(hour) {
  return `/frames/frame_${String(hour).padStart(4, "0")}.png`;
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
      if (next > meta.n_hours) next = 0; // loop
      setHour(next);
    }, 120);
  } else {
    clearInterval(playTimer);
  }
}

init();
