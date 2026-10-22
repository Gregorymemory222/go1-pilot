// Go1 Pilot – okno sterowania; całą komunikację z psem robi server.py
const $ = (id) => document.getElementById(id);

// klawisz -> [oś, kierunek]; osie: 0 bokiem, 1 obrót, 2 głowa, 3 przód/tył
const KEYS = { w: [3, 1], s: [3, -1], a: [0, -1], d: [0, 1], q: [1, -1], e: [1, 1], r: [2, 1], f: [2, -1] };
const MODE_NAMES = {
  standUp: "Wstań", standDown: "Połóż się", recoverStand: "Podnieś po upadku", stand: "Poza",
  walk: "Chód", run: "Bieg", climb: "Wspinaczka", dance1: "Taniec 1", dance2: "Taniec 2",
  straightHand1: "Podaj łapę", jumpYaw: "Skok z obrotem", damping: "Zwiotcz silniki",
};
const MOTION = {
  w: "do przodu", s: "do tyłu", a: "bokiem w lewo", d: "bokiem w prawo",
  q: "obrót w lewo", e: "obrót w prawo", r: "głowa w górę", f: "głowa w dół",
};

// skróty do komend; „Zwiotcz silniki” celowo bez skrótu
const MODE_KEYS = new Map([
  ["1", "standUp"], ["2", "standDown"], ["3", "recoverStand"], ["4", "walk"], ["5", "run"], ["6", "climb"],
  ["7", "stand"], ["8", "dance1"], ["9", "dance2"], ["0", "straightHand1"], ["j", "jumpYaw"],
]);

const pressed = new Set();
let state = null;
let serverDown = false;
let firstRender = true;

async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return res.json();
}

// --- stan z serwera ---
async function poll() {
  try {
    render(await api("/api/state"));
    setServerDown(false);
  } catch {
    setServerDown(true);
  }
  setTimeout(poll, 250);
}

function setServerDown(down) {
  if (down === serverDown) return;
  serverDown = down;
  let banner = document.querySelector(".offline-banner");
  if (down && !banner) {
    banner = document.createElement("div");
    banner.className = "offline-banner";
    banner.textContent = "Program w tle jest wyłączony. Uruchom start.bat jeszcze raz.";
    document.body.append(banner);
  } else if (!down && banner) {
    banner.remove();
  }
}

function render(s) {
  state = s;
  if (firstRender) {
    initFromSettings(s);
    if (location.hash === "#ustawienia") setTimeout(openSettings);
    if (location.hash === "#skroty") setTimeout(() => $("helpDialog").showModal());
  }
  firstRender = false;

  document.body.classList.toggle("connected", s.connected);
  const status = $("status");
  const waiting = s.status.startsWith("Łączenie") || s.status.startsWith("Rozłączono");
  status.className = "status " + (s.connected ? "on" : waiting ? "wait" : s.status.startsWith("Błąd") ? "err" : "");
  $("statusText").textContent = s.connected ? "Połączono" : s.status;
  const linked = s.connected || waiting;
  $("linkBtn").textContent = linked ? "Rozłącz" : "Połącz";
  $("linkBtn").classList.toggle("primary", !linked);
  $("host").disabled = linked;
  if (linked) $("host").value = s.host;

  document.querySelectorAll(".cmd, #dampBtn").forEach((b) => (b.disabled = !s.connected));
  document.querySelectorAll("[data-mode]").forEach((b) => b.classList.toggle("active", b.dataset.mode === s.mode));

  const battery = $("battery");
  battery.hidden = s.battery == null;
  if (s.battery != null) {
    $("batteryText").textContent = `${s.battery}%`;
    $("batteryFill").style.width = `calc(${s.battery}% - 2px)`;
    battery.classList.toggle("low", s.battery <= 20);
    battery.title = `Bateria psa: ${s.battery}%`;
  }
  $("notice").textContent = s.notice;

  const maxSpeed = Math.round(s.settings.max_speed * 100);
  $("speed").max = maxSpeed;
  if (document.activeElement !== $("speed")) {
    $("speed").value = Math.round(s.speed * 100);
    $("speedOut").textContent = `${$("speed").value}%`;
  }

  renderVoice(s.voice);
  renderCamera(s.camera);
  renderLog(s.log);
  renderHud(s);
  if (!pressed.size) showReadout(s.axes);
}

