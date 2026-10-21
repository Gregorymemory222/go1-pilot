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

const pressed = new Set();
let state = null;
let serverDown = false;

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

  if (document.activeElement !== $("speed")) {
    $("speed").value = Math.round(s.speed * 100);
    $("speedOut").textContent = `${$("speed").value}%`;
  }

  const v = s.voice;
  $("level").style.width = `${Math.round(v.level * 100)}%`;
  $("mutedBox").hidden = v.muted !== true;
  $("micBtn").setAttribute("aria-pressed", String(v.on));
  $("micLabel").textContent = v.on ? "Wyłącz słuchanie" : "Włącz słuchanie";
  $("voiceStatus").textContent = v.status;
  const heard = $("heard");
  if (v.heard) {
    heard.textContent = `„${v.heard}”`;
    heard.classList.remove("idle");
  } else {
    heard.classList.add("idle");
  }
  $("done").textContent = v.command ? `Wykonano: ${v.command}` : "";

  if (!pressed.size) showReadout(s.axes);
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

const typing = (e) => e.target.matches("input:not([type=range]):not([type=color])");

document.addEventListener("keydown", (e) => {
  if (typing(e) || e.repeat || e.ctrlKey || e.altKey) return;
  const key = e.code === "Space" ? "space" : e.key.toLowerCase();
  if (key === "space" || KEYS[key]) {
    e.preventDefault();
    press(key);
  }
});
document.addEventListener("keyup", (e) => release(e.key.toLowerCase()));
window.addEventListener("blur", () => pressed.size && stopAll());
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

$("dampBtn").addEventListener("click", () => {
  stopAll();
  $("dampDialog").showModal();
});
$("dampDialog").addEventListener("close", async () => {
  if ($("dampDialog").returnValue === "confirm") {
    render((await api("/api/mode", { mode: "damping" })).state);
  }
});

const micDevice = () => ($("micSelect").value === "" ? null : Number($("micSelect").value));

$("micBtn").addEventListener("click", async () => {
  const on = $("micBtn").getAttribute("aria-pressed") !== "true";
  render((await api("/api/voice", { on, device: micDevice() })).state);
});

$("micSelect").addEventListener("change", async () => {
  if (state && state.voice.on) render((await api("/api/voice", { on: true, device: micDevice() })).state);
});

$("unmuteBtn").addEventListener("click", async () => render((await api("/api/unmute", {})).state));

async function loadMics() {
  try {
    const mics = await api("/api/mics");
    for (const m of mics) $("micSelect").append(new Option(m.name, m.id));
  } catch {
    /* lista mikrofonów jest dodatkiem – bez niej działa domyślny */
  }
}

loadMics();
poll();
