document.addEventListener("click", (event) => {
  if (event.target.closest && event.target.closest("[data-office-close]")) OfficeGame.closeMenu();
  if (event.target.closest && event.target.closest("[data-office-board]")) {
    const board = document.getElementById("agent-board");
    if (board) { board.open = true; board.scrollIntoView({ behavior: "smooth", block: "start" }); }
  }
});
function setOfficeView(game) {
  const cards = document.getElementById("office-cards");
  const floor = document.getElementById("office-floor");
  const button = document.getElementById("office-view-toggle");
  if (!cards || !floor || !button) return;
  cards.hidden = game;
  floor.hidden = !game;
  button.setAttribute("aria-pressed", game ? "true" : "false");
  button.querySelector("span").textContent = game ? "Xem dạng thẻ" : "Chế độ phòng làm việc";
  if (game) OfficeGame.start(); else OfficeGame.stop();
  try { window.localStorage.setItem("goldtrader-office-view", game ? "game" : "cards"); } catch (_error) { /* per-viewer convenience only */ }
}
document.getElementById("office-view-toggle").addEventListener("click", () => {
  setOfficeView(document.getElementById("office-floor").hidden);
});
try { if (window.localStorage.getItem("goldtrader-office-view") === "game") setOfficeView(true); } catch (_error) { /* ignore */ }
const FAMILY_NAMES = { trend: "Xu hướng", breakout: "Phá vùng", reversal: "Đảo chiều" };
function labBadge(agent) {
  if (agent.stage === "draft") return '<span class="badge badge-off">Chưa triển khai</span>';
  if (agent.signal) return '<span class="badge badge-warn">Tín hiệu ' + escapeHtml(agent.signal) + "</span>";
  return '<span class="badge badge-off">Lệnh giấy · quan sát</span>';
}
function testedLine(tested) {
  if (!tested) return "";
  const part = (name, row) => name + ": " + (row.trades || 0) + " lệnh, " + signed(row.averageR, 3) + "R/lệnh, PF " + (row.profitFactor ?? "—");
  const p = tested.periods || {};
  const ok = tested.verdict === "Đạt cả hai giai đoạn";
  return '<p class="rounded border ' + (ok ? "border-emerald-400/40 text-emerald-200" : "border-line text-zinc-400") + ' px-2 py-1 text-[11px]">Kiểm thử · ' +
    escapeHtml(part("2022–24", p["2022-24"] || {})) + " · " + escapeHtml(part("2025–26", p["2025-26"] || {})) + ' · <b class="' + (ok ? "text-emerald-300" : "text-rose-300") + '">' + escapeHtml(tested.verdict) + "</b></p>";
}
function fillBacktestStrategies(crew) {
  const select = document.getElementById("backtest-strategy");
  if (!select || !crew) return;
  const options = [["auto", "Bot tự động (3 agent gốc)"]].concat((crew.agents || []).concat(crew.lab || [])
    .filter((agent) => agent.strategy && agent.stage !== "draft" && agent.timeframe === "M15" && !["trend", "pullback"].includes(agent.strategy))
    .map((agent) => [agent.strategy, agent.alias + " · " + agent.name]));
  const key = options.map((item) => item[0]).join("|");
  if (select.dataset.key === key) return;
  const keep = select.value;
  select.innerHTML = options.map((item) => '<option value="' + escapeHtml(item[0]) + '">' + escapeHtml(item[1]) + "</option>").join("");
  select.dataset.key = key;
  if (options.some((item) => item[0] === keep)) select.value = keep;
}
document.addEventListener("click", (event) => {
  const button = event.target.closest ? event.target.closest("[data-test-strategy]") : null;
  if (!button) return;
  const select = document.getElementById("backtest-strategy");
  if (select) select.value = button.dataset.testStrategy;
  const nav = document.querySelector('[data-nav="backtest"]');
  if (nav) nav.click();
});
function paintMethods(crew) {
  const root = document.getElementById("method-agents");
  if (!crew || !root) return;
  const look = { ok: ["✓", "border-emerald-400/40 bg-emerald-400/5", "text-emerald-300"], fail: ["✗", "border-rose-400/40 bg-rose-400/5", "text-rose-300"],
    warn: ["!", "border-gold/40 bg-gold/5", "text-gold"], wait: ["·", "border-line", "text-zinc-500"] };
  document.getElementById("method-note").textContent = "Agent tổng " + (crew.coordinator || "") + " · tổng rủi ro đang mở " + Number(crew.openRisk || 0).toFixed(2) + "% / " + Number(crew.openRiskCap || 6) + "% · Claude " + ((crew.llm || {}).enabled === false ? "đang tắt (chỉ dùng quy tắc)" : "đang có quyền quyết định cuối");
  root.innerHTML = (crew.agents || []).map((agent) => {
    const color = agentColor(agent.id);
    const decision = agent.decision || {};
    const method = agent.method || {};
    const tested = agent.tested || null;
    const rec = agent.record || {};
    const stages = (agent.stages || []).map((stage, index) => {
      const style = look[stage.state] || look.wait;
      return '<div class="min-w-0 flex-1 rounded-lg border px-3 py-2 ' + style[1] + '">' +
        '<p class="text-[11px] uppercase tracking-wider text-zinc-500">' + (index + 1) + ". " + escapeHtml(stage.name) + "</p>" +
        '<p class="mt-1 text-sm ' + style[2] + '">' + style[0] + " " + escapeHtml(stage.text || "—") + "</p>" +
        (stage.detail ? '<p class="mt-1 text-xs text-zinc-400">' + escapeHtml(stage.detail) + "</p>" : "") + "</div>";
    }).join('<div class="hidden self-center text-zinc-600 lg:block">→</div>');
    const list = (items) => (items || []).map((item) => "<li>" + escapeHtml(item) + "</li>").join("");
    let testedHtml = '<p class="text-xs text-zinc-500">Chưa có số kiểm thử.</p>';
    if (tested) {
      const years = Object.entries(tested.years || {});
      const top = Math.max(1, ...years.map(([, value]) => Math.abs(value)));
      testedHtml = '<p class="text-xs text-zinc-400">' + escapeHtml(tested.period) + " · " + tested.trades + " lệnh · tổng " + signed(tested.totalR, 1) + "R · TB " + signed(tested.averageR, 2) + "R/lệnh</p>" +
        '<div class="mt-2 space-y-1">' + years.map(([year, value]) =>
          '<div class="flex items-center gap-2 text-[11px]"><span class="w-9 font-mono text-zinc-500">' + year + '</span><div class="h-2 flex-1 rounded bg-white/5"><div class="h-2 rounded" style="width:' + Math.round((Math.abs(value) / top) * 100) + "%;background:" + (value >= 0 ? color : "#f43f5e") + '"></div></div><span class="w-12 text-right font-mono ' + tone(value) + '">' + signed(value, 1) + "R</span></div>").join("") + "</div>";
    }
    const live = '<p class="text-xs text-zinc-400">' + (rec.closed || 0) + " lệnh đóng · lãi ròng <span class=\"" + tone(rec.net) + "\">" + signed(rec.net) + " $</span> · R TB <span class=\"" + tone(rec.averageR) + "\">" + signed(rec.averageR, 2) + "</span> · thắng " + (rec.winRate === null || rec.winRate === undefined ? "—" : Math.round(rec.winRate * 100) + "%") + "</p>" +
      (tested && rec.closed >= 40 ? '<p class="mt-1 text-[11px] text-zinc-500">So với kiểm thử ' + signed(tested.averageR, 2) + "R/lệnh.</p>" : '<p class="mt-1 text-[11px] text-zinc-500">Cần khoảng 40 lệnh thật mới so được với kiểm thử.</p>');
    return '<article class="rounded-xl border border-line bg-panel p-4" style="border-left:3px solid ' + color + '">' +
      '<div class="flex flex-wrap items-start justify-between gap-3"><div class="flex items-center gap-3">' +
      '<div class="grid h-11 w-11 shrink-0 place-items-center rounded-full border-2 font-semibold" style="border-color:' + color + ";color:" + color + ";background:" + color + '1a">' + initials(agent.alias) + "</div>" +
      '<div><h2 class="text-base font-semibold">' + escapeHtml(agent.alias || "") + " · " + escapeHtml(agent.name || "") + '</h2><p class="text-xs text-zinc-400">Khung ' + escapeHtml(agent.timeframe || "") + " · mã sổ " + agent.magic + " · " + escapeHtml(agent.why || "") + "</p></div></div>" +
      '<div class="flex flex-col items-end gap-1"><span class="badge ' + ((agent.positions || []).length ? "badge-warn" : "badge-off") + '">' + escapeHtml((agent.activity || {}).label || "Đang theo dõi") + "</span>" + modeButton(agent) + "</div></div>" +
      '<div class="mt-4"><div class="flex justify-between text-[11px] text-zinc-500"><span>Nến gần nhất ' + escapeHtml(decision.candle || "—") + "</span><span>" + escapeHtml(decision.action || "CHỜ") + "</span></div>" +
      '<div class="mt-2 flex flex-col gap-2 lg:flex-row">' + stages + "</div>" +
      '<div class="mt-3 flex flex-wrap gap-1">' + gateChips(agent.gates) + "</div></div>" +
      '<div class="mt-4 grid gap-4 border-t border-line pt-3 md:grid-cols-3">' +
      '<div><p class="metric-label">Điều kiện vào</p><ol class="mt-1 list-decimal space-y-0.5 pl-5 text-xs text-zinc-300">' + list(method.entry) + "</ol>" +
      '<p class="metric-label mt-3">Thoát lệnh</p><ul class="mt-1 list-disc space-y-0.5 pl-5 text-xs text-zinc-300">' + list(method.exit) + "</ul></div>" +
      '<div><p class="metric-label">Kết quả kiểm thử (R theo năm)</p><div class="mt-1">' + (tested ? testedHtml : (testedLine(agent.walkForward) || testedHtml)) + "</div></div>" +
      '<div><p class="metric-label">Thực tế trên tài khoản</p><div class="mt-1">' + live + "</div>" + llmLine(agent.llm) + "</div></div>" +
      '<details class="mt-3 text-xs text-zinc-400"' + openAttr("method-" + agent.id) + '><summary class="cursor-pointer select-none text-zinc-300">Lý do đầy đủ của nến gần nhất</summary><p class="mt-2 whitespace-pre-line leading-5">' + escapeHtml(decision.reason || "Chưa có.") + "</p></details>" +
      "</article>";
  }).join("") || '<p class="text-sm text-zinc-500">Chưa có agent.</p>';
  fillBacktestStrategies(crew);
  const lab = crew.lab || [];
  const ready = lab.filter((agent) => agent.stage !== "draft").length;
  document.getElementById("method-lab-note").textContent = lab.length + " agent nghiên cứu · " + ready + " đang ghi lệnh giấy" + (lab.length - ready ? " · " + (lab.length - ready) + " chưa triển khai" : "") + (lab.length ? "" : " · tất cả đang dùng tiền thật");
  document.getElementById("method-lab").innerHTML = lab.map((agent) => {
    const rules = agent.method || {};
    const list = (items) => (items || []).map((item) => "<li>" + escapeHtml(item) + "</li>").join("");
    return '<div class="flex flex-col gap-2 rounded-lg border border-line p-3"><div class="flex items-start justify-between gap-2"><div><p class="text-sm font-semibold text-zinc-200">' + escapeHtml(agent.alias) + '</p>' +
      '<p class="text-[11px] text-zinc-500">' + escapeHtml(agent.name) + (agent.family ? " · nhóm " + escapeHtml(FAMILY_NAMES[agent.family] || agent.family) : "") + "</p></div>" + labBadge(agent) + "</div>" +
      '<p class="text-xs text-zinc-300">' + escapeHtml(agent.summary || agent.activity || "") + "</p>" +
      (agent.gates && agent.gates.length ? '<div class="flex flex-wrap gap-1">' + gateChips(agent.gates) + "</div>" : "") +
      testedLine(agent.tested) +
      '<details class="text-[11px] text-zinc-400"' + openAttr("method-lab-" + agent.id) + '><summary class="cursor-pointer select-none text-zinc-300">Phương pháp · vì sao tên</summary>' +
      '<p class="mt-1">' + escapeHtml(agent.why || "") + "</p>" +
      (rules.entry ? '<p class="mt-2 text-zinc-500">Điều kiện vào</p><ol class="list-decimal pl-5">' + list(rules.entry) + "</ol>" : "") +
      (rules.exit ? '<p class="mt-1 text-zinc-500">Thoát lệnh</p><ul class="list-disc pl-5">' + list(rules.exit) + "</ul>" : '<p class="mt-1 text-zinc-500">' + escapeHtml(agent.rule || "") + "</p>") +
      "</details>" +
      '<div class="flex flex-wrap gap-2">' + (agent.strategy && agent.stage !== "draft" ? '<button type="button" data-test-strategy="' + escapeHtml(agent.strategy) + '" class="self-start rounded-md border border-line px-2.5 py-1 text-[11px] text-zinc-300 hover:border-gold/60">Kiểm thử phương pháp này →</button>' : "") +
      (agent.magic ? modeButton(agent) : "") + "</div>" +
      "</div>";
  }).join("");
}
function paintOffice(crew) {
  const staff = document.getElementById("office-staff");
  if (!crew || !staff) return;
  document.getElementById("boss-name").textContent = crew.coordinator || "Agent tổng";
  document.getElementById("boss-why").textContent = crew.coordinatorWhy || "";
  document.getElementById("boss-activity").textContent = crew.coordinatorActivity || "";
  document.getElementById("boss-rules").innerHTML = (crew.rules || []).map((rule) => "<li>" + escapeHtml(rule) + "</li>").join("");
  const used = Number(crew.openRisk || 0);
  const cap = Number(crew.openRiskCap || 6);
  document.getElementById("office-openrisk").textContent = used.toFixed(2) + "% / " + cap + "%";
  document.getElementById("office-riskbar").style.width = Math.min(100, (used / cap) * 100).toFixed(0) + "%";
  const openNow = document.getElementById("risk-now-open");
  if (openNow) openNow.textContent = used.toFixed(2) + "%";
  const llm = crew.llm || {};
  const today = llm.today || {};
  const month = llm.month || {};
  const all = llm.all || {};
  document.getElementById("office-llm").textContent = usd(today.cost) + " · " + (today.calls || 0) + " lần";
  document.getElementById("office-llm-sub").textContent = (llm.enabled === false ? "đang tắt · " : "") + (month.calls || 0) + " lần/30 ngày · " + usd(month.cost) + " · tổng " + usd(all.cost);
  document.getElementById("office-llm-note").textContent = llm.note || "";
  const agents = crew.agents || [];
  const busy = agents.filter((agent) => (agent.positions || []).length).length;
  document.getElementById("office-staff-note").textContent = agents.length + " agent đang làm việc · " + busy + " đang giữ lệnh · vốn chia đều, mỗi agent tối đa một lệnh · bấm \"Xuống nghiên cứu\" để ngừng gửi lệnh thật";
  const badge = { holding: "badge-warn", sent: "badge-ok", blocked: "badge-off", waiting: "badge-off", idle: "badge-off" };
  staff.innerHTML = agents.map((agent) => {
    const color = agentColor(agent.id);
    const act = agent.activity || {};
    const rec = agent.record || {};
    const gates = agent.gates || [];
    const counted = gates.filter((gate) => gate.state !== "skip");
    const passed = counted.filter((gate) => gate.state === "ok").length;
    const pct = counted.length ? Math.round((passed / counted.length) * 100) : 0;
    const decision = agent.decision || {};
    const positions = (agent.positions || []).map((p) =>
      '<div class="flex flex-wrap justify-between gap-2 rounded-lg border border-gold/30 bg-gold/5 px-3 py-2 font-mono text-xs"><span class="' + (p.side === "Mua" ? "text-emerald-300" : "text-rose-300") + '">' + p.side + " " + p.volume + " lot @ " + p.open.toFixed(2) + "</span>" +
      '<span class="text-zinc-400">cắt lỗ ' + (p.sl ? p.sl.toFixed(2) : "—") + '</span><span class="' + tone(p.profit) + '">' + signed(p.profit) + " $</span></div>").join("");
    return '<article class="flex flex-col gap-3 rounded-xl border border-line bg-panel p-4" style="border-top:3px solid ' + color + '">' +
      '<div class="flex items-start justify-between gap-2"><div class="flex items-center gap-3">' +
      '<div class="grid h-11 w-11 shrink-0 place-items-center rounded-full border-2 font-semibold" style="border-color:' + color + ";color:" + color + ";background:" + color + '1a">' + initials(agent.alias) + "</div>" +
      '<div><h3 class="text-base font-semibold leading-tight">' + escapeHtml(agent.alias || agent.name) + '</h3><p class="text-xs text-zinc-400">' + escapeHtml(agent.name) + " · mã sổ " + agent.magic + "</p>" +
      '<p class="text-xs"><span class="text-gold">' + "★".repeat(Number(agent.stars || 0)) + '</span><span class="text-zinc-600">' + "☆".repeat(5 - Number(agent.stars || 0)) + '</span> <span class="text-zinc-400">' + (agent.trades || 0) + " lệnh</span></p></div></div>" +
      '<div class="flex flex-col items-end gap-1"><span class="badge ' + (badge[act.state] || "badge-off") + '">' + escapeHtml(act.label || "Đang theo dõi") + "</span>" + modeButton(agent) + "</div></div>" +
      '<p class="rounded-lg bg-black/20 px-3 py-2 text-sm text-zinc-100">' + escapeHtml(act.text || "") + "</p>" +
      positions +
      '<div><div class="flex justify-between text-[11px] text-zinc-500"><span>Điều kiện nến ' + escapeHtml(decision.candle || "—") + "</span><span class=\"font-mono\">" + passed + "/" + counted.length + "</span></div>" +
      '<div class="mt-1 h-1.5 overflow-hidden rounded bg-white/10"><div class="h-1.5 rounded" style="width:' + pct + "%;background:" + color + '"></div></div>' +
      '<div class="mt-2 flex flex-wrap gap-1">' + gateChips(gates) + "</div></div>" +
      '<div class="grid grid-cols-4 gap-2 border-t border-line pt-2 text-center text-xs">' +
      '<div><p class="text-zinc-500">Lệnh đóng</p><p class="font-mono">' + (rec.closed || 0) + "</p></div>" +
      '<div><p class="text-zinc-500">Lãi ròng</p><p class="font-mono ' + tone(rec.net) + '">' + signed(rec.net) + "</p></div>" +
      '<div><p class="text-zinc-500">R TB</p><p class="font-mono ' + tone(rec.averageR) + '">' + signed(rec.averageR, 2) + "</p></div>" +
      '<div><p class="text-zinc-500">Thắng</p><p class="font-mono">' + (rec.winRate === null || rec.winRate === undefined ? "—" : Math.round(rec.winRate * 100) + "%") + "</p></div></div>" +
      llmLine(agent.llm) +
      '<details class="text-xs text-zinc-400"' + openAttr("staff-" + agent.id) + '><summary class="cursor-pointer select-none text-zinc-300">Vì sao tên ' + escapeHtml(agent.alias || "") + " · quy tắc làm việc</summary>" +
      '<p class="mt-2">' + escapeHtml(agent.why || "") + '</p><p class="mt-1 text-zinc-500">' + escapeHtml(agent.rule || "") + "</p>" +
      '<p class="mt-1 text-zinc-500">Phần vốn ' + money(agent.budget) + " (" + Math.round((agent.share || 0) * 100) + "%) · rủi ro đang mở " + Number(agent.openRisk || 0).toFixed(2) + "%</p></details>" +
      "</article>";
  }).join("") || '<p class="text-sm text-zinc-500">Chưa có agent.</p>';
  document.getElementById("office-lab").innerHTML = (crew.lab || []).map((agent) =>
    '<article class="space-y-2 rounded-xl border border-dashed border-line bg-panel/60 p-3">' +
    '<div class="flex items-center justify-between gap-2"><div class="flex items-center gap-2">' +
    '<div class="grid h-8 w-8 place-items-center rounded-full border border-zinc-600 text-[11px] font-semibold text-zinc-400">' + initials(agent.alias) + "</div>" +
    '<div><p class="text-sm font-semibold text-zinc-200">' + escapeHtml(agent.alias) + '</p><p class="text-[11px] text-zinc-500">' + escapeHtml(agent.name) + "</p></div></div>" +
    labBadge(agent) + "</div>" +
    '<p class="line-clamp-2 text-xs text-zinc-300">' + escapeHtml(agent.activity || "") + "</p>" +
    (agent.gates && agent.gates.length ? '<div class="flex flex-wrap gap-1">' + gateChips(agent.gates) + "</div>" : "") +
    '<details class="text-[11px] text-zinc-500"' + openAttr("lab-" + (agent.id || agent.alias)) + '><summary class="cursor-pointer select-none">Vì sao tên · quy tắc</summary><p class="mt-1">' + escapeHtml(agent.why || "") + '</p><p class="mt-1">' + escapeHtml(agent.rule || "") + "</p></details>" +
    (agent.magic ? modeButton(agent) : "") +
    "</article>").join("");
  paintSwitchboard(crew);
}

