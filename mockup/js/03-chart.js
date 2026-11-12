function toast(message) {
  const node = document.getElementById("toast");
  node.textContent = message;
  node.classList.remove("hidden");
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => node.classList.add("hidden"), 2400);
}

function lineChart(id, values, color) {
  const svg = document.getElementById(id);
  const width = 640;
  const height = 180;
  const min = Math.min.apply(null, values);
  const max = Math.max.apply(null, values);
  const coords = values
    .map((value, index) => {
      const x = (index / (values.length - 1)) * (width - 16) + 8;
      const y = 12 + ((max - value) / (max - min || 1)) * (height - 28);
      return x.toFixed(1) + "," + y.toFixed(1);
    })
    .join(" ");
  svg.innerHTML = '<polyline fill="none" stroke="' + color + '" stroke-width="2" points="' + coords + '" />';
}

const chartLayers = {
  ema9: false,
  ema20: true,
  ema50: false,
  ema200: false,
  bollinger: false,
  swings: true,
  levels: false,
  plan: false,
  orders: false,
  rsi: false,
};
let latestChart = null;

function loadChartLayers() {
  try {
    const saved = JSON.parse(window.localStorage.getItem("goldtrader-chart-layers") || "{}");
    Object.keys(chartLayers).forEach((key) => {
      if (typeof saved[key] === "boolean") chartLayers[key] = saved[key];
    });
  } catch (_error) {
    return;
  }
}

function paintLayerButtons() {
  document.querySelectorAll(".layer-btn").forEach((button) => {
    const on = chartLayers[button.dataset.layer];
    button.setAttribute("aria-pressed", on ? "true" : "false");
    button.classList.toggle("bg-white/10", on);
    button.classList.toggle("opacity-40", !on);
  });
}

function formatPrice(value) {
  return Number(value).toFixed(2);
}

function formatBarTime(unix, timeframe) {
  const date = new Date(unix * 1000);
  const hours = String(date.getUTCHours()).padStart(2, "0");
  const minutes = String(date.getUTCMinutes()).padStart(2, "0");
  const day = String(date.getUTCDate()).padStart(2, "0");
  const month = String(date.getUTCMonth() + 1).padStart(2, "0");
  if (timeframe === "D1") return day + "/" + month;
  if (timeframe === "H1" || timeframe === "H4") return day + "/" + month + " " + hours + "h";
  return hours + ":" + minutes;
}

function verticalGrid(bars, times, timeframe, slot, bottom, plotLeft) {
  const step = Math.max(1, Math.floor(bars.length / 7));
  let markup = "";
  for (let index = step; index < bars.length - 1; index += step) {
    const x = (plotLeft + index * slot + slot / 2).toFixed(1);
    markup += '<line x1="' + x + '" y1="16" x2="' + x + '" y2="' + bottom + '" stroke="#3f3f46" stroke-width="1" stroke-dasharray="2 4" />';
    if (times && times[index]) {
      markup += '<text x="' + x + '" y="' + (bottom + 12) + '" fill="#71717a" font-size="9" text-anchor="middle" font-family="IBM Plex Mono, monospace">' + formatBarTime(times[index], timeframe) + "</text>";
    }
  }
  const lastX = (plotLeft + (bars.length - 1) * slot + slot / 2).toFixed(1);
  markup += '<line x1="' + lastX + '" y1="16" x2="' + lastX + '" y2="' + bottom + '" stroke="#e4c27a" stroke-width="1" />';
  if (times && times[bars.length - 1]) {
    markup += '<text x="' + lastX + '" y="' + (bottom + 12) + '" fill="#e4c27a" font-size="9" text-anchor="middle" font-family="IBM Plex Mono, monospace">' + formatBarTime(times[bars.length - 1], timeframe) + "</text>";
  }
  return markup;
}

function priceAxis(low, high, scaleY, plotLeft, plotRight, bottom) {
  const steps = 4;
  let markup = '<line x1="' + plotLeft + '" y1="14" x2="' + plotLeft + '" y2="' + bottom + '" stroke="#3f3f46" stroke-width="1" />';
  for (let index = 0; index <= steps; index += 1) {
    const price = high - ((high - low) * index) / steps;
    const y = scaleY(price);
    if (y < 12 || y > bottom - 2) continue;
    const yText = y.toFixed(1);
    markup += '<line x1="' + plotLeft + '" y1="' + yText + '" x2="' + plotRight + '" y2="' + yText + '" stroke="#27272a" stroke-width="1" />';
    markup += '<text x="' + (plotLeft - 6) + '" y="' + (y + 3).toFixed(1) + '" fill="#a1a1aa" font-size="10" text-anchor="end" font-family="IBM Plex Mono, monospace">' + formatPrice(price) + "</text>";
  }
  return markup;
}

