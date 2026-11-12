let backtestToken = 0;

let backtestRuns = [];

const roleBadge = {
  live: '<span class="badge badge-ok">Lệnh thật</span>',
  shadow: '<span class="badge badge-warn">Theo dõi</span>',
  analysis: '<span class="badge badge-off">Phân tích</span>',
};
function markBacktestPreset(months) {
  document.querySelectorAll(".backtest-preset").forEach((button) => {
    const on = Number(button.dataset.months) === months;
    button.classList.toggle("border-gold", on);
    button.classList.toggle("text-gold", on);
    button.classList.toggle("border-line", !on);
    button.classList.toggle("text-zinc-300", !on);
  });
  document.getElementById("backtest-preset-note").textContent = months && months < 3
    ? "Khoảng ngắn chỉ có khoảng " + months * 10 + " lệnh, kết quả phụ thuộc may rủi nhiều."
    : "";
}
function setBacktestMonths(months) {
  const end = new Date();
  const start = new Date(end);
  start.setMonth(start.getMonth() - months);
  const iso = (d) => d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
  document.getElementById("backtest-end").value = iso(end);
  document.getElementById("backtest-start").value = iso(start);
  markBacktestPreset(months);
}
function setDefaultBacktestDates() {
  setBacktestMonths(12);
}
setDefaultBacktestDates();
document.querySelectorAll(".backtest-preset").forEach((button) =>
  button.addEventListener("click", () => setBacktestMonths(Number(button.dataset.months))));
["backtest-start", "backtest-end"].forEach((id) =>
  document.getElementById(id).addEventListener("input", () => markBacktestPreset(0)));

function clearBacktestBoard() {
  backtestRuns = [];
  document.getElementById("backtest-tabs").innerHTML = "";
  document.getElementById("backtest-decisions").classList.add("hidden");
  document.getElementById("backtest-trades").innerHTML = "";
  document.getElementById("backtest-metrics").innerHTML = "";
  document.getElementById("backtest-reliability").className = "hidden";
  document.getElementById("backtest-months").innerHTML = "";
  document.getElementById("backtest-equity").replaceChildren();
  document.getElementById("backtest-dd").replaceChildren();
  document.getElementById("backtest-count").textContent = "";
  document.getElementById("backtest-progress").style.width = "0%";
}

function showBacktestTab(index) {
  const run = backtestRuns[index];
  if (!run) return;
  document.querySelectorAll("[data-backtest-tab]").forEach((button) => {
    const active = Number(button.dataset.backtestTab) === index;
    button.classList.toggle("border-gold", active);
    button.classList.toggle("bg-gold/10", active);
    button.classList.toggle("border-line", !active);
    button.classList.toggle("bg-panel", !active);
  });
  renderBacktest(run);
}

