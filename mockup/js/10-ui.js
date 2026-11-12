// Confirm / notice in a <dialog> (no browser alert or confirm). Resolves true on "Đồng ý".
function confirmDialog(title, text, okLabel = "Đồng ý", notice = false) {
  const dialog = document.getElementById("confirm-dialog");
  document.getElementById("confirm-title").textContent = title;
  document.getElementById("confirm-text").textContent = text;
  document.getElementById("confirm-ok").textContent = okLabel;
  document.getElementById("confirm-cancel").hidden = notice;
  dialog.returnValue = "";
  return new Promise((resolve) => {
    dialog.addEventListener("close", () => resolve(dialog.returnValue === "ok"), { once: true });
    dialog.showModal();
    document.getElementById(notice ? "confirm-ok" : "confirm-cancel").focus();
  });
}
function noticeDialog(title, text) {
  return confirmDialog(title, text, "Đóng", true);
}
document.addEventListener("click", async (event) => {
  const button = event.target.closest ? event.target.closest("[data-agent-mode]") : null;
  if (!button) return;
  event.preventDefault();
  const real = button.dataset.real === "1";
  const alias = button.dataset.alias || button.dataset.agentMode;
  const question = real
    ? "Đưa " + alias + " lên tiền thật? Agent sẽ gửi lệnh thật từ nến tiếp theo."
    : "Đưa " + alias + " xuống phòng nghiên cứu? Agent ngừng gửi lệnh mới, chỉ ghi lệnh giấy. Lệnh thật đang mở vẫn được quản lý tới khi đóng.";
  if (!(await confirmDialog(real ? "Lên tiền thật" : "Xuống phòng nghiên cứu", question, real ? "↑ Lên tiền thật" : "↓ Xuống nghiên cứu"))) return;
  if (typeof OfficeGame !== "undefined") OfficeGame.closeMenu();
  button.disabled = true;
  button.textContent = "Đang chuyển…";
  try {
    const response = await fetch(apiBase + "/api/agents/mode", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id: button.dataset.agentMode, real }) });
    const data = await response.json();
    if (!data.ok) noticeDialog("Không chuyển được", data.message || "Không chuyển được.");
  } catch (error) {
    noticeDialog("Không chuyển được", String(error));
  }
  pollLive();
});
const AGENT_BY_MAGIC = { 260611: "Linda Raschke", 260613: "Larry Connors", 260612: "Ed Seykota" };
const AGENT_BY_STRATEGY = {
  "Theo xu hướng": "Linda Raschke (Theo xu hướng M15)",
  "Hồi giá": "Larry Connors (Hồi giá M15)",
  "Theo xu hướng M30": "Ed Seykota (Theo xu hướng M30)",
};
function initials(name) {
  return String(name || "?").split(" ").map((part) => part[0] || "").join("").slice(0, 3).toUpperCase();
}
function gateChips(gates) {
  const look = { ok: ["✓", "text-emerald-300 border-emerald-400/30"], fail: ["✗", "text-rose-300 border-rose-400/40"], wait: ["·", "text-zinc-600 border-line"], skip: ["–", "text-zinc-600 border-line"] };
  return (gates || []).map((gate) => {
    const style = look[gate.state] || look.wait;
    return '<span class="inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10.5px] ' + style[1] + '" title="' + escapeHtml(gate.name) + '">' + style[0] + " " + escapeHtml(gate.name) + "</span>";
  }).join(" ");
}
function usd(value, digits) {
  if (value === null || value === undefined) return "—";
  return "$" + Number(value).toFixed(digits === undefined ? 3 : digits);
}
function llmLine(cost) {
  const c = cost || {};
  const head = '<p class="metric-label">Chi phí xử lý Claude CLI</p>';
  if (!c.calls) return '<div class="rounded-lg border border-line bg-black/20 px-3 py-2">' + head + '<p class="mt-1 text-[11px] text-zinc-500">Chưa gọi lần nào. Claude chỉ được gọi khi agent có tín hiệu qua đủ quy tắc và cổng rủi ro.</p></div>';
  const today = c.today || {};
  const month = c.month || {};
  const cell = (label, value, sub) => '<div><p class="text-[10.5px] text-zinc-500">' + label + '</p><p class="font-mono text-sm text-zinc-100">' + value + '</p><p class="text-[10.5px] text-zinc-500">' + sub + "</p></div>";
  const names = { "vào": "vào", "giảm": "giảm", "bỏ": "bỏ", "lỗi": "lỗi", "quá giờ": "quá giờ", "đồng ý": "đồng ý (chấm cũ)", "nghi ngờ": "nghi ngờ (chấm cũ)", "phản đối": "phản đối (chấm cũ)" };
  const split = Object.entries(c.decisions || {}).map(([key, count]) => (names[key] || key) + " " + count).join(" · ");
  const last = c.last || null;
  const tokens = (Number(c.inputTokens || 0) / 1000).toFixed(1) + "k vào / " + (Number(c.outputTokens || 0) / 1000).toFixed(1) + "k ra";
  return '<div class="rounded-lg border border-line bg-black/20 px-3 py-2">' + head +
    '<div class="mt-1 grid grid-cols-4 gap-2">' +
    cell("Hôm nay", usd(today.cost), (today.calls || 0) + " lần") +
    cell("30 ngày", usd(month.cost), (month.calls || 0) + " lần") +
    cell("Tổng", usd(c.cost), c.calls + " lần") +
    cell("TB / lần", usd(c.averageCost), (c.averageSeconds ?? "—") + " giây") + "</div>" +
    '<p class="mt-1 text-[10.5px] text-zinc-500">Quyết định: ' + escapeHtml(split || "—") + " · token " + tokens +
    (last ? " · lần cuối " + escapeHtml(last.at) + " (" + escapeHtml(last.verdict || "") + ", " + usd(last.cost) + ", " + last.seconds + " giây)" : "") + "</p></div>";
}
// remember which <details data-key> the user opened, so the periodic re-render keeps them open
const OPEN_DETAILS = new Set();
document.addEventListener("toggle", (event) => {
  const key = event.target && event.target.dataset ? event.target.dataset.key : "";
  if (!key) return;
  if (event.target.open) OPEN_DETAILS.add(key); else OPEN_DETAILS.delete(key);
}, true);
function openAttr(key) {
  return ' data-key="' + escapeHtml(key) + '"' + (OPEN_DETAILS.has(key) ? " open" : "");
}
