async function pollLive() {
  try {
    const response = await fetch(apiBase + "/api/live");
    const data = await response.json();
    if (!data.ok) {
      document.getElementById("session-label").textContent = "Mất kết nối";
      setDot("dot-mt5", "bad");
      return;
    }
    marketClosed = Boolean(data.marketClosed);
    closedLabel = data.nextDecision || "";
    secondsLeft = Number(data.secondsToDecision);
    paintClock();
    if (marketClosed) {
      const lead = document.getElementById("strategy-lead");
      const strategyClock = document.getElementById("strategy-clock");
      if (lead) lead.textContent = "Thứ Bảy và Chủ Nhật phiên đóng. Không chấm lại cho đến thứ Hai.";
      if (strategyClock) strategyClock.textContent = "Đóng";
    }
    document.getElementById("symbol-label").textContent = data.symbol;
    document.getElementById("quote-price").innerHTML = '<span class="text-emerald-300">' + Number(data.bid).toFixed(2) + '</span><span class="text-zinc-600"> / </span><span class="text-rose-300">' + Number(data.ask).toFixed(2) + "</span>";
    document.getElementById("spread-label").textContent = (Number(data.ask) - Number(data.bid)).toFixed(2);
    document.getElementById("session-label").textContent = marketClosed ? "Phiên đóng" : "Giờ sàn " + data.serverTime;
    document.getElementById("acct-balance").textContent = money(data.balance);
    document.getElementById("acct-equity").textContent = money(data.equity);
    document.getElementById("acct-margin").textContent = money(data.freeMargin);
    document.getElementById("acct-daily").textContent = (data.dailyProfit > 0 ? "+" : "") + money(data.dailyProfit);
    document.getElementById("acct-dd").textContent = (data.drawdown * 100).toFixed(1) + "%";
    document.getElementById("overview-risk").textContent = data.risk;
    applyTick(Number(data.bid));
    document.getElementById("decision-word").textContent = data.decision.action;
    paintPipeline(data.pipeline);
    paintOffice(data.agents);
    paintMethods(data.agents);
    OfficeGame.update(data.agents, { bid: Number(data.bid), equity: Number(data.equity), drawdown: Number(data.drawdown), closed: marketClosed, time: data.serverTime ? "Giờ sàn " + data.serverTime : "" });
    document.getElementById("decision-blurb").textContent = data.decision.reason + " Lần chấm tiếp theo lúc " + data.nextDecision + " giờ sàn.";
    const history = document.getElementById("decision-rows");
    if (history && Array.isArray(data.history)) {
      history.innerHTML = data.history
        .map((row) => {
          const scores = Array.isArray(row.scores) && row.scores.length ? row.scores : ["—"];
          const scoreCell = scores.map((line) => "<div>" + escapeHtml(line) + "</div>").join("");
          return (
            "<tr class=\"border-b border-line/70\"><td class=\"px-3 py-2 font-mono\">" + escapeHtml(row.candle || "") + "</td>" +
            "<td class=\"px-3 py-2 text-gold\">" + escapeHtml(row.action) + "</td>" +
            "<td class=\"px-3 py-2 font-mono text-gold\">" + escapeHtml(row.points || "—") + "</td>" +
            "<td class=\"px-3 py-2\">" + escapeHtml(AGENT_BY_STRATEGY[row.strategy] || row.strategy || "—") + "</td>" +
            "<td class=\"max-w-xs px-3 py-2 font-mono leading-4 text-zinc-300\"><div class=\"max-h-8 overflow-hidden\">" + scoreCell + "</div></td>" +
            "<td class=\"max-w-sm px-3 py-2\"><div class=\"line-clamp-2\">" + escapeHtml(row.reason) + "</div></td><td class=\"px-3 py-2 text-zinc-500\">" + (row.sent ? "Có" : "Không") + "</td></tr>"
          );
        })
        .join("");
    }
    document.getElementById("risk-copy").textContent = data.decision.sent ? "Đã gửi lệnh." : "Chưa gửi lệnh.";
    paintRiskUsage(data.usage);
    document.getElementById("drawdown-unlock").classList.toggle("hidden", !data.drawdownLock);
    setDot("dot-mt5", "ok");
    const pilot = data.autopilot || {};
    setDot("dot-autopilot", pilot.error ? "bad" : pilot.lastRun ? "ok live" : "");
    document.getElementById("autopilot-note").textContent = pilot.error
      ? "Chạy nền lỗi: " + pilot.error
      : pilot.lastRun ? "Chạy nền lúc " + pilot.lastRun + ", không cần mở trang." : "";
  } catch (_error) {
    document.getElementById("session-label").textContent = "Mất kết nối";
  }
}
let reopenCheck = false;
window.setInterval(() => {
  if (secondsLeft > 0) secondsLeft -= 1;
  if (!marketClosed && strategyLeft > 0) strategyLeft -= 1;
  paintClock();
  paintStrategyClock();
  if (marketClosed && secondsLeft <= 0 && !reopenCheck) {
    reopenCheck = true;
    pollLive().finally(() => {
      reopenCheck = false;
    });
  }
}, 1000);
const chartFrame = document.getElementById("candle-chart");
if (window.ResizeObserver && chartFrame) {
  let chartBox = "";
  new ResizeObserver(() => {
    const nextBox = Math.round(chartFrame.clientWidth) + "x" + Math.round(chartFrame.clientHeight);
    if (nextBox === chartBox || !latestChart) return;
    chartBox = nextBox;
    drawChart(latestChart);
  }).observe(chartFrame);
}
window.setInterval(() => {
  if (marketClosed) return;
  pollLive();
}, 2000);
window.setInterval(() => {
  if (marketClosed) return;
  const dashboard = document.getElementById("screen-dashboard");
  const strategies = document.getElementById("screen-strategies");
  const dashboardOn = dashboard && !dashboard.classList.contains("hidden");
  const strategiesOn = strategies && !strategies.classList.contains("hidden");
  if (!dashboardOn && !strategiesOn) return;
  loadChart(undefined, true);
}, 2000);