const strategyNames = { trend: "Theo xu hướng", pullback: "Hồi giá", breakout: "Phá vùng", reversal: "Đảo chiều", range: "Đi ngang" };
function paintDecisions(info) {
  const box = document.getElementById("backtest-decisions");
  if (!info) {
    box.classList.add("hidden");
    return;
  }
  box.classList.remove("hidden");
  const signals = info.signals || {};
  const blocked = info.blocked || {};
  const totalSignals = Object.values(signals).reduce((sum, value) => sum + Number(value), 0);
  const tile = (label, value, note, tone) =>
    '<div class="rounded-lg border border-line px-3 py-2"><p class="text-[11px] text-zinc-500">' + label + '</p><p class="font-mono text-lg ' + (tone || "") + '">' + value +
    '</p><p class="text-[11px] text-zinc-500">' + (note || "") + "</p></div>";
  const pickTiles = Object.keys(strategyNames)
    .filter((id) => signals[id])
    .map((id) => {
      const live = id === "trend" || id === "pullback";
      return tile("Chọn: " + strategyNames[id], signals[id], live ? "được gửi lệnh thật" : "chỉ phân tích, không vào", live ? "text-emerald-300" : "text-zinc-300");
    });
  const agentTiles = Object.values(info.agents || {}).map((agent) =>
    tile(agent.name + ": vào lệnh", agent.taken, agent.signals + " tín hiệu · bỏ " + agent.busy + " vì đang giữ lệnh · " + (agent.opposite || 0) + " vì lệnh ngược chiều đang lãi · " +
      ((agent.risk || 0) + (agent.lock || 0) + (agent.volume || 0) + (agent.openRisk || 0)) + " vì cổng rủi ro" + (agent.paper ? " · " + agent.paper + " lệnh giấy" : ""), "text-orange-300"));
  const bookTiles = Object.entries(info.books || {}).map(([frame, book]) =>
    tile("Sổ phụ " + frame + ": vào lệnh", book.taken, book.signals + " tín hiệu · bỏ " + book.busy + " vì đang giữ lệnh " + frame + " · " + ((book.risk || 0) + (book.lock || 0) + (book.volume || 0)) + " vì cổng rủi ro (khối lượng " + (book.volume || 0) + ")", "text-orange-300"));
  if (agentTiles.length) {
    const crewList = Object.values(info.agents || {});
    const realCount = crewList.filter((agent) => agent.real).length;
    document.getElementById("backtest-decisions-grid").innerHTML = agentTiles.join("");
    document.getElementById("backtest-decisions-note").textContent = crewList.length + " agent chạy (" + realCount + " tiền thật, " + (crewList.length - realCount) + " lệnh giấy) · agent tổng Paul Tudor Jones điều phối";
    return;
  }
  document.getElementById("backtest-decisions-grid").innerHTML = [
    tile("Nến đã chấm", info.bars, "mỗi nến một quyết định"),
    tile("Có tín hiệu đủ điều kiện", totalSignals, info.bars ? (totalSignals / info.bars * 100).toFixed(1) + "% số nến" : ""),
    tile("Vào lệnh M15", info.taken, "sau khi qua cổng rủi ro", "text-gold"),
    ...pickTiles,
    ...agentTiles,
    ...bookTiles,
    tile("Bỏ: đang giữ lệnh", blocked.busy || 0, "mỗi sổ chỉ một lệnh mỗi lúc"),
    tile("Bỏ: giờ hoặc chênh lệch", blocked.filter || 0, "18–24 giờ UTC, chênh lệch > 0,80"),
    tile("Bỏ: cổng rủi ro", (blocked.risk || 0) + (blocked.lock || 0) + (blocked.volume || 0),
      "lỗ ngày/chuỗi thua " + (blocked.risk || 0) + " · khóa sụt giảm " + (blocked.lock || 0) + " · khối lượng " + (blocked.volume || 0)),
  ].join("");
  document.getElementById("backtest-decisions-note").textContent = "Bộ chọn xác nhận chiến lược ở từng nến, giống bot tự động";
}

function renderLive(data, replay) {
  backtestRuns = [];
  document.getElementById("backtest-tabs").innerHTML = "";
  renderBacktest(data, replay);
  paintDecisions(data.decisions);
}

function renderCompare(data) {
  const runs = Array.isArray(data.runs) && data.runs.length ? data.runs : data.metrics ? [data] : [];
  backtestRuns = runs;
  const tabs = document.getElementById("backtest-tabs");
  if (runs.length === 0) {
    tabs.innerHTML = "";
    renderBacktest(data);
    return;
  }
  let best = runs.findIndex((run) => run.role === "live" || run.id === "trend");
  if (best < 0) best = 0;
  tabs.innerHTML = runs
    .map((run, index) => {
      const net = Number(run.metrics?.net ?? 0);
      const tone = net >= 0 ? "text-emerald-300" : "text-rose-300";
      const factor = run.metrics?.profitFactor === null || run.metrics?.profitFactor === undefined ? "—" : run.metrics.profitFactor;
      return (
        '<button type="button" data-backtest-tab="' + index + '" class="min-w-44 rounded-lg border border-line bg-panel px-3 py-2 text-left">' +
        '<span class="flex items-center justify-between gap-2 text-sm text-zinc-100">' + escapeHtml(run.strategy) + (roleBadge[run.role] || "") + "</span>" +
        '<span class="mt-1 block font-mono text-xs ' + tone + '">' + money(net) + "</span>" +
        '<span class="mt-0.5 block text-[11px] ' + (Number(run.tradeCount ?? 0) < 30 ? "text-amber-300/80" : "text-zinc-500") + '">' +
        escapeHtml(run.tradeCount ?? 0) + " lệnh" + (Number(run.tradeCount ?? 0) < 30 ? " · quá ít" : "") + " · hệ số " + escapeHtml(factor) + "</span>" +
        "</button>"
      );
    })
    .join("");
  tabs.querySelectorAll("[data-backtest-tab]").forEach((button) => {
    button.addEventListener("click", () => showBacktestTab(Number(button.dataset.backtestTab)));
  });
  showBacktestTab(best);
  document.getElementById("backtest-progress").style.width = "100%";
}