function paintAgents(crew) {
  const root = document.getElementById("crew-agents");
  if (!crew || !root) return;
  const used = Number(crew.openRisk || 0);
  const cap = Number(crew.openRiskCap || 6);
  document.getElementById("crew-title").textContent = "Agent tổng · " + (crew.coordinator || "") + " · điều phối " + (crew.agents || []).length + " agent tiền thật";
  document.getElementById("crew-risk").textContent = "Tổng rủi ro đang mở " + used.toFixed(2) + "% / tối đa " + cap + "%";
  document.querySelector("#crew-bar > div").style.width = Math.min(100, (used / cap) * 100).toFixed(0) + "%";
  document.getElementById("crew-rules").innerHTML = (crew.rules || []).map((rule) => "<li>" + escapeHtml(rule) + "</li>").join("");
  document.getElementById("crew-paper").textContent = crew.paper && crew.paper.length ? "Chỉ theo dõi, không có tiền thật: " + crew.paper.join(", ") + " (kiểm thử nhiều năm không có lợi thế)." : "";
  const openNow = document.getElementById("risk-now-open");
  if (openNow) openNow.textContent = used.toFixed(2) + "%";
  root.innerHTML = (crew.agents || []).map((agent) => {
    const rec = agent.record || {};
    const decision = agent.decision || {};
    const positions = (agent.positions || []).map((p) =>
      '<p class="font-mono text-xs"><span class="' + (p.side === "Mua" ? "text-emerald-300" : "text-rose-300") + '">' + p.side + "</span> " + p.volume + " lot @ " + p.open.toFixed(2) +
      ' · cắt lỗ ' + (p.sl ? p.sl.toFixed(2) : "—") + ' · <span class="' + tone(p.profit) + '">' + signed(p.profit) + " $</span></p>").join("") ||
      '<p class="text-xs text-zinc-500">Không có lệnh mở.</p>';
    return '<article class="space-y-3 rounded-xl border border-line bg-panel p-4">' +
      '<div class="flex items-baseline justify-between gap-2"><div><h3 class="text-base font-semibold">' + escapeHtml(agent.alias || agent.name) + '</h3><p class="text-xs text-zinc-400">' + escapeHtml(agent.name) + '</p></div><span class="badge badge-ok">' + escapeHtml(agent.status) + "</span></div>" +
      '<p class="text-xs text-zinc-500">Mã sổ ' + agent.magic + " · tỷ trọng " + Math.round(agent.share * 100) + "% · phần vốn " + money(agent.budget) + " · rủi ro đang mở " + Number(agent.openRisk).toFixed(2) + "%</p>" +
      '<div class="rounded-lg border border-line px-3 py-2"><p class="text-[11px] uppercase tracking-wider text-zinc-500">Nến ' + escapeHtml(decision.candle || "—") + " · " +
      '<span class="' + (decision.sent ? "text-emerald-300" : "text-gold") + '">' + escapeHtml(decision.action || "CHỜ") + "</span>" + (decision.points ? " · " + escapeHtml(decision.points) : "") + "</p>" +
      '<p class="mt-1 line-clamp-3 text-xs text-zinc-300">' + escapeHtml(decision.reason || "Chưa chấm.") + "</p></div>" +
      '<div>' + positions + "</div>" +
      '<div class="grid grid-cols-4 gap-2 text-center text-xs">' +
      '<div><p class="text-zinc-500">Lệnh đóng</p><p class="font-mono">' + (rec.closed || 0) + "</p></div>" +
      '<div><p class="text-zinc-500">Lãi ròng</p><p class="font-mono ' + tone(rec.net) + '">' + signed(rec.net) + "</p></div>" +
      '<div><p class="text-zinc-500">R TB</p><p class="font-mono ' + tone(rec.averageR) + '">' + signed(rec.averageR, 2) + "</p></div>" +
      '<div><p class="text-zinc-500">Thắng</p><p class="font-mono">' + (rec.winRate === null || rec.winRate === undefined ? "—" : Math.round(rec.winRate * 100) + "%") + "</p></div></div>" +
      "</article>";
  }).join("");
}