function initFromSettings(s) {
  $("host").value = s.host;
  lastVoiceSeq = s.voice.seq;
  for (const [key, mode] of MODE_KEYS) {
    const kbd = document.createElement("kbd");
    kbd.textContent = key.toUpperCase();
    document.querySelector(`[data-mode="${mode}"]`).append(kbd);
    const dt = document.createElement("dt");
    dt.append(kbd.cloneNode(true));
    const dd = document.createElement("dd");
    dd.textContent = MODE_NAMES[mode];
    $("helpModes").append(dt, dd);
  }
  const cam = $("camSelect");
  s.camera.cameras.forEach((label, i) => cam.append(new Option(label, i)));
  cam.value = s.settings.camera_index;
  loadMics(s.settings.mic_device);
}

function renderVoice(v) {
  $("level").style.width = `${Math.round(v.level * 100)}%`;
  $("mutedBox").hidden = v.muted !== true;
  $("micBtn").setAttribute("aria-pressed", String(v.on));
  $("micLabel").textContent = v.on ? "Wyłącz słuchanie" : "Włącz słuchanie";
  $("voiceStatus").textContent = v.status;
  const heard = $("heard");
  if (v.heard) {
    heard.textContent = `„${v.heard}”`;
    heard.classList.remove("idle");
  }
  $("done").textContent = v.command ? `Wykonano: ${v.command}` : "";
  $("talkBtn").hidden = !(v.on && state.settings.mic_mode === "ptt");
  $("talkBtn").classList.toggle("down", v.talking);
  if (v.seq !== lastVoiceSeq) {
    lastVoiceSeq = v.seq;
    if (state.settings.voice_beeps) beep(v.result);
  }
}

// --- dźwięk potwierdzenia: wysoki = wykonane, niski = pominięte / brak połączenia ---
let lastVoiceSeq = null;
let audioCtx = null;
const BEEPS = { ok: [[660, 0], [990, 0.11]], rejected: [[300, 0]], offline: [[300, 0], [300, 0.16]] };

function beep(result) {
  try {
    audioCtx = audioCtx || new AudioContext();
    for (const [freq, at] of BEEPS[result] || []) {
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();
      const t = audioCtx.currentTime + at;
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0.0001, t);
      gain.gain.exponentialRampToValueAtTime(0.25, t + 0.01);
      gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.1);
      osc.connect(gain).connect(audioCtx.destination);
      osc.start(t);
      osc.stop(t + 0.12);
    }
  } catch {
    /* brak dźwięku nie psuje sterowania */
  }
}

function renderHud(s) {
  $("hudMode").textContent = s.mode ? MODE_NAMES[s.mode] : s.connected ? "Połączono" : "Niepołączono";
  $("hudSpeed").textContent = `Prędkość ${Math.round(s.speed * 100)}%`;
  $("hudBattery").textContent = s.battery != null ? `Bateria ${s.battery}%` : "";
  $("hudVoice").textContent = s.voice.on && s.voice.heard ? `„${s.voice.heard}”` : "";
}

const streamState = (c, i) => (c.streams[i] ? c.streams[i].state : "off");
let mainShown = null; // numer kamery w głównym podglądzie albo null

function renderCamera(c) {
  $("camBtn").textContent = c.busy ? "Łączę…" : c.on ? "Wyłącz kamerę" : "Włącz kamerę";
  $("camBtn").disabled = c.busy && !c.on;
  $("gridBtn").classList.toggle("active", c.grid);
  $("camStatus").textContent = c.status;
  $("camStatus").classList.toggle("err", c.status.startsWith("błąd"));
  if (document.activeElement !== $("camSelect")) $("camSelect").value = c.main;

  // główny podgląd: strumień MJPEG z kamery głównej
  const showMain = !c.grid && streamState(c, c.main) === "on" ? c.main : null;
  if (showMain !== mainShown) {
    mainShown = showMain;
    const img = $("camImg");
    if (showMain !== null) img.src = `/camera.mjpg?cam=${showMain}&t=${Date.now()}`;
    else img.removeAttribute("src");
    img.hidden = showMain === null;
  }
  $("camEmpty").hidden = showMain !== null || c.grid;
  renderGrid(c);

  const live = streamState(c, c.main) === "on";
  $("photoBtn").disabled = !live;
  $("recBtn").disabled = !live && !c.recording;
  $("recBtn").classList.toggle("on", Boolean(c.recording));
  $("recLabel").textContent = c.recording ? `Zatrzymaj ${clock(c.recording.seconds)}` : "Nagrywaj";
  $("hudRec").textContent = c.recording ? `● REC ${clock(c.recording.seconds)}` : "";
  if (!camError) $("camSaved").textContent = c.saved;
}

