const EVENT_ICON = { step: "⏳", meeting: "🗣️", decision: "📋", change: "🔀", improve: "🎯", code: "🛠", rollback: "↩️", restart: "🔄", done: "✅", arbitration: "⚖️" };
const EVENT_NAME = { step: "Bước", meeting: "Trưởng phòng", decision: "Quyết định", change: "Chuyển bàn", improve: "Giao cải tiến", code: "Sửa mã",
  rollback: "Khôi phục", restart: "Khởi động lại", done: "Kết thúc", arbitration: "Phân xử" };
function diaryDetail(detail) {
  if (!detail) return "";
  const parts = [];
  if (detail.diff) parts.push("<p class='mt-1 text-zinc-400'>Thay đổi mã:</p><pre class='overflow-x-auto whitespace-pre rounded bg-black/40 p-2 text-[10px] leading-tight'>" +
    escapeHtml(detail.diff).replace(/^(\+[^+].*)$/gm, "<span class='text-emerald-300'>$1</span>").replace(/^(-[^-].*)$/gm, "<span class='text-rose-300'>$1</span>") + "</pre>");
  const rest = Object.assign({}, detail);
  delete rest.diff;
  if (rest.context) rest.context = "(số liệu " + ((rest.context.agents || []).length) + " agent — xem trong file biên bản)";
  parts.push("<details class='mt-1'><summary class='cursor-pointer text-[11px] text-zinc-500'>Dữ liệu chi tiết</summary><pre class='mt-1 max-h-72 overflow-auto whitespace-pre-wrap rounded bg-black/40 p-2 text-[10px] leading-tight text-zinc-300'>" +
    escapeHtml(JSON.stringify(rest, null, 1)) + "</pre></details>");
  return parts.join("");
}
function timeOf(at) {
  return new Date(at * 1000).toLocaleTimeString(LOCALE, { hour12: false });
}
// One meeting's timeline: each step on its own row; rows with details expand.
function timelineHtml(entries) {
  return entries.map((e) => {
    const head = "<span class='w-16 shrink-0 font-mono text-[11px] text-zinc-500'>" + escapeHtml(e.at ? (typeof e.at === "number" ? timeOf(e.at) : e.at) : "") + "</span>" +
      "<span class='w-5 shrink-0'>" + (EVENT_ICON[e.kind] || "•") + "</span>";
    const tag = "<span class='mr-1 rounded bg-white/5 px-1 text-[10px] text-zinc-400'>" + (EVENT_NAME[e.kind] || e.kind) + "</span>";
    const body = tag + escapeHtml(e.text || "");
    if (e.detail && (e.detail.diff || e.kind === "meeting" || e.kind === "code" || e.kind === "rollback")) {
      return "<li class='border-l border-gold/30 pl-2'><details><summary class='flex cursor-pointer gap-1 text-sm leading-6'>" + head + "<span class='min-w-0'>" + body + "</span></summary>" +
        "<div class='ml-[5.5rem]'>" + diaryDetail(e.detail) + "</div></details></li>";
    }
    return "<li class='flex gap-1 border-l border-gold/30 pl-2 text-sm leading-6'>" + head + "<span class='min-w-0'>" + body + "</span></li>";
  }).join("");
}
function meetingCard(g, open) {
  const day = new Date(g.start * 1000);
  const title = day.toLocaleDateString(LOCALE, { weekday: "long", day: "2-digit", month: "2-digit" }) + " · " + timeOf(g.start).slice(0, 5) + "–" + timeOf(g.end).slice(0, 5);
  const chips = [
    g.up.length ? "<span class='rounded bg-emerald-400/10 px-1.5 text-emerald-300'>⬆️ " + g.up.length + " lên tiền thật</span>" : "",
    g.down.length ? "<span class='rounded bg-sky-400/10 px-1.5 text-sky-300'>⬇️ " + g.down.length + " xuống bàn giấy</span>" : "",
    g.code ? "<span class='rounded bg-gold/10 px-1.5 text-gold'>🛠 " + g.code + " sửa mã</span>" : "",
    g.rollback ? "<span class='rounded bg-rose-400/10 px-1.5 text-rose-300'>↩️ " + g.rollback + " khôi phục</span>" : "",
    g.interrupted ? "<span class='rounded bg-amber-400/10 px-1.5 text-amber-300'>bị gián đoạn</span>" : "",
    g.failed ? "<span class='rounded bg-rose-400/10 px-1.5 text-rose-300'>không họp được</span>" : "",
  ].filter(Boolean).join(" ");
  return "<li class='rounded-lg border border-line bg-black/20'><details" + (open ? " open" : "") + "><summary class='cursor-pointer px-3 py-2'>" +
    "<div class='flex flex-wrap items-center justify-between gap-2'><span class='text-sm font-semibold text-zinc-100'>🗓 " + escapeHtml(title) + "</span><span class='flex flex-wrap gap-1 text-[11px]'>" + chips + "</span></div>" +
    (g.summary ? "<p class='mt-1 text-xs leading-5 text-zinc-400'>" + escapeHtml(g.summary) + "</p>" : "") + "</summary>" +
    "<div class='border-t border-line px-3 py-2'><p class='metric-label'>Diễn biến cuộc họp</p><ol class='mt-1 space-y-0.5'>" + timelineHtml(g.entries) + "</ol></div></details></li>";
}
let meetingGroups = [];
async function loadDiary() {
  try {
    const [groups, arb, meet] = await Promise.all([
      fetch(apiBase + "/api/meetings?limit=20").then((r) => r.json()),
      fetch(apiBase + "/api/manager-log?limit=60&kind=arbitration").then((r) => r.json()),
      fetch(apiBase + "/api/meeting").then((r) => r.json()),
    ]);
    meetingGroups = groups.meetings || [];
    const last = (meet.history || [])[0];
    const running = meet.status && meet.status.running;
    document.getElementById("meeting-status").textContent = running ? "Đang họp: " + (meet.status.step || "") : last ? "Lần gần nhất " + last.date : "";
    document.querySelectorAll("[data-meeting-state]").forEach((node) => {
      node.textContent = running ? "Đang họp: " + (meet.status.step || "") : last ? "Họp gần nhất " + last.date + ": " + (last.summary || "").slice(0, 140) : "Chưa họp lần nào.";
    });
    document.getElementById("meeting-summary").textContent = last ? last.summary || "" : "Chưa có cuộc họp nào.";
    document.getElementById("meeting-changes").innerHTML = last ? [
      ...(last.changes || []).map((c) => "<li>" + (c.real ? "⬆️ Lên tiền thật: " : "⬇️ Xuống bàn giấy: ") + escapeHtml(c.name) + " — " + escapeHtml(c.reason || "") + "</li>"),
      ...(last.improvements || []).map((i) => "<li>🛠 " + escapeHtml(i.name || i.id) + ": " + escapeHtml(i.statusText || "") + "</li>"),
      last.restart ? "<li>🔄 " + escapeHtml(last.restart) + "</li>" : "",
    ].join("") : "";
    const list = document.getElementById("meeting-list");
    const opened = new Set([...list.querySelectorAll("details[open]")].map((d) => d.closest("li") && d.closest("li").dataset.id));
    list.innerHTML = meetingGroups.map((g) => meetingCard(g, opened.has(g.id)).replace("<li ", "<li data-id='" + escapeHtml(g.id) + "' ")).join("") ||
      "<li class='text-xs text-zinc-500'>Chưa có cuộc họp nào. Bấm \"Họp ngay\" hoặc chờ 5:10 sáng.</li>";
    document.getElementById("arbitration-list").innerHTML = (arb.items || []).map((row) =>
      "<li class='rounded border border-line bg-black/20 px-2 py-1'><span class='text-zinc-500'>" + new Date(row.at * 1000).toLocaleString(LOCALE, { hour12: false }) + "</span> ⚖️ " + escapeHtml(row.text) + "</li>"
    ).join("") || "<li class='text-zinc-500'>Hôm nay chưa có lần nào nhiều agent báo cùng nến.</li>";
  } catch (_error) {
    /* keep the last view */
  }
}
document.addEventListener("click", async (event) => {
  const button = event.target.closest ? event.target.closest("[data-meeting-run]") : null;
  if (!button) return;
  event.preventDefault();
  const ok = await confirmDialog("Họp ngay",
    "Trưởng phòng họp ngay bây giờ?\nClaude CLI sẽ quyết định agent nào lên tiền thật, agent nào xuống phòng nghiên cứu, và có thể sửa mã nguồn của agent cần cải tiến.\nMọi bước được ghi vào nhật ký trưởng phòng.", "Họp ngay");
  if (!ok) return;
  if (typeof OfficeGame !== "undefined") OfficeGame.closeMenu();
  const result = await fetch(apiBase + "/api/meeting/run", { method: "POST" }).then((r) => r.json()).catch(() => ({ message: "Lỗi kết nối" }));
  document.getElementById("meeting-status").textContent = result.message || "";
  document.querySelectorAll("[data-meeting-state]").forEach((node) => { node.textContent = result.message || ""; });
  openMeetingDialog();
  loadDiary();
});
document.addEventListener("click", (event) => {
  if (event.target.closest && event.target.closest("[data-meeting-watch]")) { event.preventDefault(); openMeetingDialog(); }
});
let meetingTimer = null;
function paintMeeting(meet) {
  const status = meet.status || {};
  const running = !!status.running;
  const last = (meet.history || [])[0];
  const result = status.result || (!running ? last : null);
  if (!running && !status.result && meetingGroups[0]) {
    document.getElementById("mdlg-state").textContent = "";
  }
  document.getElementById("mdlg-spin").hidden = !running;
  document.getElementById("mdlg-state").textContent = running
    ? "Đang họp (bắt đầu " + (status.startedAt || "") + ") · " + (status.step || "")
    : result ? "Đã họp xong · " + (result.date || "") : "Chưa có cuộc họp nào.";
  const events = running || (status.events || []).length ? status.events || [] : ((meetingGroups[0] || {}).entries || []);
  document.getElementById("mdlg-events").innerHTML = events.length
    ? timelineHtml(events)
    : "<li class='text-zinc-500'>" + (running ? "Đang khởi động…" : "Chưa có cuộc họp nào.") + "</li>";
  const box = document.getElementById("mdlg-result");
  box.hidden = running || !result;
  if (!running && result) {
    document.getElementById("mdlg-summary").textContent = result.summary || "";
    const lines = [
      ...(result.changes || []).map((c) => "<li>" + (c.real ? "⬆️ <b class='text-emerald-300'>Lên tiền thật</b>: " : "⬇️ <b class='text-sky-300'>Xuống bàn giấy</b>: ") + escapeHtml(c.name) + " — " + escapeHtml(c.reason || "") + "</li>"),
      ...(result.improvements || []).map((i) => "<li>🛠 <b>" + escapeHtml(i.name || i.id) + "</b>: " + escapeHtml(i.statusText || "") + "</li>"),
      result.restart ? "<li>🔄 " + escapeHtml(result.restart) + "</li>" : "",
    ].filter(Boolean);
    document.getElementById("mdlg-changes").innerHTML = lines.join("") || "<li class='text-zinc-400'>Không đổi agent nào, không sửa mã.</li>";
  }
  const list = document.getElementById("mdlg-events");
  list.lastElementChild && list.lastElementChild.scrollIntoView({ block: "nearest" });
  return running;
}
async function pollMeeting() {
  const meet = await fetch(apiBase + "/api/meeting").then((r) => r.json()).catch(() => null);
  if (!meet) return;
  const running = paintMeeting(meet);
  if (!running && meetingTimer) {
    window.clearInterval(meetingTimer);
    meetingTimer = null;
    loadDiary();
    pollLive();
  }
}
async function openMeetingDialog() {
  const dialog = document.getElementById("meeting-dialog");
  if (!dialog.open) dialog.showModal();
  await loadDiary();
  pollMeeting();
  if (!meetingTimer) meetingTimer = window.setInterval(pollMeeting, 2000);
}
document.getElementById("meeting-dialog").addEventListener("close", () => {
  if (meetingTimer) { window.clearInterval(meetingTimer); meetingTimer = null; }
});
window.setInterval(loadDiary, 30000);
loadDiary();
pollLive();
loadTelegram();
loadSignalModel();
document.querySelectorAll(".tf-btn").forEach((button) => {
  button.classList.add(button.dataset.tf === "M15" ? "bg-gold/15" : "text-zinc-400");
  if (button.dataset.tf === "M15") button.classList.add("text-gold");
});
