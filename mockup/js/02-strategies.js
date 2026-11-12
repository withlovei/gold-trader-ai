let strategyLeft = 60;
let strategyScoredAt = null;

function scoreEveryLabel(seconds) {
  const whole = Number(seconds) || 60;
  if (whole % 60 === 0) {
    const minutes = whole / 60;
    return minutes === 1 ? "1 phút" : minutes + " phút";
  }
  return whole + " giây";
}

function paintStrategyClock() {
  const node = document.getElementById("strategy-clock");
  if (!node || marketClosed) return;
  const whole = Math.max(0, strategyLeft);
  const minutes = String(Math.floor(whole / 60)).padStart(2, "0");
  const seconds = String(whole % 60).padStart(2, "0");
  node.textContent = minutes + ":" + seconds;
}

function renderStrategyLog(rows) {
  const body = document.getElementById("strategy-log");
  if (!body) return;
  const list = Array.isArray(rows) ? rows.slice().reverse() : [];
  if (!list.length) {
    body.innerHTML = '<tr><td class="px-3 py-3 text-zinc-500" colspan="4">Chưa có lần chấm.</td></tr>';
    return;
  }
  body.innerHTML = list
    .map((row) => {
      const when = new Date(Number(row.scoredAt) * 1000).toLocaleString(LOCALE, {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        day: "2-digit",
        month: "2-digit",
        timeZone: "Asia/Ho_Chi_Minh",
      });
      return (
        "<tr class=\"border-t border-line/70\"><td class=\"px-3 py-2 font-mono\">" + escapeHtml(when) + "</td>" +
        "<td class=\"px-3 py-2 font-mono\">" + escapeHtml(row.timeframe || "") + "</td>" +
        "<td class=\"px-3 py-2\">" + escapeHtml(row.name || "Chưa chọn") + "</td>" +
        "<td class=\"px-3 py-2 text-zinc-300\">" + escapeHtml(row.reason || "") + "</td></tr>"
      );
    })
    .join("");
}

function renderStrategies(strategy, chart) {
  const lead = document.getElementById("strategy-lead");
  const title = document.getElementById("strategy-detail-title");
  const side = document.getElementById("strategy-detail-side");
  const text = document.getElementById("strategy-detail-text");
  const rules = document.getElementById("strategy-rules");
  const cards = document.getElementById("strategy-cards");
  const detail = document.getElementById("strategy-detail");
  if (!lead || !detail || !title || !side || !text || !rules || !cards || !strategy || !Array.isArray(strategy.catalog)) return;
  const chosen = strategy.catalog.find((item) => item.chosen) || null;
  const frame = strategy.timeframe || "M15";
  const every = chart && chart.strategyScoreEvery ? chart.strategyScoreEvery : 60;
  const stamp = chart ? Number(chart.strategyScoredAt) : NaN;
  if (Number.isFinite(stamp) && stamp !== strategyScoredAt && Number.isFinite(Number(chart.strategyScoreIn))) {
    strategyScoredAt = stamp;
    strategyLeft = Number(chart.strategyScoreIn);
  }
  lead.textContent = "Kế hoạch trên khung " + frame + " được chấm lại mỗi " + scoreEveryLabel(every) + ", trên nến đang chạy. Quyết định gửi lệnh chỉ chấm một lần khi nến " + frame + " đóng.";
  paintStrategyClock();
  renderStrategyLog(chart ? chart.strategyLog : []);
  if (!chosen) {
    detail.classList.add("hidden");
  } else {
    const sideText = chosen.side === "buy" ? "Mua" : chosen.side === "sell" ? "Bán" : "Chờ";
    detail.classList.remove("hidden");
    title.textContent = chosen.name;
    side.textContent = sideText + (chosen.confirmed ? " · đã xác nhận" : " · chưa gửi lệnh");
    text.textContent = chosen.explanation;
  }
  rules.replaceChildren();
  (chosen ? chosen.rules : []).forEach((rule) => {
    const wrap = document.createElement("div");
    wrap.className = "rounded-lg border border-line px-3 py-2";
    const label = document.createElement("p");
    label.className = "text-[11px] uppercase tracking-wider text-zinc-500";
    label.textContent = rule.label;
    const value = document.createElement("p");
    value.className = "mt-1 text-sm leading-5 text-zinc-200";
    value.textContent = rule.value;
    wrap.append(label, value);
    rules.append(wrap);
  });
  cards.replaceChildren();
  strategy.catalog.forEach((item) => {
    const article = document.createElement("article");
    const active = item.chosen;
    article.className = active
      ? "rounded-xl border border-gold/50 bg-gold/5 p-4"
      : "rounded-xl border border-line bg-panel p-4";
    const head = document.createElement("div");
    head.className = "flex items-center justify-between gap-2";
    const name = document.createElement("h2");
    name.className = "text-sm font-medium";
    name.textContent = item.name;
    const badge = document.createElement("span");
    badge.className = active ? "text-xs text-gold" : "text-xs text-zinc-500";
    badge.textContent = strategyStatus(item.status);
    head.append(name, badge);
    const summary = document.createElement("p");
    summary.className = "mt-2 text-sm leading-5 text-zinc-300";
    summary.textContent = item.summary;
    article.append(head, summary);
    cards.append(article);
  });
}
