/* MyIDEA2MyLEGO frontend: upload → options → convert → preview/instructions/BoM. */
"use strict";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];

const state = {
  file: null,
  result: null,     // server response
  rotation: 0,      // 3D preview rotation (0..3)
  maxLayer: 1,      // 3D preview "built up to" layer
  instLayer: 0,     // instructions current layer/row (0-based)
};

/* ---------------------------------------------------------------- upload */

const dropzone = $("#dropzone");
const fileInput = $("#file-input");

dropzone.addEventListener("click", () => fileInput.click());
dropzone.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") fileInput.click();
});
fileInput.addEventListener("change", () => acceptFile(fileInput.files[0]));

["dragenter", "dragover"].forEach((ev) =>
  dropzone.addEventListener(ev, (e) => {
    e.preventDefault();
    dropzone.classList.add("drag");
  })
);
["dragleave", "drop"].forEach((ev) =>
  dropzone.addEventListener(ev, (e) => {
    e.preventDefault();
    dropzone.classList.remove("drag");
  })
);
dropzone.addEventListener("drop", (e) => acceptFile(e.dataTransfer.files[0]));
document.addEventListener("paste", (e) => {
  const item = [...(e.clipboardData?.items || [])].find((i) => i.type.startsWith("image/"));
  if (item) acceptFile(item.getAsFile());
});

function acceptFile(file) {
  if (!file || !file.type.startsWith("image/")) return;
  state.file = file;
  const img = $("#preview-img");
  img.src = URL.createObjectURL(file);
  img.hidden = false;
  $("#drop-hint").hidden = true;
  $("#build-btn").disabled = false;
  setStatus("");
}

/* --------------------------------------------------------------- options */

$$(".mode-card").forEach((card) =>
  card.addEventListener("click", () => {
    $$(".mode-card").forEach((c) => c.classList.remove("selected"));
    card.classList.add("selected");
    card.querySelector("input").checked = true;
    const mode = card.dataset.mode;
    $$(".mosaic-only").forEach((el) => (el.hidden = mode !== "mosaic"));
    $$(".statue-only").forEach((el) => (el.hidden = mode !== "statue"));
    $$(".relief-only").forEach((el) => (el.hidden = mode !== "relief"));
  })
);

function bindRange(rangeSel, outSel, fmt) {
  const r = $(rangeSel), o = $(outSel);
  const update = () => {
    o.textContent = r.value;
    if (fmt) fmt(+r.value);
  };
  r.addEventListener("input", update);
  update();
}
bindRange("#opt-width", "#width-out", (v) => {
  $("#width-note").textContent = `${v} studs ≈ ${(v * 0.8).toFixed(0)} cm wide`;
});
bindRange("#opt-depth", "#depth-out");
bindRange("#opt-relief-height", "#relief-height-out");

/* --------------------------------------------------------------- convert */

const FUN = [
  "Sorting bricks by color…",
  "Emptying the big bin onto the carpet…",
  "Asking a minifig for a second opinion…",
  "Counting studs twice, placing once…",
  "Stepping on a brick so you don't have to…",
  "Snapping layers together…",
];