function tradeRow(trade) {
  const tone = trade.pnl >= 0 ? "text-emerald-300" : "text-rose-300";
  return "<tr data-opened=\"" + (trade.openedTs || "") + "\" class=\"cursor-pointer border-t border-line/70 hover:bg-white/[0.03]\"><td class=\"px-3 py-2 font-mono\">" + escapeHtml(trade.time) + "</td><td class=\"px-3 py-2\">" + escapeHtml(trade.side) + "</td><td class=\"px-3 py-2 font-medium\" style=\"color:" + (strategyColor[trade.strategy] || "#e4e4e7") + "\">" + escapeHtml(trade.agent || "—") + "</td><td class=\"px-3 py-2\">" + escapeHtml(trade.strategy) + "</td><td class=\"px-3 py-2 font-mono\">" + escapeHtml(trade.entry) + "</td><td class=\"px-3 py-2 font-mono\">" + escapeHtml(trade.exit) + "</td><td class=\"px-3 py-2 font-mono " + tone + "\">" + escapeHtml(trade.pnl) + "</td><td class=\"px-3 py-2 font-mono\">" + escapeHtml(trade.r) + "</td><td class=\"px-3 py-2\">" + escapeHtml(trade.reason) + "</td></tr>";
}

function paintBacktestSummary(data) {
  const metrics = data.metrics;
  const cards = [
    ["Lãi ròng", money(metrics.net)],
    ["Lời gộp", money(metrics.grossProfit)],
    ["Lỗ gộp", money(metrics.grossLoss)],
    ["Tỷ lệ thắng", (metrics.winRate * 100).toFixed(1) + "%"],
    ["Hệ số lời", metrics.profitFactor === null ? "—" : metrics.profitFactor],
    ["Sụt giảm lớn nhất", metrics.maxDrawdown + "%"],
    ["Sharpe", metrics.sharpe === null ? "—" : metrics.sharpe],
    ["Hệ số phục hồi", metrics.recovery === null ? "—" : metrics.recovery],
    ["Kỳ vọng mỗi lệnh", money(metrics.expectancy)],
    ["R trung bình", metrics.averageRLow === null || metrics.averageRLow === undefined
      ? metrics.averageR
      : signed(metrics.averageR) + '<span class="block text-[11px] text-zinc-500">95%: ' + signed(metrics.averageRLow) + " → " + signed(metrics.averageRHigh) + "</span>"],
    ["Giữ trung bình", metrics.holdingBars + " nến"],
    ["Chuỗi thắng / thua", metrics.consecutiveWins + " / " + metrics.consecutiveLosses],
  ];
  if (data.shadow) {
    cards.push(["Sổ bóng", money(data.shadow.net)]);
    cards.push(["Sổ bóng, số lệnh", data.shadow.trades]);
    cards.push(["Sổ bóng, hệ số lời", data.shadow.profitFactor === null ? "—" : data.shadow.profitFactor]);
    cards.push(["Sổ bóng, sụt giảm", data.shadow.maxDrawdown + "%"]);
  }
  if (data.paper && data.kind !== "live") cards.push(["Sổ giấy xu hướng", data.paper.trades + " lệnh, " + money(data.paper.net)]);
  document.getElementById("backtest-metrics").innerHTML = cards
    .map((card) => '<article class="kpi rounded-xl border border-line bg-panel px-4 py-3"><p class="metric-label">' + card[0] + '</p><p class="kpi-value">' + card[1] + "</p></article>")
    .join("");
  const reliability = document.getElementById("backtest-reliability");
  if (metrics.reliability) {
    const weak = Number(metrics.trades) < 30 || (metrics.averageRLow !== null && metrics.averageRLow <= 0 && metrics.averageRHigh >= 0);
    const negative = metrics.averageRHigh !== null && metrics.averageRHigh < 0;
    reliability.className = "rounded-lg border px-4 py-3 text-sm leading-6 " + (negative
      ? "border-rose-500/30 bg-rose-500/[0.07] text-rose-200"
      : weak ? "border-amber-500/30 bg-amber-500/[0.07] text-amber-200" : "border-emerald-500/30 bg-emerald-500/[0.07] text-emerald-200");
    const roleText = { live: "Chiến lược đang gửi lệnh thật. ", shadow: "Đang theo dõi trên giấy, chưa gửi lệnh thật. ", analysis: "Chỉ phân tích, không gửi lệnh thật. " };
    reliability.textContent = (data.kind === "live" ? "Mô phỏng bot tự động. " : roleText[data.role] || "") + metrics.reliability;
  } else {
    reliability.className = "hidden";
  }
  paintMonths(data.months && data.months.rows ? data.months.rows : []);
  if (data.equity && data.equity.length > 1) lineChart("backtest-equity", data.equity, "#6ee7b7");
  if (data.drawdown && data.drawdown.length > 1) lineChart("backtest-dd", data.drawdown, "#fb7185");
}