function currentPriceMarkup(price, scaleY, plotRight, plotLeft) {
  const y = scaleY(price).toFixed(1);
  return (
    '<line id="current-price-line" x1="' + plotLeft + '" y1="' + y + '" x2="' + plotRight + '" y2="' + y + '" stroke="#f5d78e" stroke-width="1.2" />' +
    '<rect id="current-price-tag" x="' + (plotRight + 4) + '" y="' + (Number(y) - 8) + '" width="68" height="16" rx="2" fill="#e4c27a" />' +
    '<text id="current-price-label" x="' + (plotRight + 8) + '" y="' + (Number(y) + 4) + '" fill="#0b0c0f" font-size="10" font-family="IBM Plex Mono, monospace">' + formatPrice(price) + "</text>"
  );
}

function swingMarks(swings, scaleY, slot, plotLeft) {
  return swings
    .map((point) => {
      const x = plotLeft + point.index * slot + slot / 2;
      const y = scaleY(point.price);
      if (point.kind === "high") {
        const tip = y - 4;
        return '<polygon points="' + (x - 4.5) + "," + (tip - 8) + " " + (x + 4.5) + "," + (tip - 8) + " " + x + "," + tip + '" fill="#fb7185" />';
      }
      const tip = y + 4;
      return '<polygon points="' + (x - 4.5) + "," + (tip + 8) + " " + (x + 4.5) + "," + (tip + 8) + " " + x + "," + tip + '" fill="#6ee7b7" />';
    })
    .join("");
}

function polyline(values, scaleY, slot, color, width, plotLeft) {
  const points = [];
  values.forEach((value, index) => {
    if (value === null || value === undefined) return;
    points.push((plotLeft + index * slot + slot / 2).toFixed(1) + "," + scaleY(value).toFixed(1));
  });
  if (points.length < 2) return "";
  return '<polyline fill="none" stroke="' + color + '" stroke-width="' + width + '" points="' + points.join(" ") + '" />';
}

function placeLevels(levels, scaleY, bottom, plotRight, plotLeft) {
  const placed = levels
    .map((level) => ({ ...level, y: scaleY(level.price) }))
    .filter((level) => level.y >= 8 && level.y <= bottom)
    .sort((left, right) => left.y - right.y);
  placed.forEach((level, index) => {
    let textY = level.y;
    if (index > 0 && textY - placed[index - 1].textY < 12) textY = placed[index - 1].textY + 12;
    level.textY = textY;
  });
  return placed
    .map((level) => {
      return (
        '<line x1="' + plotLeft + '" y1="' + level.y + '" x2="' + plotRight + '" y2="' + level.y + '" stroke="' + level.color + '" stroke-width="1" stroke-dasharray="' + level.dash + '" />' +
        '<text x="' + (plotRight + 6) + '" y="' + (level.textY + 3) + '" fill="' + level.color + '" font-size="10" font-family="IBM Plex Mono, monospace">' + level.label + " " + formatPrice(level.price) + "</text>"
      );
    })
    .join("");
}

