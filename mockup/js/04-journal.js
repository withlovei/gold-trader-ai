function setDot(id, tone) {
  const dot = document.getElementById(id);
  if (dot) dot.className = "dot" + (tone ? " " + tone : "");
}
function signed(value, digits) {
  if (value === null || value === undefined) return "—";
  const number = Number(value);
  return (number > 0 ? "+" : "") + number.toFixed(digits === undefined ? 2 : digits);
}
function tone(value) {
  if (value === null || value === undefined) return "text-zinc-300";
  return Number(value) > 0 ? "text-emerald-300" : Number(value) < 0 ? "text-rose-300" : "text-zinc-300";
}
function statTile(label, value, sub, cls) {
  return '<article class="kpi rounded-xl border border-line bg-panel px-4 py-3"><p class="metric-label">' + label +
    '</p><p class="kpi-value ' + (cls || "") + '">' + value + '</p><p class="mt-1 text-[11px] text-zinc-500">' + (sub || "") + "</p></article>";
}
async function loadJournal() {
  try {
    const response = await fetch(apiBase + "/api/journal");
    const data = await response.json();
    const stats = data.stats || {};
    const expected = stats.expected || {};
    document.getElementById("journal-verdict").textContent = stats.verdict || "";
    document.getElementById("journal-stats").innerHTML = [
      statTile("Lệnh đã đóng", stats.closed || 0, (stats.open || 0) + " lệnh đang mở"),
      statTile("Lãi lỗ ròng", signed(stats.net) + " $", "sau phí và qua đêm", tone(stats.net)),
      statTile("Tổng R", signed(stats.totalR), "1R = rủi ro đặt cho lệnh", tone(stats.totalR)),
      statTile("R trung bình", signed(stats.averageR, 3), "kiểm thử " + signed(expected.averageR, 2), tone(stats.averageR)),
      statTile("Tỷ lệ thắng", stats.winRate === null || stats.winRate === undefined ? "—" : (stats.winRate * 100).toFixed(0) + "%", "kiểm thử " + Math.round((expected.winRate || 0) * 100) + "%"),
      statTile("Trượt giá TB", stats.averageSlippage === null || stats.averageSlippage === undefined ? "—" : signed(stats.averageSlippage, 3), "dương là khớp xấu hơn giá đặt"),
    ].join("");
    paintShadow(data.shadow || {});
    const vetoRows = data.vetoes || [];
    document.getElementById("veto-rows").innerHTML = vetoRows.length
      ? vetoRows.map((row) => "<tr><td class=\"py-2 pr-3 font-mono\">" + escapeHtml(row.when) + "</td><td class=\"py-2 pr-3\">" + escapeHtml(row.agentLabel || row.agent) +
          "</td><td class=\"py-2 pr-3 " + (row.side === "buy" ? "text-emerald-300" : "text-rose-300") + "\">" + (row.side === "buy" ? "Mua" : "Bán") +
          "</td><td class=\"py-2 pr-3 font-mono\">" + Number(row.entry).toFixed(2) + " / " + Number(row.stop).toFixed(2) + " / " + (row.take ? Number(row.take).toFixed(2) : "bám") +
          "</td><td class=\"py-2 pr-3 text-zinc-300\">" + escapeHtml(row.reason || "") + "</td></tr>").join("")
      : '<tr class="empty-row"><td colspan="5">Chưa có tín hiệu nào bị bỏ.</td></tr>';
    const rows = data.rows || [];
    document.getElementById("journal-count").textContent = rows.length ? rows.length + " lệnh gần nhất" : "";
    document.getElementById("journal-rows").innerHTML = rows.length
      ? rows.map((row) => {
          const sideClass = row.side === "Mua" ? "text-emerald-300" : "text-rose-300";
          const status = row.status === "Đang mở" ? '<span class="badge badge-warn">Đang mở</span>' : '<span class="badge badge-off">Đã đóng</span>';
          return "<tr>" +
            '<td class="px-3 py-2 font-mono">' + escapeHtml(row.opened) + "</td>" +
            '<td class="px-3 py-2 font-semibold ' + sideClass + '">' + row.side + "</td>" +
            '<td class="px-3 py-2 font-mono">' + row.volume + (row.sizeFactor !== null && row.sizeFactor < 1 ? ' <span class="badge badge-warn">½</span>' : "") +
            (row.score !== null && row.score !== undefined ? '<span class="block text-[10px] text-zinc-500">điểm ' + Math.round(row.score * 100) + "%</span>" : "") + "</td>" +
            '<td class="px-3 py-2 font-mono">' + Number(row.fill).toFixed(2) + "</td>" +
            '<td class="px-3 py-2 font-mono">' + signed(row.slippage, 2) + "</td>" +
            '<td class="px-3 py-2 font-mono text-zinc-400">' + Number(row.sl).toFixed(2) + " / " + (row.tp ? Number(row.tp).toFixed(2) : "—") + "</td>" +
            '<td class="px-3 py-2 font-mono">' + Number(row.riskMoney || 0).toFixed(2) + " $</td>" +
            '<td class="px-3 py-2">' + status + "</td>" +
            '<td class="px-3 py-2 font-mono">' + (row.exit ? Number(row.exit).toFixed(2) : "—") + "</td>" +
            '<td class="px-3 py-2 font-mono ' + tone(row.net) + '">' + (row.net === null ? "—" : signed(row.net) + " $") + "</td>" +
            '<td class="px-3 py-2 font-mono ' + tone(row.r) + '">' + (row.r === null ? "—" : signed(row.r)) + "</td>" +
            '<td class="px-3 py-2 text-zinc-400">' + escapeHtml(row.reason || "") + (row.bars ? " · " + row.bars + " nến" : "") + "</td>" +
            '<td class="px-3 py-2 text-zinc-300">' + escapeHtml(row.agent || row.strategy || "") + "</td>" +
            '<td class="max-w-xs px-3 py-2" title="' + escapeHtml(row.llmReason || "") + '"><span class="' + (row.llmVerdict === "đồng ý" ? "text-emerald-300" : row.llmVerdict === "phản đối" ? "text-rose-300" : row.llmVerdict === "nghi ngờ" ? "text-gold" : "text-zinc-500") + '">' +
            escapeHtml(row.llmVerdict || "—") + "</span>" + (row.llmCost ? '<span class="ml-1 font-mono text-[10px] text-zinc-500">$' + Number(row.llmCost).toFixed(3) + (row.llmSeconds ? " · " + row.llmSeconds + "s" : "") + "</span>" : "") +
            '<span class="block line-clamp-2 text-[10px] text-zinc-500">' + escapeHtml(row.llmReason || "") + "</span></td></tr>";
        }).join("")
      : '<tr class="empty-row"><td colspan="14">Chưa có lệnh tự động nào. Lệnh sẽ hiện ở đây ngay khi được gửi.</td></tr>';
    const llm = stats.llm || {};
    const llmRows = (llm.rows || []).map((row) => row.verdict + ": " + row.trades + " lệnh, " + signed(row.averageR, 2) + "R/lệnh").join(" · ");
    const spent = (llm.costs || {}).all || {};
    document.getElementById("journal-verdict").textContent = (stats.verdict || "") + (llm.note ? " Claude: " + (llmRows ? llmRows + ". " : "") + llm.note : "") +
      (spent.calls ? " Chi phí Claude CLI: " + spent.calls + " lần, tổng $" + Number(spent.cost).toFixed(3) + " (TB $" + Number(spent.averageCost).toFixed(3) + "/lần, giá API quy đổi)." : "");
  } catch (_error) {
    document.getElementById("journal-verdict").textContent = "Không đọc được sổ lệnh.";
  }
}
document.getElementById("journal-refresh").addEventListener("click", loadJournal);
function paintShadow(data) {
  const s = (data.strategies || {}).breakout || {};
  const expected = s.expected || {};
  document.getElementById("shadow-stats").innerHTML = [
    statTile("Phá vùng · lệnh giấy", s.closed || 0, (s.open || 0) + " lệnh đang mở"),
    statTile("Tổng R", signed(s.totalR), "không phải tiền thật", tone(s.totalR)),
    statTile("R trung bình", signed(s.averageR, 3), "kiểm thử " + signed(expected.averageR, 3), tone(s.averageR)),
    statTile("Tỷ lệ thắng", s.winRate === null || s.winRate === undefined ? "—" : Math.round(s.winRate * 100) + "%", "kiểm thử " + Math.round((expected.winRate || 0) * 100) + "%"),
    statTile("Hệ số lời", s.profitFactor === null || s.profitFactor === undefined ? "—" : s.profitFactor, "kiểm thử " + (expected.profitFactor || "—")),
  ].join("");
  document.getElementById("shadow-verdict").textContent = s.verdict || "";
  const rows = data.rows || [];
  document.getElementById("shadow-rows").innerHTML = rows.length
    ? rows.map((row) => "<tr>" +
        '<td class="py-2 pr-3 font-mono">' + escapeHtml(row.opened) + "</td>" +
        '<td class="py-2 pr-3">' + escapeHtml(row.strategy) + "</td>" +
        '<td class="py-2 pr-3 font-semibold ' + (row.side === "Mua" ? "text-emerald-300" : "text-rose-300") + '">' + row.side + "</td>" +
        '<td class="py-2 pr-3 font-mono">' + Number(row.entry).toFixed(2) + "</td>" +
        '<td class="py-2 pr-3 font-mono">' + Number(row.stop).toFixed(2) + "</td>" +
        '<td class="py-2 pr-3">' + (row.status === "Đang mở" ? '<span class="badge badge-warn">Đang mở</span>' : '<span class="badge badge-off">Đã đóng</span>') + "</td>" +
        '<td class="py-2 pr-3 font-mono">' + (row.exit ? Number(row.exit).toFixed(2) : "—") + "</td>" +
        '<td class="py-2 pr-3 font-mono ' + tone(row.r) + '">' + (row.r === null ? "—" : signed(row.r)) + "</td>" +
        '<td class="py-2 pr-3 text-zinc-400">' + escapeHtml(row.reason) + (row.bars ? " · " + row.bars + " nến" : "") + "</td></tr>").join("")
    : '<tr class="empty-row"><td colspan="9">Chưa có lệnh giấy. Lệnh sẽ xuất hiện khi Phá vùng có tín hiệu trên nến M30 đóng.</td></tr>';
}