function paintMonths(rows) {
  const box = document.getElementById("backtest-months");
  if (!rows.length) {
    box.innerHTML = '<p class="text-xs text-zinc-500">Chưa có lệnh.</p>';
    document.getElementById("backtest-months-note").textContent = "";
    return;
  }
  const peak = Math.max(...rows.map((row) => Math.abs(Number(row.net))), 1);
  box.innerHTML = rows.map((row) => {
    const net = Number(row.net);
    const alpha = Math.min(0.45, 0.08 + (Math.abs(net) / peak) * 0.37);
    const bg = net >= 0 ? "rgba(52,211,153," + alpha + ")" : "rgba(244,63,94," + alpha + ")";
    return '<div class="rounded-lg border border-line px-3 py-2" style="background:' + bg + '"><p class="font-mono text-[11px] text-zinc-300">' + escapeHtml(row.month) +
      '</p><p class="font-mono text-sm font-semibold">' + (net > 0 ? "+" : "") + money(net) + '</p><p class="text-[10.5px] text-zinc-300/80">' + row.trades + " lệnh</p></div>";
  }).join("");
  const positive = rows.filter((row) => Number(row.net) > 0).length;
  document.getElementById("backtest-months-note").textContent = positive + "/" + rows.length + " tháng có lãi";
}

