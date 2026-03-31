/* ===================================================================
   Stock Analysis — Web Viewer
   =================================================================== */

const DATA_DIR = "data";
let summaryData = [];
let groupsData = {};
let sortCol = null;
let sortAsc = true;

// Cache fetched ticker data so we don't re-download
const tickerCache = {};

// Plotly dark theme
const PLOTLY_LAYOUT = {
  paper_bgcolor: "#161b22",
  plot_bgcolor:  "#0d1117",
  font: { color: "#e6edf3", family: "-apple-system, sans-serif", size: 11 },
  margin: { t: 36, r: 12, b: 36, l: 48 },
  legend: { orientation: "h", y: -0.22, font: { size: 10 }, bgcolor: "rgba(0,0,0,0)" },
  xaxis: { gridcolor: "#21262d", linecolor: "#30363d" },
  yaxis: { gridcolor: "#21262d", linecolor: "#30363d", zeroline: false },
};

const C = {
  pe:     "#58a6ff",
  pb:     "#bc8cff",
  margin: "#3fb950",
  growth: "#f0883e",
  roic:   "#39d2c0",
};

// ─── Bootstrap ──────────────────────────────────────────────────────────

async function init() {
  try {
    const [meta, summary, groups] = await Promise.all([
      fetchJSON("meta.json"),
      fetchJSON("summary.json"),
      fetchJSON("groups.json"),
    ]);
    summaryData = summary;
    groupsData = groups;

    document.getElementById("lastUpdated").textContent =
      "Updated " + new Date(meta.last_updated).toLocaleDateString("en-GB", {
        day: "numeric", month: "short", year: "numeric",
        hour: "2-digit", minute: "2-digit"
      });

    populateGroupFilter();
    renderTable();
    bindEvents();
  } catch (e) {
    document.getElementById("tableBody").innerHTML =
      `<tr><td colspan="99" style="color:var(--red);padding:24px">
       Failed to load data. Run the analysis first to generate JSON files.<br>
       <small>${e.message}</small></td></tr>`;
  }
}

async function fetchJSON(file) {
  const r = await fetch(`${DATA_DIR}/${file}`);
  if (!r.ok) throw new Error(`${file}: ${r.status}`);
  return r.json();
}

async function fetchTicker(ticker) {
  if (tickerCache[ticker]) return tickerCache[ticker];
  try {
    const data = await fetchJSON(`${ticker}.json`);
    tickerCache[ticker] = data;
    return data;
  } catch { return null; }
}

// ─── Dashboard table ────────────────────────────────────────────────────

const TABLE_COLS = [
  { key: "Ticker",              label: "Ticker",     fmt: "str" },
  { key: "Price",               label: "Price",      fmt: "price" },
  { key: "P/E",                 label: "P/E",        fmt: "1f" },
  { key: "P/B",                 label: "P/B",        fmt: "2f" },
  { key: "ROIC",                label: "ROIC",       fmt: "pct" },
  { key: "ROE",                 label: "ROE",        fmt: "pct" },
  { key: "Operating Margin",    label: "Op Margin",  fmt: "pct" },
  { key: "Net Margin",          label: "Net Margin", fmt: "pct" },
  { key: "Growth Rate (g)",     label: "g (2Y)",     fmt: "pct" },
  { key: "YoY Revenue Growth",  label: "YoY Rev",    fmt: "pct" },
  { key: "FCF Yield",           label: "FCF Yield",  fmt: "pct" },
  { key: "Debt/Equity",         label: "D/E",        fmt: "2f" },
  { key: "Price / BG Intrinsic",label: "P/BG",       fmt: "2f" },
  { key: "Price / (BG + BV)",   label: "P/(BG+BV)",  fmt: "2f" },
];