function drawChart(data) {
  latestChart = data;
  const svg = document.getElementById("candle-chart");
  const bars = data.bars;
  const width = Math.max(360, Math.round(svg.clientWidth) || 760);
  const height = Math.max(160, Math.round(svg.clientHeight) || 176);
  const plotLeft = 64;
  const plotRight = width - 96;
  const priceBottom = height - (chartLayers.rsi ? 108 : 22);
  const currentPrice = data.quote && data.quote.bid ? Number(data.quote.bid) : bars[bars.length - 1].close;
  const prices = bars.flatMap((bar) => [bar.high, bar.low]);
  prices.push(currentPrice);
  const pushSeries = (key) => {
    data[key].forEach((value) => {
      if (value !== null) prices.push(value);
    });
  };
  if (chartLayers.ema9) pushSeries("ema9");
  if (chartLayers.ema20) pushSeries("ema20");
  if (chartLayers.ema50) pushSeries("ema50");
  if (chartLayers.ema200) pushSeries("ema200");
  if (chartLayers.bollinger) {
    pushSeries("bollingerUpper");
    pushSeries("bollingerLower");
  }
  if (chartLayers.levels) prices.push(data.support, data.resistance);
  if (chartLayers.plan && data.strategy.side !== "wait") {
    prices.push(data.strategy.entry, data.strategy.stop);
    if (data.strategy.takeProfit) prices.push(data.strategy.takeProfit);
  }
  if (chartLayers.orders) {
    data.orders.forEach((order) => {
      prices.push(order.entry);
      if (order.stop) prices.push(order.stop);
      if (order.takeProfit) prices.push(order.takeProfit);
    });
  }
  const min = Math.min.apply(null, prices);
  const max = Math.max.apply(null, prices);
  const pad = (max - min) * 0.08 || 1;
  const scaleY = (value) => 14 + ((max + pad - value) / (max - min + pad * 2)) * (priceBottom - 22);
  const slot = Math.max(4, (plotRight - plotLeft) / bars.length);
  const axisLow = min - pad;
  const axisHigh = max + pad;
  let markup = priceAxis(axisLow, axisHigh, scaleY, plotLeft, plotRight, priceBottom);
  markup += verticalGrid(bars, data.times, data.timeframe, slot, priceBottom, plotLeft);
  if (chartLayers.bollinger) {
    markup += polyline(data.bollingerUpper, scaleY, slot, "#52525b", 1, plotLeft);
    markup += polyline(data.bollingerLower, scaleY, slot, "#52525b", 1, plotLeft);
    markup += polyline(data.bollingerMid, scaleY, slot, "#3f3f46", 1, plotLeft);
  }
  bars.forEach((bar, index) => {
    const x = plotLeft + index * slot + slot / 2;
    const color = bar.close >= bar.open ? "#6ee7b7" : "#fb7185";
    markup += '<line x1="' + x + '" y1="' + scaleY(bar.high) + '" x2="' + x + '" y2="' + scaleY(bar.low) + '" stroke="' + color + '" stroke-width="1" />';
    const bodyTop = scaleY(Math.max(bar.open, bar.close));
    const bodyHeight = Math.max(1.2, Math.abs(scaleY(bar.open) - scaleY(bar.close)));
    markup += '<rect x="' + (x - Math.max(1, slot * 0.28)) + '" y="' + bodyTop + '" width="' + Math.max(1.4, slot * 0.56) + '" height="' + bodyHeight + '" fill="' + color + '" />';
  });
  if (chartLayers.swings && Array.isArray(data.swings)) markup += swingMarks(data.swings, scaleY, slot, plotLeft);
  if (chartLayers.ema200) markup += polyline(data.ema200, scaleY, slot, "#c4b5fd", 1.2, plotLeft);
  if (chartLayers.ema50) markup += polyline(data.ema50, scaleY, slot, "#7dd3fc", 1.2, plotLeft);
  if (chartLayers.ema20) markup += polyline(data.ema20, scaleY, slot, "#e4c27a", 1.6, plotLeft);
  if (chartLayers.ema9) markup += polyline(data.ema9, scaleY, slot, "#e4e4e7", 1, plotLeft);
  const levels = [];
  if (chartLayers.levels) {
    levels.push(
      { price: data.support, color: "#a1a1aa", label: "Hỗ trợ", dash: "4 4" },
      { price: data.resistance, color: "#a1a1aa", label: "Kháng cự", dash: "4 4" }
    );
  }
  if (chartLayers.plan && data.strategy.side !== "wait") {
    const sideWord = data.strategy.side === "buy" ? "Mua" : "Bán";
    const entryColor = data.strategy.side === "buy" ? "#6ee7b7" : "#fb7185";
    levels.push(
      { price: data.strategy.entry, color: entryColor, label: sideWord + " vào", dash: "2 3" },
      { price: data.strategy.stop, color: "#fb7185", label: sideWord + " cắt lỗ", dash: "2 3" }
    );
    if (data.strategy.takeProfit) {
      levels.push({ price: data.strategy.takeProfit, color: "#86efac", label: sideWord + " chốt", dash: "2 3" });
    }
  }
  if (chartLayers.orders) {
    data.orders.forEach((order) => {
      levels.push({ price: order.entry, color: "#f5d78e", label: order.label, dash: "0" });
    });
  }
  markup += placeLevels(levels, scaleY, priceBottom, plotRight, plotLeft);
  markup += currentPriceMarkup(currentPrice, scaleY, plotRight, plotLeft);
  data.priceScale = { min: min - pad, max: max + pad, top: 14, bottom: priceBottom };
  if (chartLayers.plan && data.strategy.side !== "wait") {
    const entryY = scaleY(data.strategy.entry);
    const entryColor = data.strategy.side === "buy" ? "#6ee7b7" : "#fb7185";
    markup += '<polygon points="' + (plotRight - 12) + "," + (entryY - 5) + " " + (plotRight - 2) + "," + entryY + " " + (plotRight - 12) + "," + (entryY + 5) + '" fill="' + entryColor + '" />';
  }
  if (chartLayers.rsi) {
    const rsiTop = priceBottom + 28;
    const rsiHeight = 72;
    const scaleRsi = (value) => rsiTop + ((100 - value) / 100) * rsiHeight;
    markup += '<line x1="' + plotLeft + '" y1="' + scaleRsi(70) + '" x2="' + plotRight + '" y2="' + scaleRsi(70) + '" stroke="#3f3f46" stroke-dasharray="3 3" />';
    markup += '<line x1="' + plotLeft + '" y1="' + scaleRsi(30) + '" x2="' + plotRight + '" y2="' + scaleRsi(30) + '" stroke="#3f3f46" stroke-dasharray="3 3" />';
    markup += '<text x="' + (plotRight + 6) + '" y="' + (scaleRsi(70) + 3) + '" fill="#71717a" font-size="10">RSI 70</text>';
    markup += '<text x="' + (plotRight + 6) + '" y="' + (scaleRsi(30) + 3) + '" fill="#71717a" font-size="10">RSI 30</text>';
    markup += polyline(data.rsi, scaleRsi, slot, "#e4c27a", 1.4, plotLeft);
  }
  svg.setAttribute("viewBox", "0 0 " + width + " " + height);
  svg.innerHTML = markup;
  const strategy = data.strategy;
  const planButton = document.querySelector('[data-layer="plan"]');
  if (strategy.side === "buy") {
    planButton.textContent = "Kế hoạch Mua";
  } else if (strategy.side === "sell") {
    planButton.textContent = "Kế hoạch Bán";
  } else {
    planButton.textContent = "Chưa có kế hoạch";
  }
  const planLead = strategy.side === "buy"
    ? "Kế hoạch MUA. Chưa phải lệnh đang mở."
    : strategy.side === "sell"
      ? "Kế hoạch BÁN. Chưa phải lệnh đang mở."
      : "Chưa có kế hoạch mua hoặc bán, nên không vẽ vào, cắt lỗ, chốt lời.";
  const stateLabel = strategy.confirmed ? "Nến đã xác nhận." : "Nến chưa xác nhận, chưa gửi lệnh.";
  const planPrices = strategy.side === "wait"
    ? ""
    : strategy.takeProfit
      ? " Vào " + formatPrice(strategy.entry) + ", cắt lỗ " + formatPrice(strategy.stop) + ", chốt lời " + formatPrice(strategy.takeProfit) + "."
      : " Vào " + formatPrice(strategy.entry) + ", cắt lỗ " + formatPrice(strategy.stop) + ", thoát khi cắt EMA 50.";
  const strategyNode = document.getElementById("chart-strategy");
  strategyNode.textContent =
    planLead + " Chiến lược " + strategy.name + ". " + stateLabel + " " + strategy.reason +
    " Hỗ trợ " + formatPrice(data.support) + ", kháng cự " + formatPrice(data.resistance) + "." + planPrices;
  strategyNode.title = strategyNode.textContent;
  renderStrategies(strategy, data);
  document.getElementById("chart-caption").textContent =
    data.symbol + " · " + data.timeframe + " · hỗ trợ " + formatPrice(data.support) + " · kháng cự " + formatPrice(data.resistance) +
    " · " + (data.source === "mt5" ? "nến MetaTrader" : "nến mẫu") + " · RSI " + data.rsiNow + " · ATR " + data.atr;
  if (data.quote) {
    document.getElementById("quote-price").innerHTML =
      '<span class="text-emerald-300">' + formatPrice(data.quote.bid) + '</span><span class="text-zinc-600"> / </span><span class="text-rose-300">' + formatPrice(data.quote.ask) + "</span>";
  }
  if (data.source === "mt5") renderLiveOrders(data);
}