$("#build-btn").addEventListener("click", async () => {
  if (!state.file) return;
  const btn = $("#build-btn");
  btn.disabled = true;
  btn.classList.add("working");
  let funIdx = 0;
  setStatus(FUN[0]);
  const funTimer = setInterval(() => setStatus(FUN[++funIdx % FUN.length]), 1600);

  const mode = document.querySelector("input[name=mode]:checked").value;
  const fd = new FormData();
  fd.append("file", state.file);
  fd.append("mode", mode);
  fd.append("width", $("#opt-width").value);
  fd.append("palette_mode", $("#opt-palette").value);
  fd.append("dither", $("#opt-dither").checked);
  fd.append("optimize", $("#opt-optimize").checked);
  fd.append("depth", $("#opt-depth").value);
  fd.append("relief_height", $("#opt-relief-height").value);
  fd.append("invert", $("#opt-invert").checked);
  fd.append("hollow_inside", $("#opt-hollow").checked);

  try {
    const res = await fetch("/api/convert", { method: "POST", body: fd });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Conversion failed (${res.status})`);
    }
    state.result = await res.json();
    state.rotation = 0;
    state.instLayer = 0;
    state.maxLayer = totalLayers();
    showResults();
    setStatus("");
  } catch (err) {
    setStatus(err.message, true);
  } finally {
    clearInterval(funTimer);
    btn.disabled = false;
    btn.classList.remove("working");
  }
});

function setStatus(msg, isError = false) {
  const el = $("#status");
  el.textContent = msg;
  el.classList.toggle("error", isError);
}

/* --------------------------------------------------------------- results */

function is3D() {
  return state.result && state.result.mode !== "mosaic";
}
function totalLayers() {
  const r = state.result;
  return is3D() ? r.grid_size.layers : r.grid.length;
}
function partNames() {
  const map = {};
  for (const row of state.result.bom) map[row.part] = row.part_name;
  return map;
}

function showResults() {
  const r = state.result;
  $("#results").hidden = false;

  // Stats row
  const s = r.stats;
  const cards = [
    [r.totals.pieces.toLocaleString(), "pieces"],
    [r.totals.lots, "part+color lots"],
    [
      is3D()
        ? `${s.size_cm[0]}×${s.size_cm[1]}×${s.size_cm[2]}`
        : `${s.size_cm[0]}×${s.size_cm[1]}`,
      "size (cm)",
    ],
    [s.layers, is3D() ? "build layers" : "layer (flat)"],
    [`$${r.totals.est_price_usd.toLocaleString()}`, "est. parts price*"],
    [
      r.totals.est_weight_g >= 1000
        ? `${(r.totals.est_weight_g / 1000).toFixed(1)} kg`
        : `${r.totals.est_weight_g} g`,
      "est. weight",
    ],
  ];
  if (!is3D() && s.baseplates_32) cards.push([s.baseplates_32, "32×32 baseplates"]);
  $("#stats-row").innerHTML = cards
    .map(([b, l]) => `<div class="stat"><b>${b}</b><span>${l}</span></div>`)
    .join("");

  // Stability note (3D only)
  const note = $("#stability-note");
  if (is3D() && r.stability) {
    note.hidden = false;
    if (r.stability.buildable) {
      note.className = "ok";
      note.textContent = "✓ Every brick connects to the layer below — this builds straight up with no supports.";
    } else {
      note.className = "warn";
      note.textContent = `⚠ ${r.stability.floating_bricks} brick(s) have no support below them (overhangs). Add temporary supports while building, or try Relief mode.`;
    }
  } else {
    note.hidden = true;
  }

  // Preview tools
  $$(".three-d-only").forEach((el) => (el.hidden = !is3D()));
  if (is3D()) {
    const slider = $("#layer-slider");
    slider.max = totalLayers();
    slider.value = totalLayers();
    $("#layer-out").textContent = `${totalLayers()} / ${totalLayers()}`;
  }

  // Instructions tools
  const inst = $("#inst-slider");
  inst.max = totalLayers();
  inst.value = 1;
  $("#inst-hint").textContent = is3D()
    ? "Build one layer at a time, bottom to top. Gray shapes show the layer underneath. The downloadable ZIP has these as printable PNGs, and model.ldr opens in LeoCAD/LPub3D with one STEP per layer."
    : "Work row by row onto baseplates, top row first. Long plates are placed left to right. The ZIP includes a numbered build chart you can print.";

  renderPreview();
  renderInstructions();
  renderParts();
  $("#results").scrollIntoView({ behavior: "smooth", block: "start" });
}

/* ------------------------------------------------------------------ tabs */

$$(".tab").forEach((tab) =>
  tab.addEventListener("click", () => {
    $$(".tab").forEach((t) => t.classList.remove("selected"));
    tab.classList.add("selected");
    const which = tab.dataset.tab;
    $("#panel-preview").hidden = which !== "preview";
    $("#panel-instructions").hidden = which !== "instructions";
    $("#panel-parts").hidden = which !== "parts";
    if (which === "preview") renderPreview();
    if (which === "instructions") renderInstructions();
  })
);

$("#layer-slider").addEventListener("input", (e) => {
  state.maxLayer = +e.target.value;
  $("#layer-out").textContent = `${state.maxLayer} / ${totalLayers()}`;
  renderPreview();
});
$("#rotate-btn").addEventListener("click", () => {
  state.rotation = (state.rotation + 1) % 4;
  renderPreview();
});
$("#inst-slider").addEventListener("input", (e) => {
  state.instLayer = +e.target.value - 1;
  renderInstructions();
});
$("#inst-prev").addEventListener("click", () => stepInst(-1));
$("#inst-next").addEventListener("click", () => stepInst(1));
function stepInst(d) {
  state.instLayer = Math.max(0, Math.min(totalLayers() - 1, state.instLayer + d));
  $("#inst-slider").value = state.instLayer + 1;
  renderInstructions();
}

/* ---------------------------------------------------------------- canvas */

function setupCanvas(canvas, w, h) {
  const dpr = window.devicePixelRatio || 1;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  canvas.style.width = w + "px";
  canvas.style.height = h + "px";
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return ctx;
}

function hexToRgb(hex) {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
function shade(rgb, f) {
  return `rgb(${rgb.map((c) => Math.max(0, Math.min(255, Math.round(c * f)))).join(",")})`;
}

/* ------------------------------------------------------------- 2D mosaic */

function renderMosaicPreview() {
  const r = state.result;
  const grid = r.grid;
  const rows = grid.length, cols = grid[0].length;
  const avail = Math.min(920, $(".canvas-wrap").clientWidth - 24 || 900);
  const cell = Math.max(4, Math.min(20, Math.floor(avail / cols)));
  const ctx = setupCanvas($("#preview-canvas"), cols * cell, rows * cell);

  for (let y = 0; y < rows; y++) {
    for (let x = 0; x < cols; x++) {
      const rgb = hexToRgb(r.palette[grid[y][x]].hex);
      ctx.fillStyle = shade(rgb, 1);
      ctx.fillRect(x * cell, y * cell, cell, cell);
      if (cell >= 6) {
        ctx.beginPath();
        ctx.arc(x * cell + cell / 2, y * cell + cell / 2, cell * 0.32, 0, Math.PI * 2);
        ctx.strokeStyle = shade(rgb, 0.82);
        ctx.lineWidth = 1;
        ctx.stroke();
        ctx.beginPath();
        ctx.arc(x * cell + cell / 2, y * cell + cell / 2, cell * 0.32, Math.PI, Math.PI * 1.7);
        ctx.strokeStyle = shade(rgb, 1.22);
        ctx.stroke();
      }
    }
  }
}

/* --------------------------------------------------------- 3D isometric */

function rotatedBricks() {
  const r = state.result;
  let W = r.grid_size.x, D = r.grid_size.z;
  let bricks = r.bricks.map((b) => ({ ...b }));
  for (let i = 0; i < state.rotation; i++) {
    bricks = bricks.map((b) => ({
      ...b,
      x: D - (b.z + b.zlen),
      z: b.x,
      xlen: b.zlen,
      zlen: b.xlen,
    }));
    [W, D] = [D, W];
  }
  return { bricks, W, D };
}

function renderIso() {
  const { bricks, W, D } = rotatedBricks();
  const layers = totalLayers();
  const visible = bricks.filter((b) => b.layer < state.maxLayer);

  const avail = Math.min(920, $(".canvas-wrap").clientWidth - 24 || 900);
  // Pick s so the projected width fits.
  const projWidthUnits = (W + D) * 0.866;
  const s = Math.max(3, Math.min(26, Math.floor(avail / projWidthUnits)));
  const ISO_X = s * 0.866, ISO_Y = s * 0.5, H = s * 1.2;

  const px = (x, z) => (x - z) * ISO_X;
  const py = (x, z, y) => (x + z) * ISO_Y - y * H;

  const minX = px(0, D), maxX = px(W, 0);
  const minY = py(0, 0, layers), maxY = py(W, D, 0);
  const pad = 16;
  const cw = maxX - minX + pad * 2, ch = maxY - minY + pad * 2;
  const ctx = setupCanvas($("#preview-canvas"), cw, ch);
  const ox = pad - minX, oy = pad - minY;

  const P = (x, z, y) => [ox + px(x, z), oy + py(x, z, y)];
  const poly = (pts, fill, stroke) => {
    ctx.beginPath();
    ctx.moveTo(pts[0][0], pts[0][1]);
    for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
    ctx.closePath();
    ctx.fillStyle = fill;
    ctx.fill();
    if (stroke) {
      ctx.strokeStyle = stroke;
      ctx.lineWidth = 0.75;
      ctx.stroke();
    }
  };
  const seg = (a, b, stroke) => {
    ctx.beginPath();
    ctx.moveTo(a[0], a[1]);
    ctx.lineTo(b[0], b[1]);
    ctx.strokeStyle = stroke;
    ctx.lineWidth = 0.9;
    ctx.stroke();
  };

  // Per-brick painter ordering is not a valid occlusion order for
  // mixed-size boxes, so render per unit cell: unit cubes sort correctly
  // by (x+z, then layer). Faces flush against occupied neighbors are
  // culled; brick outlines are drawn on top-face boundary edges only.
  const key = (x, z, l) => ((l * 4096 + z) * 4096) + x;
  const owner = new Map(); // cell -> brick index (for boundary detection)
  visible.forEach((b, i) => {
    for (let dx = 0; dx < b.xlen; dx++)
      for (let dz = 0; dz < b.zlen; dz++)
        owner.set(key(b.x + dx, b.z + dz, b.layer), i);
  });

  const cells = [];
  visible.forEach((b, i) => {
    for (let dx = 0; dx < b.xlen; dx++) {
      for (let dz = 0; dz < b.zlen; dz++) {
        const x = b.x + dx, z = b.z + dz, L = b.layer;
        const rightHidden = owner.has(key(x + 1, z, L));
        const leftHidden = owner.has(key(x, z + 1, L));
        const topHidden = owner.has(key(x, z, L + 1));
        if (rightHidden && leftHidden && topHidden) continue;
        cells.push({ x, z, L, brick: i, rightHidden, leftHidden, topHidden });
      }
    }
  });
  cells.sort((a, b) => a.x + a.z - (b.x + b.z) || a.L - b.L);

  const pal = state.result.palette;
  const same = (c, dx, dz) => owner.get(key(c.x + dx, c.z + dz, c.L)) === c.brick;
  for (const c of cells) {
    const b = visible[c.brick];
    const rgb = hexToRgb(pal[b.color].hex);
    const dark = shade(rgb, 0.45);
    const { x, z, L } = c;
    if (!c.rightHidden)
      poly([P(x + 1, z, L + 1), P(x + 1, z + 1, L + 1), P(x + 1, z + 1, L), P(x + 1, z, L)],
        shade(rgb, 0.62), same(c, 1, 0) ? null : dark);
    if (!c.leftHidden)
      poly([P(x, z + 1, L + 1), P(x + 1, z + 1, L + 1), P(x + 1, z + 1, L), P(x, z + 1, L)],
        shade(rgb, 0.8), same(c, 0, 1) ? null : dark);
    if (!c.topHidden) {
      const A = P(x, z, L + 1), B = P(x + 1, z, L + 1),
            C = P(x + 1, z + 1, L + 1), Dd = P(x, z + 1, L + 1);
      poly([A, B, C, Dd], shade(rgb, 1.08), null);
      if (!same(c, 0, -1)) seg(A, B, dark);
      if (!same(c, 1, 0)) seg(B, C, dark);
      if (!same(c, 0, 1)) seg(C, Dd, dark);
      if (!same(c, -1, 0)) seg(Dd, A, dark);
      if (s >= 7) {
        const [cx, cy] = P(x + 0.5, z + 0.5, L + 1);
        ctx.beginPath();
        ctx.ellipse(cx, cy, s * 0.3, s * 0.15, 0, 0, Math.PI * 2);
        ctx.strokeStyle = shade(rgb, 0.75);
        ctx.lineWidth = 0.8;
        ctx.stroke();
      }
    }
  }
}

function renderPreview() {
  if (!state.result) return;
  if (is3D()) renderIso();
  else renderMosaicPreview();
}

/* ----------------------------------------------------------- instructions */

function renderInstructions() {
  if (!state.result) return;
  $("#inst-label").textContent = (is3D() ? "Layer " : "Row ") + (state.instLayer + 1) + " / " + totalLayers();
  if (is3D()) renderLayerTopdown();
  else renderMosaicRow();
}

function renderLayerTopdown() {
  const r = state.result;
  const { x: W, z: D } = r.grid_size;
  const L = state.instLayer;
  const avail = Math.min(880, $("#panel-instructions .canvas-wrap").clientWidth - 24 || 800);
  const cell = Math.max(8, Math.min(30, Math.floor(avail / W)));
  const ctx = setupCanvas($("#inst-canvas"), W * cell, D * cell);

  ctx.fillStyle = "#f7f3e9";
  ctx.fillRect(0, 0, W * cell, D * cell);

  // ghost layer below
  for (const b of r.bricks) {
    if (b.layer !== L - 1) continue;
    ctx.fillStyle = "#dedacd";
    ctx.fillRect(b.x * cell, b.z * cell, b.xlen * cell, b.zlen * cell);
  }
  // grid
  ctx.strokeStyle = "#e6e0d0";
  ctx.lineWidth = 1;
  for (let gx = 0; gx <= W; gx++) {
    ctx.beginPath(); ctx.moveTo(gx * cell + 0.5, 0); ctx.lineTo(gx * cell + 0.5, D * cell); ctx.stroke();
  }
  for (let gz = 0; gz <= D; gz++) {
    ctx.beginPath(); ctx.moveTo(0, gz * cell + 0.5); ctx.lineTo(W * cell, gz * cell + 0.5); ctx.stroke();
  }
  // bricks of this layer
  const counts = {};
  for (const b of r.bricks) {
    if (b.layer !== L) continue;
    const rgb = hexToRgb(r.palette[b.color].hex);
    ctx.fillStyle = shade(rgb, 1);
    ctx.fillRect(b.x * cell, b.z * cell, b.xlen * cell, b.zlen * cell);
    ctx.strokeStyle = shade(rgb, 0.5);
    ctx.lineWidth = 2;
    ctx.strokeRect(b.x * cell + 1, b.z * cell + 1, b.xlen * cell - 2, b.zlen * cell - 2);
    if (cell >= 10) {
      ctx.strokeStyle = shade(rgb, 0.72);
      ctx.lineWidth = 1.2;
      for (let dx = 0; dx < b.xlen; dx++) {
        for (let dz = 0; dz < b.zlen; dz++) {
          ctx.beginPath();
          ctx.arc((b.x + dx + 0.5) * cell, (b.z + dz + 0.5) * cell, cell * 0.28, 0, Math.PI * 2);
          ctx.stroke();
        }
      }
    }
    const key = b.color + "|" + b.part;
    counts[key] = (counts[key] || 0) + 1;
  }
  fillInstParts(counts);
}

function renderMosaicRow() {
  const r = state.result;
  const grid = r.grid;
  const rows = grid.length, cols = grid[0].length;
  const row = state.instLayer;
  const avail = Math.min(880, $("#panel-instructions .canvas-wrap").clientWidth - 24 || 800);
  const cell = Math.max(5, Math.min(22, Math.floor(avail / cols)));
  const ctx = setupCanvas($("#inst-canvas"), cols * cell, rows * cell);

  // whole mosaic, dimmed except current row
  for (let y = 0; y < rows; y++) {
    for (let x = 0; x < cols; x++) {
      const rgb = hexToRgb(r.palette[grid[y][x]].hex);
      ctx.globalAlpha = y === row ? 1 : 0.25;
      ctx.fillStyle = shade(rgb, 1);
      ctx.fillRect(x * cell, y * cell, cell, cell);
    }
  }
  ctx.globalAlpha = 1;

  // outline the placements of this row
  const counts = {};
  for (const p of r.placements) {
    if (p.row !== row) continue;
    const rgb = hexToRgb(r.palette[p.color].hex);
    ctx.strokeStyle = shade(rgb, 0.4);
    ctx.lineWidth = 2;
    ctx.strokeRect(p.col * cell + 1, p.row * cell + 1, p.length * cell - 2, cell - 2);
    const key = p.color + "|" + p.part;
    counts[key] = (counts[key] || 0) + 1;
  }
  // row marker
  ctx.strokeStyle = "#e3000b";
  ctx.lineWidth = 2;
  ctx.strokeRect(0.5, row * cell + 0.5, cols * cell - 1, cell - 1);

  fillInstParts(counts);
}

function fillInstParts(counts) {
  const r = state.result;
  const names = partNames();
  const items = Object.entries(counts)
    .map(([key, qty]) => {
      const [color, part] = key.split("|");
      return { color: +color, part, qty };
    })
    .sort((a, b) => b.qty - a.qty);
  $("#inst-parts-title").textContent =
    (is3D() ? "Pieces in this layer" : "Pieces in this row") +
    ` (${items.reduce((s, i) => s + i.qty, 0)})`;
  $("#inst-parts-list").innerHTML = items
    .map(
      (i) => `<li>
        <span class="swatch" style="background:${r.palette[i.color].hex}"></span>
        <span>${names[i.part] || i.part} · ${r.palette[i.color].name}</span>
        <span class="qty-badge">×${i.qty}</span>
      </li>`
    )
    .join("");
}

/* ----------------------------------------------------------------- parts */

function renderParts() {
  const r = state.result;
  const f = r.files;
  const dls = [
    [f.zip, "⬇️ Everything (ZIP)", true],
    [f.ldr, "model.ldr"],
    [f.bricklink_xml, "BrickLink XML"],
    [f.rebrickable_csv, "Rebrickable CSV"],
    [f.bom_csv, "Parts list CSV"],
  ];
  if (f.chart) dls.push([f.chart, "Build chart PNG"]);
  $("#downloads").innerHTML = dls
    .map(
      ([url, label, primary]) =>
        `<a class="dl${primary ? " primary" : ""}" href="${url}" download>${label}</a>`
    )
    .join("");

  $("#bom-totals").innerHTML = `
    <span>🧱 ${r.totals.pieces.toLocaleString()} pieces</span>
    <span>📦 ${r.totals.lots} lots</span>
    <span>💵 ~$${r.totals.est_price_usd.toLocaleString()}</span>
    <span>⚖️ ~${r.totals.est_weight_g.toLocaleString()} g</span>`;

  $("#bom-table tbody").innerHTML = r.bom
    .map(
      (row) => `<tr>
      <td><span class="color-cell"><span class="swatch" style="background:${row.color.hex}"></span>${row.color.name}</span></td>
      <td>${row.part_name}</td>
      <td>${row.part}</td>
      <td class="num">${row.qty.toLocaleString()}</td>
      <td class="num">$${row.est_price_usd.toFixed(2)}</td>
      <td><a href="${row.bricklink_url}" target="_blank" rel="noopener">Buy ↗</a></td>
    </tr>`
    )
    .join("");
}

window.addEventListener("resize", () => {
  if (state.result) {
    renderPreview();
    renderInstructions();
  }
});