const strategyColor = { "Theo xu hướng": "#e3b341", "Hồi giá": "#38bdf8", "Theo xu hướng M30": "#f97316" };
const VN_SHIFT = 7 * 3600;
let btChart = null;
let btSeries = null;
let btTrades = [];
let btLines = [];
let btSelected = -1;
let btBars = [];
let btShownUntil = Infinity;
let btShownCount = -1;
let btReplayIndex = 0;
let btTimer = null;
function vnTime(ts) {
  const d = new Date((Number(ts) + VN_SHIFT) * 1000);
  const pad = (v) => String(v).padStart(2, "0");
  return pad(d.getUTCDate()) + "/" + pad(d.getUTCMonth() + 1) + "/" + d.getUTCFullYear() + " " + pad(d.getUTCHours()) + ":" + pad(d.getUTCMinutes());
}
function backtestMarkers() {
  const markers = btTrades.map((trade, index) => {
    if (trade.openedTs + VN_SHIFT > btShownUntil) return null;
    const buy = trade.side === "Mua";
    const color = strategyColor[trade.strategy] || "#a1a1aa";
    return {
      time: trade.openedTs + VN_SHIFT,
      position: buy ? "belowBar" : "aboveBar",
      color: index === btSelected ? "#ffffff" : color,
      shape: buy ? "arrowUp" : "arrowDown",
      id: "t" + index,
      size: index === btSelected ? 2 : 1,
    };
  }).filter(Boolean);
  // Nhãn Lãi / Lỗ trên đầu nến vào lệnh, chỉ hiện khi lệnh đã đóng (kể cả lúc phát lại).
  btTrades.forEach((trade, index) => {
    if (!trade.closedTs || trade.openedTs + VN_SHIFT > btShownUntil || trade.closedTs + VN_SHIFT > btShownUntil) return;
    const win = Number(trade.pnl) >= 0;
    markers.push({
      time: trade.openedTs + VN_SHIFT,
      position: "aboveBar",
      color: win ? "#34d399" : "#f43f5e",
      shape: "circle",
      size: 0,
      text: (win ? "Lãi +$" : "Lỗ −$") + money(Math.abs(Number(trade.pnl))),
      id: "t" + index,
    });
  });
  const chosen = btTrades[btSelected];
  if (chosen && chosen.closedTs && chosen.closedTs + VN_SHIFT <= btShownUntil) {
    markers.push({
      time: chosen.closedTs + VN_SHIFT,
      position: chosen.side === "Mua" ? "aboveBar" : "belowBar",
      color: Number(chosen.pnl) >= 0 ? "#34d399" : "#f43f5e",
      shape: "circle",
      text: "Ra " + (Number(chosen.r) >= 0 ? "+" : "") + chosen.r + "R",
      id: "exit",
    });
  }
  markers.sort((a, b) => a.time - b.time);
  btSeries.setMarkers(markers);
}
function selectBacktestTrade(index, scroll) {
  const trade = btTrades[index];
  if (!trade || !btSeries) return;
  if (scroll && btShownUntil !== Infinity) btShowAll();
  btSelected = index;
  btLines.forEach((line) => btSeries.removePriceLine(line));
  btLines = [];
  const addLine = (price, color, title, style) => {
    if (price === null || price === undefined || !Number(price)) return;
    btLines.push(btSeries.createPriceLine({ price: Number(price), color, lineWidth: 1, lineStyle: style, axisLabelVisible: true, title }));
  };
  addLine(trade.entry, "#e3b341", "Vào", 0);
  addLine(trade.stop, "#f43f5e", "Cắt lỗ", 2);
  addLine(trade.take, "#34d399", "Chốt lời", 2);
  addLine(trade.exit, "#e4e4e7", "Ra", 1);
  backtestMarkers();
  if (scroll) {
    const data = btSeries.data();
    const first = data.findIndex((bar) => bar.time >= trade.openedTs + VN_SHIFT);
    if (first >= 0) btChart.timeScale().setVisibleLogicalRange({ from: first - 60, to: first + Math.max(60, Number(trade.bars) + 40) });
  }
  const buy = trade.side === "Mua";
  const tone = Number(trade.pnl) >= 0 ? "text-emerald-300" : "text-rose-300";
  const row = (label, value, cls) => '<div class="flex justify-between gap-3 border-b border-line/40 py-1.5"><span class="text-zinc-500">' + label + '</span><span class="text-right font-mono ' + (cls || "") + '">' + value + "</span></div>";
  document.getElementById("backtest-trade-detail").innerHTML =
    '<div class="flex items-center justify-between gap-2"><p class="text-[11px] text-zinc-500">Lệnh ' + (index + 1) + " / " + btTrades.length + "</p>" +
    '<div class="flex gap-1"><button type="button" data-bt-nav="-1" class="rounded border border-line px-2 py-0.5 text-xs hover:border-gold/60">‹ Trước</button>' +
    '<button type="button" data-bt-nav="1" class="rounded border border-line px-2 py-0.5 text-xs hover:border-gold/60">Sau ›</button></div></div>' +
    '<p class="mt-2 text-base font-semibold" style="color:' + (strategyColor[trade.strategy] || "#e4e4e7") + '">' + escapeHtml(trade.agent || trade.strategy) + "</p>" +
    (trade.agent ? '<p class="text-xs text-zinc-400">' + escapeHtml(trade.strategy) + "</p>" : "") +
    '<p class="mb-2 text-sm font-semibold ' + (buy ? "text-emerald-300" : "text-rose-300") + '">' + (buy ? "▲ Mua" : "▼ Bán") + "</p>" +
    row("Vào lúc", vnTime(trade.openedTs)) +
    row("Giá vào", Number(trade.entry).toFixed(2), "text-gold") +
    row("Cắt lỗ ban đầu", trade.stop ? Number(trade.stop).toFixed(2) : "—", "text-rose-300") +
    row("Chốt lời", trade.take ? Number(trade.take).toFixed(2) : "Cắt lỗ bám", "text-emerald-300") +
    row("Ra lúc", trade.closedTs ? vnTime(trade.closedTs) : "—") +
    row("Giá ra", Number(trade.exit).toFixed(2)) +
    row("Lý do thoát", escapeHtml(trade.reason)) +
    row("Giữ", trade.bars + " nến") +
    row("Lãi / lỗ", money(trade.pnl), tone) +
    row("R", (Number(trade.r) >= 0 ? "+" : "") + trade.r + "R", tone);
  document.querySelectorAll("[data-bt-nav]").forEach((button) =>
    button.addEventListener("click", () => {
      const next = Math.min(btTrades.length - 1, Math.max(0, btSelected + Number(button.dataset.btNav)));
      selectBacktestTrade(next, true);
    }));
}
function btReplayInfo() {
  const until = btShownUntil === Infinity ? Number.MAX_SAFE_INTEGER : btShownUntil;
  let opened = 0;
  let net = 0;
  let closed = 0;
  btTrades.forEach((trade) => {
    if (trade.openedTs + VN_SHIFT <= until) opened += 1;
    if (trade.closedTs && trade.closedTs + VN_SHIFT <= until) {
      closed += 1;
      net += Number(trade.pnl);
    }
  });
  const last = btBars[Math.min(btReplayIndex, btBars.length) - 1];
  const when = btShownUntil === Infinity || !last ? "Toàn bộ" : "Đến " + vnTime(last.time - VN_SHIFT);
  const info = document.getElementById("bt-replay-info");
  info.textContent = when + " · " + opened + " lệnh · đã đóng " + closed + " · lãi ròng " + (net >= 0 ? "+" : "") + money(net);
  info.className = "ml-auto font-mono text-xs " + (net >= 0 ? "text-emerald-300" : "text-rose-300");
}
function btUpdatePlayButton() {
  document.getElementById("bt-play").textContent = btTimer ? "⏸ Tạm dừng" : btReplayIndex > 0 && btReplayIndex < btBars.length ? "▶ Tiếp tục" : "▶ Phát lại";
}
function btStopReplay() {
  if (btTimer) window.clearInterval(btTimer);
  btTimer = null;
  btUpdatePlayButton();
}
function btShowAll() {
  btStopReplay();
  if (!btSeries) return;
  const replaying = btShownUntil !== Infinity;
  btSeries.setData(btBars);
  if (replaying) btChart.timeScale().setVisibleLogicalRange({ from: btBars.length - 180, to: btBars.length + 8 });
  btReplayIndex = btBars.length;
  btShownUntil = Infinity;
  btShownCount = -1;
  backtestMarkers();
  btReplayInfo();
  btUpdatePlayButton();
}
function btStartReplay() {
  btStopReplay();
  if (!btSeries || !btBars.length) return;
  if (btReplayIndex <= 0 || btReplayIndex >= btBars.length) {
    btReplayIndex = 0;
    btSelected = -1;
    btLines.forEach((line) => btSeries.removePriceLine(line));
    btLines = [];
    btSeries.setData([]);
    btShownUntil = 0;
    btShownCount = -1;
  }
  const tickMs = 50;
  btTimer = window.setInterval(() => {
    const speed = Number(document.getElementById("bt-speed").value) || 800;
    const end = Math.min(btBars.length, btReplayIndex + Math.max(1, Math.round((speed * tickMs) / 1000)));
    for (; btReplayIndex < end; btReplayIndex += 1) btSeries.update(btBars[btReplayIndex]);
    btShownUntil = btBars[btReplayIndex - 1].time;
    const shown = btTrades.filter((trade) => trade.openedTs + VN_SHIFT <= btShownUntil).length;
    if (shown !== btShownCount) {
      btShownCount = shown;
      backtestMarkers();
    }
    btReplayInfo();
    btChart.timeScale().setVisibleLogicalRange({ from: btReplayIndex - 180, to: btReplayIndex + 8 });
    if (btReplayIndex >= btBars.length) btShowAll();
  }, tickMs);
  btUpdatePlayButton();
}
document.getElementById("bt-play").addEventListener("click", () => (btTimer ? btStopReplay() : btStartReplay()));
document.getElementById("bt-all").addEventListener("click", btShowAll);