const clock = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

// siatka: każdy kafelek pobiera pojedyncze klatki po kolei (5 ciągłych strumieni zajęłoby
// limit 6 połączeń przeglądarki i zablokowało resztę okna)
let gridOn = false;
function renderGrid(c) {
  const grid = $("camGrid");
  if (!grid.children.length) {
    c.cameras.forEach((label, i) => {
      const tile = document.createElement("button");
      tile.className = "tile";
      tile.innerHTML = `<img alt="" hidden><span class="tile-state"></span><span class="tile-label"></span>`;
      tile.querySelector(".tile-label").textContent = label;
      tile.addEventListener("click", async () => render((await api("/api/camera/grid", { on: false, main: i })).state));
      grid.append(tile);
    });
  }
  grid.hidden = !c.grid;
  gridOn = c.grid;
  [...grid.children].forEach((tile, i) => {
    const s = c.streams[i];
    const on = s && s.state === "on";
    tile.classList.toggle("main", i === c.main);
    tile.querySelector(".tile-state").textContent = on ? "" : s ? s.text : "wyłączona";
    const img = tile.querySelector("img");
    img.hidden = !on;
    if (on && !img.dataset.loop) pullTile(img, i);
  });
}

function pullTile(img, i) {
  img.dataset.loop = "1";
  const next = (delay) => setTimeout(() => {
    if (!gridOn || !state || streamState(state.camera, i) !== "on") {
      delete img.dataset.loop;
      return;
    }
    img.src = `/camera.jpg?cam=${i}&t=${Date.now()}`;
  }, delay);
  img.onload = () => next(120);
  img.onerror = () => next(1000);
  next(0);
}

let lastLogKey = "";
function renderLog(entries) {
  const key = entries.map((e) => e.join(" ")).join("|");
  if (key === lastLogKey || !entries.length) return;
  lastLogKey = key;
  $("log").replaceChildren(
    ...entries.slice().reverse().map(([time, text]) => {
      const li = document.createElement("li");
      const t = document.createElement("time");
      t.textContent = time;
      li.append(t, text);
      return li;
    })
  );
}

function showReadout(axes) {
  const [side, turn, head, fwd] = axes;
  const parts = [];
  if (fwd) parts.push(fwd > 0 ? "do przodu" : "do tyłu");
  if (side) parts.push(side > 0 ? "bokiem w prawo" : "bokiem w lewo");
  if (turn) parts.push(turn > 0 ? "obrót w prawo" : "obrót w lewo");
  if (head) parts.push(head > 0 ? "głowa w górę" : "głowa w dół");
  $("readout").textContent = parts.length ? `Ruch: ${parts.join(", ")}` : "Pies stoi w miejscu.";
}

// --- jazda ---
function speed() {
  return Number($("speed").value) / 100;
}

function sendAxes() {
  const axes = [0, 0, 0, 0];
  for (const k of pressed) axes[KEYS[k][0]] += KEYS[k][1] * speed();
  document.querySelectorAll(".key[data-key]").forEach((el) => el.classList.toggle("down", pressed.has(el.dataset.key)));
  $("readout").textContent = pressed.size
    ? `Ruch: ${[...pressed].map((k) => MOTION[k]).join(", ")}`
    : "Pies stoi w miejscu.";
  api("/api/axes", { axes }).catch(() => {});
}

function press(key) {
  if (key === "space") return stopAll();
  if (!KEYS[key] || pressed.has(key)) return;
  pressed.add(key);
  sendAxes();
}

function release(key) {
  if (pressed.delete(key)) sendAxes();
}

function stopAll() {
  pressed.clear();
  sendAxes();
  const space = document.querySelector('[data-key="space"]');
  space.classList.add("down");
  setTimeout(() => space.classList.remove("down"), 150);
}

const typing = (e) => e.target.matches("input:not([type=range]):not([type=color]):not([type=checkbox]), select") ||
  $("settingsDialog").open;