function paintTelegram(data) {
  document.getElementById("tg-enabled").checked = Boolean(data.enabled);
  document.getElementById("tg-chat").value = data.chatId || "";
  document.getElementById("tg-token").placeholder = data.hasToken ? "Đã lưu mã bot · để trống nếu không đổi" : "Dán mã bot từ @BotFather";
  const parts = [];
  parts.push(data.enabled ? "Đang bật." : "Đang tắt.");
  if (data.lastSent) parts.push("Gửi gần nhất " + data.lastSent + ".");
  if (data.lastError) parts.push("Lỗi: " + data.lastError);
  document.getElementById("tg-status").textContent = parts.join(" ");
  setDot("dot-telegram", data.lastError ? "bad" : data.enabled ? "ok" : "");
}
async function loadTelegram() {
  try {
    const response = await fetch(apiBase + "/api/settings/telegram");
    paintTelegram(await response.json());
  } catch (_error) {
    document.getElementById("tg-status").textContent = "Chưa đọc được cài đặt Telegram.";
  }
}
document.getElementById("telegram-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const status = document.getElementById("tg-status");
  status.textContent = "Đang lưu…";
  try {
    const response = await fetch(apiBase + "/api/settings/telegram", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        enabled: document.getElementById("tg-enabled").checked,
        chatId: document.getElementById("tg-chat").value,
        token: document.getElementById("tg-token").value,
      }),
    });
    const data = await response.json();
    if (!data.ok) {
      status.textContent = data.message || "Chưa lưu được.";
      return;
    }
    document.getElementById("tg-token").value = "";
    paintTelegram(data);
    toast("Đã lưu cài đặt Telegram.");
  } catch (_error) {
    status.textContent = "Không gọi được dịch vụ.";
  }
});
document.getElementById("tg-test").addEventListener("click", async () => {
  const status = document.getElementById("tg-status");
  status.textContent = "Đang gửi tin thử…";
  try {
    const response = await fetch(apiBase + "/api/settings/telegram/test", { method: "POST" });
    const data = await response.json();
    status.textContent = data.message || "";
    setDot("dot-telegram", data.ok ? "ok" : "bad");
  } catch (_error) {
    status.textContent = "Không gọi được dịch vụ.";
  }
});
