/* CUTTER MAKER — веб-клиент (server-профиль, единый gateway). */
"use strict";

const GW = ""; // same origin → путь идёт через gateway
const state = {
  paths: [],        // после разбора / лечения (слой "исходник/вылеченный")
  source: [],
  healed: [],
  visual: [],       // УФ-маска (визуальные слои)
  cnc: [],          // контуры ЧПУ
  maskWkt: "",
  tool: null,
  post: null,
};

const $ = (id) => document.getElementById(id);
const cv = $("cv");
const ctx = cv.getContext("2d");
const colors = {
  source: "#9aa3b8",
  healed: "#17191f",
  mask: "#5b3df5",
  cnc: "#0f7b4f",
};

function log(msg, cls) {
  const el = $("log");
  const line = document.createElement("div");
  if (cls) line.className = cls;
  line.textContent = msg;
  el.appendChild(line);
  el.scrollTop = el.scrollHeight;
}
function status(msg) { $("status").textContent = msg; }

async function api(path, payload) {
  const r = await fetch(GW + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload ?? {}),
  });
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail || detail; } catch (e) {}
    throw new Error(`${path}: ${detail}`);
  }
  return r.json();
}

async function job(svc, path, payload, timeoutMs = 60000) {
  const ref = await api(`/${svc}${path}`, payload);
  const t0 = Date.now();
  for (;;) {
    if (Date.now() - t0 > timeoutMs) throw new Error(`Таймаут задачи ${ref.job_id}`);
    const r = await fetch(`${GW}/${svc}/v1/jobs/${ref.job_id}`);
    if (!r.ok) throw new Error(`Опрос статуса: HTTP ${r.status}`);
    const st = await r.json();
    if (st.status === "done") return st.result ?? {};
    if (st.status === "error") throw new Error(st.error || "Ошибка задачи");
    await new Promise((res) => setTimeout(res, 250));
  }
}

/* ---------------- отрисовка ---------------- */
function fitTransform(paths) {
  let minx = Infinity, miny = Infinity, maxx = -Infinity, maxy = -Infinity;
  for (const p of paths)
    for (const pt of p.points) {
      if (pt[0] < minx) minx = pt[0];
      if (pt[0] > maxx) maxx = pt[0];
      if (pt[1] < miny) miny = pt[1];
      if (pt[1] > maxy) maxy = pt[1];
    }
  if (!isFinite(minx)) return null;
  const w = Math.max(maxx - minx, 1e-6), h = Math.max(maxy - miny, 1e-6);
  const pad = 30;
  const sx = (cv.width - 2 * pad) / w, sy = (cv.height - 2 * pad) / h;
  const s = Math.min(sx, sy);
  const ox = (cv.width - w * s) / 2, oy = (cv.height - h * s) / 2;
  return (x, y) => [ox + (x - minx) * s, oy + (maxy - y) * s]; // Y вверх → экран вниз
}

function strokePaths(paths, color, width) {
  const t = fitTransformAll();
  if (!t) return;
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.lineJoin = "round";
  for (const p of paths) {
    if (!p.points.length) continue;
    ctx.beginPath();
    p.points.forEach((pt, i) => {
      const [sx, sy] = t(pt[0], pt[1]);
      i === 0 ? ctx.moveTo(sx, sy) : ctx.lineTo(sx, sy);
    });
    if (p.is_closed) ctx.closePath();
    ctx.stroke();
  }
}

function fitTransformAll() {
  const layers = [];
  if ($("ly-source").checked) layers.push(...state.source);
  if ($("ly-healed").checked) layers.push(...state.healed);
  if ($("ly-mask").checked) layers.push(...state.visual);
  if ($("ly-cnc").checked) layers.push(...state.cnc);
  return fitTransform(layers.length ? layers : state.paths);
}

function draw() {
  cv.width = cv.clientWidth * devicePixelRatio;
  cv.height = cv.clientHeight * devicePixelRatio;
  ctx.clearRect(0, 0, cv.width, cv.height);
  ctx.save();
  ctx.scale(1, 1);
  if ($("ly-source").checked) strokePaths(state.source, colors.source, 1.2 * devicePixelRatio);
  if ($("ly-healed").checked) strokePaths(state.healed, colors.healed, 1.4 * devicePixelRatio);
  if ($("ly-mask").checked) strokePaths(state.visual, colors.mask, 1.6 * devicePixelRatio);
  if ($("ly-cnc").checked) strokePaths(state.cnc, colors.cnc, 1.2 * devicePixelRatio);
  ctx.restore();
  $("empty").style.display = (state.source.length || state.healed.length) ? "none" : "flex";
}