function renderLiveOrders(data) {
  const body = document.getElementById("position-rows");
  const price = data.quote ? data.quote.bid : data.bars[data.bars.length - 1].close;
  if (!data.orders.length) {
    body.innerHTML = '<tr><td class="px-3 py-3 text-zinc-500" colspan="10">Không có lệnh đang mở trên ' + data.symbol + ".</td></tr>";
    document.getElementById("pane-note").textContent = "Không có lệnh mở · đường trên biểu đồ là kế hoạch của chiến lược";
    return;
  }
  body.innerHTML = data.orders
    .map((order) => {
      const side = order.side === "buy" ? "Mua" : "Bán";
      const sideClass = order.side === "buy" ? "text-emerald-300" : "text-rose-300";
      const profit = order.side === "buy" ? price - order.entry : order.entry - price;
      return (
        "<tr><td class=\"px-3 py-2 font-medium text-gold\">" + escapeHtml(AGENT_BY_MAGIC[order.magic] || (order.magic ? "Mã sổ " + order.magic : "Lệnh tay")) + "</td>" +
        "<td class=\"px-3 py-2 " + sideClass + "\">" + side + "</td>" +
        "<td class=\"px-3 py-2 font-mono\">" + order.volume + "</td>" +
        "<td class=\"px-3 py-2 font-mono\">" + formatPrice(order.entry) + "</td>" +
        "<td class=\"px-3 py-2 font-mono\">" + formatPrice(price) + "</td>" +
        "<td class=\"px-3 py-2 font-mono\">" + (order.stop ? formatPrice(order.stop) : "—") + "</td>" +
        "<td class=\"px-3 py-2 font-mono\">" + (order.takeProfit ? formatPrice(order.takeProfit) : "—") + "</td>" +
        "<td class=\"px-3 py-2 font-mono " + tone(order.profit !== undefined ? order.profit : profit) + "\">" + (order.profit !== undefined ? signed(order.profit) + " $" : profit.toFixed(2)) + "</td>" +
        "<td class=\"px-3 py-2 font-mono text-zinc-400\">" + (order.ticket || "") + "</td>" +
        "<td class=\"px-3 py-2 text-zinc-500\">Chỉ xem</td></tr>"
      );
    })
    .join("");
  document.getElementById("pane-note").textContent = data.orders.length + " lệnh đang mở · đường vàng trên biểu đồ là giá vào";
}

