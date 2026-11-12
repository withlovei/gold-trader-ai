function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}
function money(value) {
  return Number(value).toLocaleString(LOCALE, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
let marketClosed = false;
let closedLabel = "";

function paintClock() {
  const label = document.getElementById("next-label");
  if (marketClosed) {
    if (label) label.textContent = "Mở phiên";
    document.getElementById("next-clock").textContent = closedLabel || "Thứ Hai";
    return;
  }
  if (label) label.textContent = "Quyết định M15 sau";
  const whole = Math.max(0, secondsLeft);
  const minutes = String(Math.floor(whole / 60)).padStart(2, "0");
  const seconds = String(whole % 60).padStart(2, "0");
  document.getElementById("next-clock").textContent = minutes + ":" + seconds;
}
function applyTick(price) {
  if (!latestChart || !latestChart.bars || !latestChart.bars.length || !Number.isFinite(price)) return;
  const bar = latestChart.bars[latestChart.bars.length - 1];
  const high = Math.max(bar.high, price);
  const low = Math.min(bar.low, price);
  if (bar.close === price && bar.high === high && bar.low === low) {
    moveCurrentPrice(price);
    return;
  }
  bar.high = high;
  bar.low = low;
  bar.close = price;
  latestChart.quote = Object.assign({}, latestChart.quote, { bid: price });
  drawChart(latestChart);
}

function moveCurrentPrice(price) {
  if (!latestChart || !latestChart.priceScale || !Number.isFinite(price)) return;
  const scale = latestChart.priceScale;
  const span = scale.max - scale.min || 1;
  const y = scale.top + ((scale.max - price) / span) * (scale.bottom - scale.top - 8);
  if (y < scale.top || y > scale.bottom) {
    latestChart.quote = Object.assign({}, latestChart.quote, { bid: price });
    drawChart(latestChart);
    return;
  }
  const line = document.getElementById("current-price-line");
  const tag = document.getElementById("current-price-tag");
  const label = document.getElementById("current-price-label");
  if (!line || !tag || !label) return;
  line.setAttribute("y1", y);
  line.setAttribute("y2", y);
  tag.setAttribute("y", y - 8);
  label.setAttribute("y", y + 4);
  label.textContent = formatPrice(price);
}

const AGENT_COLORS = { "trend-M15": "#e3b341", "pullback-M15": "#38bdf8", "trend-M30": "#f97316" };
const EXTRA_COLORS = ["#a78bfa", "#34d399", "#f472b6", "#22d3ee", "#facc15", "#fb923c", "#60a5fa", "#4ade80", "#e879f9", "#2dd4bf", "#fda4af", "#c084fc"];
function agentColor(id) {
  if (AGENT_COLORS[id]) return AGENT_COLORS[id];
  let h = 0;
  for (const c of String(id || "")) h = (h * 31 + c.charCodeAt(0)) % 9973;
  return EXTRA_COLORS[h % EXTRA_COLORS.length];
}
function modeButton(agent) {
  const real = agent.real !== false;
  return '<button type="button" data-agent-mode="' + escapeHtml(agent.id || "") + '" data-real="' + (real ? "0" : "1") + '" data-alias="' + escapeHtml(agent.alias || agent.id || "") + '" class="shrink-0 rounded-md border px-2 py-0.5 text-[11px] font-semibold ' +
    (real ? "border-sky-400/40 text-sky-200 hover:bg-sky-400/10" : "border-emerald-400/50 text-emerald-200 hover:bg-emerald-400/10") + '">' + (real ? "↓ Xuống nghiên cứu" : "↑ Lên tiền thật") + "</button>";
}
function paintSwitchboard(crew) {
  const list = document.getElementById("agent-board-list");
  if (!list || !crew) return;
  const staff = crew.agents || [];
  const lab = (crew.lab || []).filter((agent) => agent.magic);
  document.getElementById("agent-board-count").textContent = staff.length + " tiền thật · " + lab.length + " nghiên cứu";
  list.innerHTML = staff.concat(lab).map((agent) => {
    const real = agent.real !== false;
    return '<div class="flex items-center justify-between gap-2 rounded-lg border border-line px-2 py-1.5" style="border-left:3px solid ' + agentColor(agent.id) + '">' +
      '<div class="min-w-0"><p class="truncate text-xs font-semibold text-zinc-200">' + escapeHtml(agent.alias || agent.id) + '</p><p class="truncate text-[11px] text-zinc-500">' + escapeHtml(agent.name || "") + " · " + escapeHtml(agent.timeframe || "") + "</p></div>" +
      '<div class="flex items-center gap-1.5"><span class="badge whitespace-nowrap ' + (real ? "badge-ok" : "badge-off") + '">' + (real ? "Tiền thật" : "Nghiên cứu") + "</span>" + modeButton(agent) + "</div></div>";
  }).join("");
}