const anyDialogOpen = () => [...document.querySelectorAll("dialog")].some((d) => d.open);

document.addEventListener("keydown", (e) => {
  if (typing(e) || e.ctrlKey || e.altKey || e.metaKey || anyDialogOpen()) return;
  const key = e.code === "Space" ? "space" : e.key.toLowerCase();
  if (key === "space" || KEYS[key]) {
    e.preventDefault();
    if (!e.repeat) press(key);
    return;
  }
  if (e.repeat) return;
  if (MODE_KEYS.has(key)) {
    const btn = document.querySelector(`[data-mode="${MODE_KEYS.get(key)}"]`);
    if (!btn.disabled) btn.click();
  } else if (key === "m") $("micBtn").click();
  else if (key === "k") $("camBtn").click();
  else if (key === "g") $("gridBtn").click();
  else if (key === "z") takePhoto();
  else if (key === "n") toggleRecording();
  else if (key === "p") toggleFullscreen();
  else if (key === "h") $("helpDialog").showModal();
  else if (key === "v") setTalking(true);
  else if (key === "+" || key === "=") nudgeSpeed(+5);
  else if (key === "-") nudgeSpeed(-5);
  else return;
  e.preventDefault();
});
document.addEventListener("keyup", (e) => {
  const key = e.key.toLowerCase();
  if (key === "v") setTalking(false);
  release(key);
});
window.addEventListener("blur", () => {
  setTalking(false);
  if (pressed.size) stopAll();
});

function nudgeSpeed(delta) {
  const slider = $("speed");
  slider.value = Math.min(Number(slider.max), Math.max(Number(slider.min), Number(slider.value) + delta));
  slider.dispatchEvent(new Event("input"));
}

let talking = false;
function setTalking(down) {
  if (down === talking || !state || !state.voice.on || state.settings.mic_mode !== "ptt") return;
  talking = down;
  $("talkBtn").classList.toggle("down", down);
  api("/api/ptt", { down }).catch(() => {});
}
$("talkBtn").addEventListener("pointerdown", (e) => {
  $("talkBtn").setPointerCapture(e.pointerId);
  setTalking(true);
});
for (const ev of ["pointerup", "pointercancel", "lostpointercapture"]) {
  $("talkBtn").addEventListener(ev, () => setTalking(false));
}

function toggleFullscreen() {
  if (document.fullscreenElement) document.exitFullscreen();
  else $("camera").requestFullscreen().catch(() => {});
}
$("fullBtn").addEventListener("click", toggleFullscreen);
$("camera").addEventListener("dblclick", toggleFullscreen);
$("helpBtn").addEventListener("click", () => $("helpDialog").showModal());
document.addEventListener("visibilitychange", () => document.hidden && stopAll());

document.querySelectorAll(".key[data-key]").forEach((el) => {
  const key = el.dataset.key;
  el.addEventListener("pointerdown", (e) => {
    el.setPointerCapture(e.pointerId);
    press(key);
  });
  for (const ev of ["pointerup", "pointercancel", "lostpointercapture"]) el.addEventListener(ev, () => release(key));
  el.addEventListener("click", (e) => e.preventDefault());
});

$("speed").addEventListener("input", () => {
  $("speedOut").textContent = `${$("speed").value}%`;
  api("/api/speed", { speed: speed() }).catch(() => {});
  if (pressed.size) sendAxes();
});

// --- komendy ---
$("linkForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const linked = state && (state.connected || $("linkBtn").textContent === "Rozłącz");
  render((await api(linked ? "/api/disconnect" : "/api/connect", { host: $("host").value })).state);
});

document.querySelectorAll("[data-mode]").forEach((b) =>
  b.addEventListener("click", async () => {
    pressed.clear();
    render((await api("/api/mode", { mode: b.dataset.mode })).state);
    $("readout").textContent = `Wysłano: ${MODE_NAMES[b.dataset.mode]}`;
  })
);

$("ledBtn").addEventListener("click", () => {
  const hex = $("led").value;
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
  api("/api/led", { r, g, b });
});

async function damp() {
  render((await api("/api/mode", { mode: "damping" })).state);
}
$("dampBtn").addEventListener("click", () => {
  stopAll();
  if (state && !state.settings.confirm_damping) return damp();
  $("dampDialog").showModal();
});
$("dampDialog").addEventListener("close", () => {
  if ($("dampDialog").returnValue === "confirm") damp();
});