function updateStats(extra) {
  const n = (arr) => arr.length;
  let s = `Исходник: ${n(state.source)} контуров\nВылечено: ${n(state.healed)}\n` +
          `Маска: ${n(state.visual)} · ЧПУ: ${n(state.cnc)}`;
  if (extra) s += `\n${extra}`;
  $("stats").textContent = s;
}

function enable(...ids) { ids.forEach((id) => ($(id).disabled = false)); }

async function pollRoot(jobId, timeoutMs = 300000) {
  const t0 = Date.now();
  for (;;) {
    if (Date.now() - t0 > timeoutMs) throw new Error(`Таймаут задачи ${jobId}`);
    const r = await fetch(`${GW}/v1/jobs/${jobId}`);
    if (!r.ok) throw new Error(`Опрос статуса: HTTP ${r.status}`);
    const st = await r.json();
    if (st.status === "done") return st.result ?? {};
    if (st.status === "error") throw new Error(st.error || "Ошибка задачи");
    await new Promise((res) => setTimeout(res, 400));
  }
}

function downloadGcode(text) {
  if (!text) return;
  const blob = new Blob([text], { type: "text/plain" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "cutter_maker.nc";
  a.click();
  URL.revokeObjectURL(a.href);
}

async function pipeline() {
  const f = $("file").files[0];
  if (!f) { status("Выберите файл"); return; }
  status(`Полный цикл: ${f.name} (parse → heal → маска → G-код)…`);
  const fd = new FormData();
  fd.append("file", f);
  fd.append("tolerance", "2.0");
  fd.append("min_loop_area", "1.0");
  fd.append("offset", "0.2");
  fd.append("badge_text", "WEB");
  fd.append("lead_radius", "1.5");
  fd.append("milling_dir", "Climb (Попутное)");
  fd.append("enable_sharpening", "true");
  const r = await fetch(`${GW}/v1/pipeline`, { method: "POST", body: fd });
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail || detail; } catch (e) {}
    throw new Error(`pipeline: ${detail}`);
  }
  const ref = await r.json();
  const res = await pollRoot(ref.job_id);
  state.source = res.source_paths || [];
  state.healed = res.healed_paths || [];
  state.visual = res.visual_paths || [];
  state.cnc = res.cnc_paths || [];
  state.maskWkt = res.mask_geom_wkt || "";
  const cs = res.check_stats || {};
  updateStats(
    `Ошибки: дубли ${cs.duplicates ?? 0}, пересечения ${cs.intersections ?? 0}, ` +
    `пыль ${cs.dust ?? 0}\nМашинное время: ${(res.time_min ?? 0).toFixed(2)} мин`
  );
  draw();
  enable("b-check", "b-heal", "b-mask", "b-gcode");
  downloadGcode(res.gcode_text);
  const lines = (res.gcode_text || "").split("\n").filter(Boolean).length;
  log(`Весь цикл: ${state.source.length} → ${state.healed.length} контуров, ` +
      `G-код ${lines} строк, ${res.time_min.toFixed(2)} мин`, "ok");
  status(`Готово: ${res.time_min.toFixed(2)} мин машинного времени, файл .nc скачан`);
}

/* ---------------- шаги ---------------- */
async function parse() {
  const f = $("file").files[0];
  if (!f) { status("Выберите файл"); return; }
  status(`Разбор ${f.name}…`);
  const fd = new FormData();
  fd.append("file", f);
  const r = await fetch(`${GW}/ingest/v1/parse`, { method: "POST", body: fd });
  if (!r.ok) {
    let d = r.statusText;
    try { d = (await r.json()).detail || d; } catch (e) {}
    throw new Error(`parse: ${d}`);
  }
  const ref = await r.json();
  const res = await poll(ref.job_id, "ingest");
  state.source = res.paths || [];
  state.healed = []; state.visual = []; state.cnc = []; state.maskWkt = "";
  state.paths = state.source;
  updateStats(); draw();
  log(`Извлечено контуров: ${state.source.length}`, "ok");
  enable("b-check", "b-heal", "b-mask");
  status("Готово: векторы извлечены");
}

async function poll(jobId, svc, timeoutMs = 60000) {
  const t0 = Date.now();
  for (;;) {
    if (Date.now() - t0 > timeoutMs) throw new Error(`Таймаут задачи ${jobId}`);
    const r = await fetch(`${GW}/${svc}/v1/jobs/${jobId}`);
    if (!r.ok) throw new Error(`Опрос статуса: HTTP ${r.status}`);
    const st = await r.json();
    if (st.status === "done") return st.result ?? {};
    if (st.status === "error") throw new Error(st.error || "Ошибка задачи");
    await new Promise((res) => setTimeout(res, 250));
  }
}