async function loadLlm() {
  try {
    const data = await (await fetch(apiBase + "/api/settings/llm")).json();
    document.getElementById("llm-enabled").checked = Boolean(data.enabled);
    document.getElementById("llm-status").textContent = data.cli ? "Tìm thấy Claude CLI: " + data.cli : "Chưa tìm thấy Claude CLI trên máy. Đặt biến môi trường CLAUDE_CLI trỏ tới claude.exe.";
  } catch (_error) {
    document.getElementById("llm-status").textContent = "Không đọc được cài đặt.";
  }
}
document.getElementById("llm-enabled").addEventListener("change", async (event) => {
  await fetch(apiBase + "/api/settings/llm", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled: event.target.checked }) });
  loadLlm();
  toast(event.target.checked ? "Đã bật Claude chấm điểm." : "Đã tắt Claude chấm điểm.");
});
loadLlm();

function paintPipeline(pipeline) {
  const totalNode = document.getElementById("decision-total");
  const bars = document.getElementById("score-bars");
  const steps = document.getElementById("decision-steps");
  const rule = document.getElementById("decision-rule");
  if (!pipeline || !bars || !steps) return;
  const label = pipeline.label || "—";
  if (totalNode) totalNode.textContent = label;
  const drawerWord = document.getElementById("drawer-word");
  const drawerTotal = document.getElementById("drawer-total");
  const word = document.getElementById("decision-word");
  if (drawerWord && word) drawerWord.textContent = word.textContent;
  if (drawerTotal) drawerTotal.textContent = label;
  if (rule && pipeline.rule) rule.textContent = pipeline.rule;
  const tones = { ok: "text-emerald-300", wait: "text-gold", bad: "text-rose-300", off: "text-zinc-500" };
  const gateLook = {
    ok: ["✓", "text-emerald-300", "đạt"],
    fail: ["✗", "text-rose-300", "chưa đạt"],
    wait: ["·", "text-zinc-600", "chưa xét"],
    skip: ["–", "text-zinc-600", "không áp dụng"],
  };
  bars.innerHTML = (pipeline.groups || [])
    .map((group) => {
      const gates = group.gates || [];
      const counted = gates.filter((gate) => gate.state !== "skip");
      const passed = counted.filter((gate) => gate.state === "ok").length;
      const rows = gates
        .map((gate) => {
          const look = gateLook[gate.state] || gateLook.wait;
          return '<li class="flex items-start gap-2"><span class="w-3 shrink-0 font-mono ' + look[1] + '">' + look[0] + '</span><span class="flex-1 ' +
            (gate.state === "wait" || gate.state === "skip" ? "text-zinc-500" : "text-zinc-200") + '">' + escapeHtml(gate.name) +
            '</span><span class="shrink-0 text-[11px] ' + look[1] + '">' + look[2] + "</span></li>";
        })
        .join("");
      return '<div class="rounded-lg border border-line px-3 py-2"><div class="flex justify-between text-[11px] uppercase tracking-wider text-zinc-500"><span>' +
        escapeHtml(group.name) + '</span><span class="font-mono">' + passed + "/" + counted.length + '</span></div><ol class="mt-1.5 space-y-1">' + rows + "</ol></div>";
    })
    .join("");
  steps.innerHTML = (pipeline.steps || [])
    .map((step) => {
      const tone = tones[step.tone] || "text-zinc-400";
      return '<li class="flex justify-between gap-3"><span class="min-w-[45%]">' + escapeHtml(step.name) + '</span><span class="text-right ' + tone + '">' + escapeHtml(step.value) + "</span></li>";
    })
    .join("");
}