// --- kamera ---
let camError = false;
async function cameraAction(path, body = {}) {
  const res = await api(path, body);
  camError = Boolean(res.error);
  $("camSaved").textContent = res.error ? `Nie udało się: ${res.error}` : "";
  $("camSaved").classList.toggle("err", camError);
  if (camError) {
    setTimeout(() => {
      camError = false;
      $("camSaved").classList.remove("err");
    }, 5000);
  }
  if (res.state) render(res.state);
  return res;
}

$("camBtn").addEventListener("click", () =>
  cameraAction("/api/camera", { on: !(state && state.camera.on), index: Number($("camSelect").value) }));
$("camSelect").addEventListener("change", () => {
  if (state && state.camera.on) cameraAction("/api/camera", { on: true, index: Number($("camSelect").value) });
});
$("gridBtn").addEventListener("click", () =>
  cameraAction("/api/camera/grid", { on: !(state && state.camera.grid), main: Number($("camSelect").value) }));
$("camImg").addEventListener("error", () => {
  setTimeout(() => {
    if (mainShown !== null) $("camImg").src = `/camera.mjpg?cam=${mainShown}&t=${Date.now()}`;
  }, 1000);
});

async function takePhoto() {
  if ($("photoBtn").disabled) return;
  const res = await cameraAction("/api/camera/photo");
  if (!res.error) {
    $("flash").classList.remove("go");
    void $("flash").offsetWidth; // restart animacji przy kolejnym zdjęciu
    $("flash").classList.add("go");
  }
}
const toggleRecording = () => {
  if (!$("recBtn").disabled) cameraAction("/api/camera/record", { on: !(state && state.camera.recording) });
};
$("photoBtn").addEventListener("click", takePhoto);
$("recBtn").addEventListener("click", toggleRecording);
$("photosFolder").addEventListener("click", () => api("/api/open-folder", { kind: "photos" }));
$("videosFolder").addEventListener("click", () => api("/api/open-folder", { kind: "videos" }));

// --- głos ---
const micDevice = () => ($("micSelect").value === "" ? null : Number($("micSelect").value));

$("micBtn").addEventListener("click", async () => {
  const on = $("micBtn").getAttribute("aria-pressed") !== "true";
  render((await api("/api/voice", { on, device: micDevice() })).state);
});

$("micSelect").addEventListener("change", async () => {
  if (state && state.voice.on) render((await api("/api/voice", { on: true, device: micDevice() })).state);
});

$("unmuteBtn").addEventListener("click", async () => render((await api("/api/unmute", {})).state));

async function loadMics(selected) {
  try {
    const mics = await api("/api/mics");
    for (const m of mics) $("micSelect").append(new Option(m.name, m.id));
    if (selected != null) $("micSelect").value = selected;
  } catch {
    /* lista mikrofonów jest dodatkiem – bez niej działa domyślny */
  }
}

// --- ustawienia ---
const form = $("settingsForm");

function showRangeValue(input) {
  const out = input.nextElementSibling;
  out.textContent = "percent" in input.dataset ? `${input.value}%` : `${input.value} s`;
}

function openSettings() {
  const s = state.settings;
  for (const el of form.elements) {
    if (!el.name) continue;
    if (el.type === "checkbox") el.checked = Boolean(s[el.name]);
    else if (el.type === "password") el.value = "";
    else if ("percent" in el.dataset) el.value = Math.round(s[el.name] * 100);
    else el.value = s[el.name];
    if (el.type === "range") showRangeValue(el);
  }
  $("settingsDialog").showModal();
}
$("settingsBtn").addEventListener("click", openSettings);

form.querySelectorAll("input[type=range]").forEach((el) => el.addEventListener("input", () => showRangeValue(el)));

$("settingsDialog").addEventListener("close", async () => {
  if ($("settingsDialog").returnValue !== "save") return;
  const data = {};
  for (const el of form.elements) {
    if (!el.name) continue;
    if (el.type === "checkbox") data[el.name] = el.checked;
    else if ("percent" in el.dataset) data[el.name] = Number(el.value) / 100;
    else if (el.type === "range") data[el.name] = Number(el.value);
    else data[el.name] = el.value;
  }
  render((await api("/api/settings", data)).state);
  if (!state.connected) $("host").value = state.settings.host;
});

poll();