let activeTimeframe = "M15";
let chartToken = 0;
let chartBusy = false;

async function loadChart(timeframe, quiet) {
  if (timeframe) activeTimeframe = timeframe;
  if (quiet && chartBusy) return;
  const token = ++chartToken;
  const requested = activeTimeframe;
  const caption = document.getElementById("chart-caption");
  if (!quiet) caption.textContent = "Đang tải nến " + requested + "...";
  if (quiet) chartBusy = true;
  try {
    const response = await fetch(apiBase + "/api/chart?timeframe=" + encodeURIComponent(requested));
    if (!response.ok) throw new Error("chart");
    const data = await response.json();
    if (token !== chartToken) return;
    drawChart(data);
  } catch (_error) {
    if (quiet || token !== chartToken) return;
    caption.textContent = "Không tải được biểu đồ.";
    document.getElementById("chart-strategy").textContent = "Server biểu đồ chưa trả dữ liệu.";
  } finally {
    if (quiet) chartBusy = false;
  }
}

navButtons.forEach((button) =>
  button.addEventListener("click", () => {
    showScreen(button.dataset.nav);
    history.replaceState(null, "", "#" + button.dataset.nav);
  }),
);
modeButtons.forEach((button) => {
  button.addEventListener("click", () => {
    if (button.disabled) return;
    modeButtons.forEach((item) => {
      const active = item === button;
      item.classList.toggle("bg-gold/15", active);
      item.classList.toggle("text-gold", active);
      item.classList.toggle("text-zinc-400", !active && !item.disabled);
    });
    document.getElementById("mode-note").textContent = notes[button.dataset.mode];
    document.getElementById("mode-pill").textContent = pills[button.dataset.mode];
    fetch(apiBase + "/api/mode", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: button.dataset.mode }),
    }).catch(() => undefined);
  });
});
document.querySelectorAll(".tf-btn").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".tf-btn").forEach((item) => {
      const active = item === button;
      item.classList.toggle("bg-gold/15", active);
      item.classList.toggle("text-gold", active);
      item.classList.toggle("text-zinc-400", !active);
    });
    loadChart(button.dataset.tf);
  });
});
document.getElementById("emergency").addEventListener("click", () => {
  const banner = document.getElementById("emergency-banner");
  const on = banner.classList.toggle("hidden") === false;
  const risk = document.getElementById("overview-risk");
  risk.textContent = on ? "Đang chặn" : "An toàn";
  risk.className = on ? "text-sm text-rose-300" : "text-sm text-emerald-300";
  document.getElementById("risk-badge").textContent = on ? "đang chặn" : "đạt";
  document.getElementById("risk-badge").className = on ? "text-rose-300" : "text-emerald-300";
  document.getElementById("emergency").textContent = on ? "Giao dịch lại" : "Dừng khẩn cấp";
  fetch(apiBase + "/api/mode", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ emergency: on }),
  }).catch(() => undefined);
});