async function check() {
  status("Анализ ошибок…");
  const paths = state.healed.length ? state.healed : state.source;
  const res = await job("geometry", "/v1/check-errors", { paths, min_loop_area: 1.0 });
  const bad = res.open_paths + res.intersections + res.duplicates + res.empty_paths;
  updateStats(`Ошибки: открыты ${res.open_paths}, пересечения ${res.intersections}, ` +
              `дубли ${res.duplicates}, пыль ${res.dust ?? 0}`);
  log(`Анализ: проблем ${bad}`, bad ? "err" : "ok");
  status("Анализ завершён");
}

async function heal() {
  status("Лечение геометрии…");
  const src = state.source;
  const res = await job("geometry", "/v1/heal", {
    paths: src, tolerance: 2.0, min_loop_area: 1.0,
  });
  state.healed = res.paths || [];
  state.paths = state.healed;
  updateStats(); draw();
  log(`Вылечено контуров: ${state.healed.length}`, "ok");
  enable("b-mask");
  status("Лечение завершено");
}

async function uvMask() {
  status("Генерация УФ-маски…");
  const paths = state.healed.length ? state.healed : state.source;
  const res = await job("render", "/v1/uv-mask", {
    paths, offset: 0.2, output_path: "/tmp/web_mask.pdf",
    badge_text: "WEB", mark_d: 4.0, mark_margin: 10.0,
  });
  state.visual = res.visual_paths || [];
  state.maskWkt = res.mask_geom_wkt || "";
  updateStats(); draw();
  log("УФ-маска построена", "ok");
  enable("b-gcode");
  status("Маска готова");
}

async function ensureTools() {
  if (state.tool && state.post) return;
  const tools = (await api("/state/v1/tools/load", {})).tools || [];
  const posts = (await api("/state/v1/posts/load", {})).posts || [];
  if (!tools.length || !posts.length) throw new Error("БД инструментов/постпроцессоров пуста");
  state.tool = tools[0];
  state.post = posts[0];
}

async function gcode() {
  if (!state.maskWkt) throw new Error("Сначала постройте УФ-маску");
  status("Генерация G-кода…");
  await ensureTools();
  const res = await job("cam", "/v1/gcode", {
    mask_geom_wkt: state.maskWkt,
    output_path: "/tmp/web_out.nc",
    tool: state.tool,
    post: state.post,
    mask_offset: 0.2,
    enable_sharpening: true,
    lead_radius: 1.5,
    milling_dir: "Climb (Попутное)",
  }, 120000);
  state.cnc = res.cnc_paths || [];
  updateStats(`Время фрезеровки: ${res.time_min.toFixed(2)} мин`);
  draw();
  if (res.gcode_text) {
    downloadGcode(res.gcode_text);
    log(`G-код: ${res.gcode_text.split("\n").length} строк, скачан`, "ok");
  } else {
    log("G-код готов (без текста в ответе)", "ok");
  }
  status(`Готово: ${res.time_min.toFixed(2)} мин машинного времени`);
}

/* ---------------- обвязка ---------------- */
function wrap(fn) {
  return (...args) => Promise.resolve()
    .then(() => fn(...args))
    .catch((e) => { log(String(e.message || e), "err"); status(`Ошибка: ${e.message || e}`); });
}

$("b-parse").addEventListener("click", wrap(parse));
$("b-pipeline").addEventListener("click", wrap(pipeline));
$("b-check").addEventListener("click", wrap(check));
$("b-heal").addEventListener("click", wrap(heal));
$("b-mask").addEventListener("click", wrap(uvMask));
$("b-gcode").addEventListener("click", wrap(gcode));
["ly-source", "ly-healed", "ly-mask", "ly-cnc"].forEach((id) =>
  $(id).addEventListener("change", draw));
window.addEventListener("resize", draw);

fetch(`${GW}/health`).then((r) => r.json()).then((h) => {
  status(h.ok ? "Шлюз: все сервисы онлайн" : "Шлюз: есть офлайн-сервисы — см. /health");
  log(h.ok ? "gateway: все 7 сервисов ок" : "gateway: " + JSON.stringify(h.backends), h.ok ? "ok" : "err");
}).catch((e) => log("Шлюз недоступен: " + e, "err"));

draw();