function paintBacktestChart(data, replay) {
  const card = document.getElementById("backtest-chart-card");
  const candles = Array.isArray(data.candles) ? data.candles : [];
  if (!candles.length || !window.LightweightCharts) {
    card.classList.add("hidden");
    return;
  }
  card.classList.remove("hidden");
  const box = document.getElementById("backtest-chart");
  if (!btChart) {
    btChart = LightweightCharts.createChart(box, {
      height: 440,
      layout: { background: { color: "transparent" }, textColor: "#a1a1aa", fontSize: 11 },
      grid: { vertLines: { color: "rgba(255,255,255,0.04)" }, horzLines: { color: "rgba(255,255,255,0.04)" } },
      rightPriceScale: { borderColor: "rgba(255,255,255,0.1)" },
      timeScale: { borderColor: "rgba(255,255,255,0.1)", timeVisible: true, secondsVisible: false },
      crosshair: { mode: 0 },
    });
    btSeries = btChart.addCandlestickSeries({
      upColor: "#34d399", downColor: "#f43f5e", wickUpColor: "#34d399", wickDownColor: "#f43f5e", borderVisible: false,
    });
    new ResizeObserver(() => btChart.applyOptions({ width: box.clientWidth })).observe(box);
    btChart.subscribeClick((param) => {
      const id = param.hoveredObjectId;
      if (typeof id === "string" && id.startsWith("t")) {
        selectBacktestTrade(Number(id.slice(1)), false);
        return;
      }
      if (param.time === undefined) return;
      const hit = btTrades.findIndex((trade) => trade.openedTs + VN_SHIFT === param.time);
      if (hit >= 0) selectBacktestTrade(hit, false);
    });
  }
  btStopReplay();
  btBars = candles.map((c) => ({ time: c[0] + VN_SHIFT, open: c[1], high: c[2], low: c[3], close: c[4] }));
  btTrades = (Array.isArray(data.chartTrades) ? data.chartTrades : []).filter((trade) => trade.openedTs);
  btSelected = -1;
  btLines.forEach((line) => btSeries.removePriceLine(line));
  btLines = [];
  btChart.applyOptions({ width: box.clientWidth });
  if (replay) {
    btReplayIndex = 0;
    btStartReplay();
  } else {
    btShowAll();
    btChart.timeScale().setVisibleLogicalRange({ from: candles.length - 400, to: candles.length + 5 });
  }
  document.getElementById("backtest-trade-detail").innerHTML =
    '<p class="text-xs text-zinc-500">' + btTrades.length + " lệnh trên biểu đồ. Bấm vào một mũi tên để xem chiến lược, điểm vào và điểm thoát lệnh.</p>";
}