function renderTable() {
  const search = (document.getElementById("search").value || "").toUpperCase();
  const group  = document.getElementById("groupFilter").value;

  let rows = summaryData;
  if (search) rows = rows.filter(r => (r.Ticker || "").toUpperCase().includes(search));
  if (group)  rows = rows.filter(r => (r.Groups || []).some(g => g === group));

  if (sortCol !== null) {
    rows = [...rows].sort((a, b) => {
      let va = a[sortCol], vb = b[sortCol];
      if (va == null) return 1;
      if (vb == null) return -1;
      if (typeof va === "string") return sortAsc ? va.localeCompare(vb) : vb.localeCompare(va);
      return sortAsc ? va - vb : vb - va;
    });
  }

  document.getElementById("tableHead").innerHTML = "<tr>" +
    TABLE_COLS.map(c => {
      let cls = sortCol === c.key ? (sortAsc ? "sorted-asc" : "sorted-desc") : "";
      return `<th class="${cls}" data-col="${c.key}">${c.label}</th>`;
    }).join("") + "</tr>";

  document.getElementById("tableBody").innerHTML = rows.map(row =>
    "<tr>" + TABLE_COLS.map(c => {
      const v = row[c.key];
      if (c.key === "Ticker")
        return `<td onclick="showDetail('${v}')">${v}</td>`;
      return `<td class="${numClass(v, c)}">${fmtVal(v, c.fmt)}</td>`;
    }).join("") + "</tr>"
  ).join("");
}

function numClass(v, col) {
  if (v == null) return "";
  if (col.fmt === "pct") return v > 0 ? "positive" : v < 0 ? "negative" : "";
  if (col.key === "P/E") return v < 15 ? "positive" : v > 30 ? "negative" : "";
  if (col.key.startsWith("Price /")) return v < 1 ? "positive" : v > 1.5 ? "negative" : "";
  return "";
}

function fmtVal(v, fmt) {
  if (v == null) return "\u2014";
  if (fmt === "str")   return v;
  if (fmt === "price") return v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (fmt === "1f")    return v.toFixed(1);
  if (fmt === "2f")    return v.toFixed(2);
  if (fmt === "pct")   return (v * 100).toFixed(1) + "%";
  return v;
}

// ─── Detail view — comparison grid ──────────────────────────────────────

async function showDetail(ticker) {
  document.getElementById("dashboard").style.display = "none";
  document.getElementById("toolbar").style.display   = "none";
  document.getElementById("detail").style.display     = "block";

  const snap = summaryData.find(r => r.Ticker === ticker) || {};
  document.getElementById("detailTicker").textContent = ticker;
  document.getElementById("detailPrice").textContent =
    snap.Price != null
      ? (snap.Currency || "") + " " + snap.Price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
      : "";
  document.getElementById("detailSource").textContent = snap.Source || "";

  // KPIs
  const kpis = [
    { label: "P/E",       val: snap["P/E"],                fmt: "1f" },
    { label: "P/B",       val: snap["P/B"],                fmt: "2f" },
    { label: "ROIC",      val: snap["ROIC"],               fmt: "pct" },
    { label: "ROE",       val: snap["ROE"],                fmt: "pct" },
    { label: "Op Margin", val: snap["Operating Margin"],   fmt: "pct" },
    { label: "Net Margin",val: snap["Net Margin"],         fmt: "pct" },
    { label: "FCF Yield", val: snap["FCF Yield"],          fmt: "pct" },
    { label: "D/E",       val: snap["Debt/Equity"],        fmt: "2f" },
    { label: "g (2Y)",    val: snap["Growth Rate (g)"],    fmt: "pct" },
    { label: "P / BG",    val: snap["Price / BG Intrinsic"], fmt: "2f" },
  ];
  document.getElementById("kpiRow").innerHTML = kpis.map(k =>
    `<div class="kpi"><div class="label">${k.label}</div><div class="value">${fmtVal(k.val, k.fmt)}</div></div>`
  ).join("");

  // Find all competitors (stocks in the same group)
  const groups = snap.Groups || [];
  const peerSet = new Set();
  peerSet.add(ticker); // always include self first
  for (const g of groups) {
    if (groupsData[g]) {
      for (const t of groupsData[g]) peerSet.add(t);
    }
  }
  const peers = Array.from(peerSet);

  // Build the chart grid — one chart per peer
  // Look up full company names from summary data
  const nameMap = {};
  for (const row of summaryData) {
    if (row.Ticker) nameMap[row.Ticker] = row.Name || row.Ticker;
  }

  const grid = document.getElementById("chartGrid");
  grid.innerHTML = peers.map(t => {
    const name = nameMap[t] || t;
    return `<div class="chart-card ${t === ticker ? 'highlighted' : ''}">
       <h3 class="chart-ticker">${t}</h3>
       <div class="chart-name">${name}</div>
       <div class="chart-plot" id="chart-${CSS.escape(t)}"></div>
     </div>`;
  }).join("");

  // Fetch all peer data in parallel
  const fetches = peers.map(t => fetchTicker(t));
  const results = await Promise.all(fetches);

  // Compute shared axis ranges across ALL peers (full range, no clipping)
  const allLeft = [], allRight = [];
  for (const ts of results) {
    if (!ts) continue;
    for (const r of ts) {
      if (r["P/E"] != null)                allLeft.push(r["P/E"]);
      if (r["P/B"] != null)                allLeft.push(r["P/B"]);
      if (r["Net Margin"] != null)         allRight.push(r["Net Margin"] * 100);
      if (r["YoY Revenue Growth"] != null) allRight.push(r["YoY Revenue Growth"] * 100);
      if (r["ROIC"] != null)              allRight.push(r["ROIC"] * 100);
    }
  }

  const sharedAxes = {
    leftMin:  0,
    leftMax:  40,
    rightMin: allRight.length ? Math.min(0, Math.min(...allRight)) : 0,
    rightMax: allRight.length ? Math.max(...allRight) * 1.05       : 100,
  };

  // Render each chart with identical axes
  for (let i = 0; i < peers.length; i++) {
    const t  = peers[i];
    const ts = results[i];
    const el = document.getElementById(`chart-${CSS.escape(t)}`);
    if (!ts || !el) {
      if (el) el.innerHTML += `<p style="color:var(--text-muted)">No data</p>`;
      continue;
    }
    renderComparisonChart(el.id, t, ts, sharedAxes);
  }
}