function renderBacktest(data, replay) {
  const status = document.getElementById("backtest-status");
  if (!data || !data.ok) {
    status.textContent = data && data.message ? data.message : "Chưa có kết quả.";
    return;
  }
  paintBacktestSummary(data);
  paintBacktestChart(data, replay);
  document.getElementById("backtest-trades").innerHTML = (data.trades || []).map(tradeRow).join("");
  document.getElementById("backtest-progress").style.width = "100%";
  document.getElementById("backtest-count").textContent = (data.trades || []).length + " lệnh trên bảng";
  status.textContent = data.symbol + " · " + data.strategy + " · " + data.timeframe + " · " + data.tradeCount + " lệnh. " + data.message;
}

async function playBacktest(data, token) {
  const status = document.getElementById("backtest-status");
  const body = document.getElementById("backtest-trades");
  const bar = document.getElementById("backtest-progress");
  const count = document.getElementById("backtest-count");
  paintBacktestSummary(data);
  body.innerHTML = "";
  const trades = data.trades || [];
  if (trades.length === 0) {
    bar.style.width = "100%";
    count.textContent = "0 lệnh";
    status.textContent = data.symbol + " · " + data.strategy + " · " + data.timeframe + " · không có lệnh. " + data.message;
    return;
  }
  for (let index = 0; index < trades.length; index += 1) {
    if (token !== backtestToken) return;
    body.insertAdjacentHTML("beforeend", tradeRow(trades[index]));
    const shown = index + 1;
    bar.style.width = Math.round((shown / trades.length) * 100) + "%";
    count.textContent = shown + " / " + trades.length;
    status.textContent = "Đang hiện lệnh " + shown + " / " + trades.length + " · " + trades[index].time + " · " + trades[index].side;
    body.lastElementChild.scrollIntoView({ block: "nearest" });
    await new Promise((resolve) => window.setTimeout(resolve, 80));
  }
  if (token !== backtestToken) return;
  status.textContent = data.symbol + " · " + data.strategy + " · " + data.timeframe + " · " + data.tradeCount + " lệnh. " + data.message;
}

document.getElementById("backtest-trades").addEventListener("click", (event) => {
  const row = event.target.closest("tr[data-opened]");
  if (!row || !row.dataset.opened) return;
  const index = btTrades.findIndex((trade) => String(trade.openedTs) === row.dataset.opened);
  if (index >= 0) {
    selectBacktestTrade(index, true);
    document.getElementById("backtest-chart-card").scrollIntoView({ behavior: "smooth", block: "start" });
  }
});

document.getElementById("backtest-run").addEventListener("click", async () => {
  const button = document.getElementById("backtest-run");
  const status = document.getElementById("backtest-status");
  const bar = document.getElementById("backtest-progress");
  const token = ++backtestToken;
  button.disabled = true;
  clearBacktestBoard();
  const steps = ["Đang đọc nến...", "Đang chấm năm chiến lược trên từng nến như bot...", "Đang qua cổng rủi ro, khớp lệnh và tính sổ..."];
  let step = 0;
  status.textContent = steps[0];
  bar.classList.add("animate-pulse");
  bar.style.width = "18%";
  const ticker = window.setInterval(() => {
    step = (step + 1) % steps.length;
    status.textContent = steps[step];
    bar.style.width = (18 + step * 16) + "%";
  }, 700);
  try {
    const response = await fetch(apiBase + "/api/backtest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        strategy: (document.getElementById("backtest-strategy") || {}).value || "auto",
        timeframe: document.getElementById("backtest-timeframe").value,
        start: document.getElementById("backtest-start").value,
        end: document.getElementById("backtest-end").value,
        capital: Number(document.getElementById("backtest-capital").value),
      }),
    });
    const data = await response.json();
    window.clearInterval(ticker);
    bar.classList.remove("animate-pulse");
    if (token !== backtestToken) return;
    if (!data.ok) {
      status.textContent = data.message || "Kiểm thử không chạy được.";
      bar.style.width = "0%";
      return;
    }
    renderLive(data, true);
    if (token === backtestToken) toast("Đã có kết quả. Biểu đồ đang phát lại từng nến.");
  } catch (_error) {
    window.clearInterval(ticker);
    bar.classList.remove("animate-pulse");
    if (token === backtestToken) status.textContent = "Không gọi được dịch vụ kiểm thử.";
  } finally {
    if (token === backtestToken) button.disabled = false;
  }
});

async function loadLatestBacktest() {
  try {
    const response = await fetch(apiBase + "/api/backtest/latest");
    if (!response.ok) return;
    const data = await response.json();
    if (data.ok) data.kind === "compare" ? renderCompare(data) : renderLive(data);
  } catch (_error) {
    document.getElementById("backtest-status").textContent = "Chưa đọc được kết quả cũ.";
  }
}
loadLatestBacktest();
loadChartLayers();
paintLayerButtons();
document.querySelectorAll(".layer-btn").forEach((button) => {
  button.addEventListener("click", () => {
    chartLayers[button.dataset.layer] = !chartLayers[button.dataset.layer];
    window.localStorage.setItem("goldtrader-chart-layers", JSON.stringify(chartLayers));
    paintLayerButtons();
    if (latestChart) drawChart(latestChart);
  });
});
const startScreen = window.location.hash.slice(1);
showScreen(document.getElementById("screen-" + startScreen) ? startScreen : "dashboard");
document.querySelector('[data-mode="full"]').classList.add("bg-gold/15", "text-gold");
document.querySelectorAll(".mode-btn").forEach((button) => {
  if (button.dataset.mode !== "full") button.classList.add("text-zinc-400");
});
document.getElementById("mode-pill").textContent = "Tự động";
document.getElementById("mode-note").textContent = notes.full;
let secondsLeft = 0;