function renderComparisonChart(containerId, ticker, ts, axes) {
  const dates = ts.map(r => r.Date);

  const traces = [
    {
      x: dates, y: ts.map(r => r["P/E"]),
      name: "P/E", yaxis: "y",
      line: { color: C.pe, width: 2 },
    },
    {
      x: dates, y: ts.map(r => r["P/B"]),
      name: "P/B", yaxis: "y",
      line: { color: C.pb, width: 2 },
    },
    {
      x: dates, y: ts.map(r => r["Net Margin"] != null ? r["Net Margin"] * 100 : null),
      name: "Net Margin", yaxis: "y2",
      line: { color: C.margin, width: 2 },
    },
    {
      x: dates, y: ts.map(r => r["YoY Revenue Growth"] != null ? r["YoY Revenue Growth"] * 100 : null),
      name: "Rev Growth", yaxis: "y2",
      line: { color: C.growth, width: 2 },
    },
    {
      x: dates, y: ts.map(r => r["ROIC"] != null ? r["ROIC"] * 100 : null),
      name: "ROIC", yaxis: "y2",
      line: { color: C.roic, width: 2 },
    },
  ];

  const layout = {
    ...PLOTLY_LAYOUT,
    yaxis: {
      ...PLOTLY_LAYOUT.yaxis,
      title: { text: "P/E · P/B", font: { size: 10 } },
      side: "left",
      range: [axes.leftMin, axes.leftMax],
    },
    yaxis2: {
      ...PLOTLY_LAYOUT.yaxis,
      title: { text: "Margin · Growth %", font: { size: 10 } },
      side: "right",
      overlaying: "y",
      ticksuffix: "%",
      range: [axes.rightMin, axes.rightMax],
    },
    legend: { ...PLOTLY_LAYOUT.legend, y: -0.28 },
    margin: { t: 8, r: 48, b: 50, l: 48 },
  };

  Plotly.newPlot(containerId, traces, layout, { responsive: true, displayModeBar: false });
}

function showDashboard() {
  document.getElementById("detail").style.display     = "none";
  document.getElementById("toolbar").style.display     = "flex";
  document.getElementById("dashboard").style.display   = "block";
}

// ─── Events ─────────────────────────────────────────────────────────────

function bindEvents() {
  document.getElementById("search").addEventListener("input", renderTable);
  document.getElementById("groupFilter").addEventListener("change", renderTable);

  document.getElementById("tableHead").addEventListener("click", e => {
    const th = e.target.closest("th");
    if (!th) return;
    const col = th.dataset.col;
    if (sortCol === col) sortAsc = !sortAsc;
    else { sortCol = col; sortAsc = true; }
    renderTable();
  });
}

function populateGroupFilter() {
  const sel = document.getElementById("groupFilter");
  Object.keys(groupsData).forEach(g => {
    const opt = document.createElement("option");
    opt.value = g; opt.textContent = g;
    sel.appendChild(opt);
  });
}

// ─── Go ─────────────────────────────────────────────────────────────────
init();
