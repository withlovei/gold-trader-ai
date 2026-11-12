async function loadSignalModel() {
  try {
    const response = await fetch(apiBase + "/api/models/signal");
    paintSignalModel(await response.json());
  } catch (_error) {
    document.getElementById("signal-status").textContent = "Không đọc được mô hình.";
  }
}
function paintSignalModel(data) {
  const modes = data.modes || { off: "Tắt", shadow: "Chỉ ghi điểm", size: "Giảm nửa khối lượng khi điểm thấp" };
  const notesByMode = {
    off: "Không chấm điểm.",
    shadow: "Chấm và ghi điểm vào sổ lệnh, không đổi khối lượng.",
    size: "Điểm dưới ngưỡng thì vào nửa khối lượng.",
  };
  document.getElementById("signal-modes").innerHTML = Object.keys(modes).map((key) => {
    const active = key === data.mode;
    return '<button type="button" data-signal-mode="' + key + '" class="rounded-lg border px-3 py-2 text-left text-sm ' +
      (active ? "border-gold/50 bg-gold/10 text-gold" : "border-line text-zinc-300 hover:bg-white/[0.04]") + '">' +
      '<span class="font-semibold">' + escapeHtml(modes[key]) + '</span><span class="block text-[11px] text-zinc-500">' + notesByMode[key] + "</span></button>";
  }).join("");
  document.querySelectorAll("[data-signal-mode]").forEach((button) => {
    button.addEventListener("click", async () => {
      const response = await fetch(apiBase + "/api/settings/model", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mode: button.dataset.signalMode }),
      });
      const saved = await response.json();
      if (saved.ok) { toast("Chế độ mô hình: " + saved.label); loadSignalModel(); }
    });
  });
  const chipText = { off: "Mô hình: tắt", shadow: "Mô hình: ghi điểm", size: "Mô hình: giảm KL" };
  const due = data.due && data.mode !== "off";
  document.getElementById("chip-model").textContent = !data.ok ? "Mô hình: chưa có" : due ? "Mô hình: cần huấn luyện" : chipText[data.mode] || "Mô hình";
  document.getElementById("chip-model").parentElement.classList.toggle("2xl:inline-flex", !due);
  document.getElementById("chip-model").parentElement.classList.toggle("lg:inline-flex", due);
  setDot("dot-model", due ? "warn" : data.ok && data.mode !== "off" ? "ok" : "");
  const banner = document.getElementById("signal-due");
  banner.classList.toggle("hidden", !due);
  if (due) {
    banner.textContent = data.ageDays === null || data.ageDays === undefined
      ? "Chưa có mô hình. Bấm Huấn luyện lại."
      : "Đã đến lịch huấn luyện hằng tháng: mô hình đã " + Math.round(data.ageDays) + " ngày tuổi. Bấm Huấn luyện lại (cần MetaTrader đang mở).";
  }
  if (!data.ok) {
    document.getElementById("signal-status").textContent = data.message || "Chưa huấn luyện. Bấm Huấn luyện lại.";
    return;
  }
  document.getElementById("signal-status").textContent =
    "Huấn luyện lúc " + data.trainedAt + ". Lịch huấn luyện lại: " + data.nextTraining + ". Ngưỡng điểm " + (data.threshold * 100).toFixed(0) + "%. " +
    data.signals + " tín hiệu (M15 " + data.byTimeframe.M15 + ", M30 " + data.byTimeframe.M30 + ", H1 " + data.byTimeframe.H1 + ").";
  document.getElementById("signal-meta").textContent = data.from + " → " + data.to + " · thắng " + (data.winRate * 100).toFixed(0) + "% · " + signed(data.averageR, 3) + "R/lệnh";
  document.getElementById("signal-message").textContent = data.message || "";
  const r = (v) => (v === null || v === undefined ? "—" : '<span class="' + tone(v) + '">' + signed(v, 3) + "</span>");
  document.getElementById("signal-folds").innerHTML = (data.folds || []).map((row) =>
    "<tr><td class=\"py-2 pr-3 font-mono\">" + row.year + "</td><td class=\"py-2 pr-3 font-mono\">" + row.signals +
    "</td><td class=\"py-2 pr-3 font-mono\">" + r(row.averageR) + "</td><td class=\"py-2 pr-3 font-mono\">" + r(row.highR) +
    " <span class=\"text-zinc-500\">(" + Math.round(row.highShare * 100) + "%)</span></td><td class=\"py-2 pr-3 font-mono\">" + r(row.lowR) +
    "</td><td class=\"py-2 pr-3 font-mono\">" + r(row.sizedR) + "</td></tr>").join("") || '<tr class="empty-row"><td colspan="6">Chưa đủ năm để kiểm định.</td></tr>';
  const drivers = data.drivers || [];
  const peak = Math.max(...drivers.map((d) => Math.abs(d.weight)), 0.001);
  document.getElementById("signal-drivers").innerHTML = drivers.map((d) => {
    const width = Math.round((Math.abs(d.weight) / peak) * 100);
    const color = d.weight >= 0 ? "bg-emerald-400/70" : "bg-rose-400/70";
    return '<div><div class="flex justify-between text-xs"><span class="text-zinc-300">' + escapeHtml(d.label) +
      '</span><span class="font-mono text-zinc-500">' + signed(d.weight, 2) + '</span></div><div class="mt-1 h-1.5 rounded-full bg-white/5"><div class="h-full rounded-full ' +
      color + '" style="width:' + width + '%"></div></div></div>';
  }).join("");
}
document.getElementById("signal-train").addEventListener("click", async () => {
  const button = document.getElementById("signal-train");
  const status = document.getElementById("signal-status");
  button.disabled = true;
  status.textContent = "Đang đọc lịch sử M15, M30, H1 từ MetaTrader và huấn luyện…";
  try {
    const response = await fetch(apiBase + "/api/models/signal/train", { method: "POST" });
    const data = await response.json();
    if (!data.ok) { status.textContent = data.message || "Huấn luyện thất bại."; return; }
    toast("Đã huấn luyện mô hình chấm tín hiệu.");
    loadSignalModel();
  } catch (_error) {
    status.textContent = "Không gọi được dịch vụ huấn luyện.";
  } finally {
    button.disabled = false;
  }
});
const unlockButton = document.getElementById("drawdown-unlock");
let unlockArmed = false;
unlockButton.addEventListener("click", async () => {
  if (!unlockArmed) {
    unlockArmed = true;
    unlockButton.textContent = "Bấm lần nữa để xác nhận";
    window.setTimeout(() => {
      unlockArmed = false;
      unlockButton.textContent = "Mở khóa sụt giảm";
    }, 5000);
    return;
  }
  unlockArmed = false;
  unlockButton.textContent = "Mở khóa sụt giảm";
  try {
    const response = await fetch(apiBase + "/api/risk/unlock", { method: "POST" });
    const data = await response.json();
    toast(data.message || "Đã mở khóa.");
    pollLive();
  } catch (_error) {
    toast("Không gọi được dịch vụ mở khóa.");
  }
});
function percent(value) {
  if (value === null || value === undefined) return "Không có mẫu";
  return (value * 100).toFixed(1) + "%";
}

function renderTrainResult(data) {
  const root = document.getElementById("train-result");
  if (!data.ok) {
    root.innerHTML = '<article class="rounded-xl border border-rose-500/40 bg-panel p-4 text-sm text-rose-200">' + (data.message || "Huấn luyện thất bại.") + "</article>";
    return;
  }
  if (!data.models) {
    root.innerHTML = '<article class="rounded-xl border border-line bg-panel p-4 text-sm text-zinc-300">Bản kết quả cũ chỉ có LightGBM. Bấm Huấn luyện ngay để chạy đủ bốn mô hình.</article>';
    return;
  }
  const money = (stats) => {
    const factor = stats.profitFactor === null || stats.profitFactor === undefined ? "—" : stats.profitFactor;
    const win = percent(stats.winRate);
    return stats.trades + " lệnh · thắng " + win + " · lời trung bình " + Number(stats.average).toFixed(2) + " · hệ số lời " + factor;
  };
  const cards = data.models
    .map((model) => '<article class="rounded-xl border border-line bg-panel p-4"><p class="text-xs uppercase tracking-wider text-gold">' + model.name + '</p><p class="mt-1 text-xs text-zinc-500">' + model.role + '</p><p class="mt-3 text-sm text-zinc-100">' + model.value + "</p></article>")
    .join("");
  root.className = "grid gap-3 lg:grid-cols-2";
  root.innerHTML =
    cards +
    '<article class="rounded-xl border border-gold/40 bg-panel p-4 lg:col-span-2"><p class="text-xs uppercase tracking-wider text-gold">Quyết định hiện tại · ' + data.now.decision + '</p><p class="mt-2 text-sm text-zinc-200">' + data.message + '</p><p class="mt-2 text-sm text-zinc-400">Bản ghép: ' + money(data.ensemble) + "</p><p class=\"mt-1 text-sm text-zinc-400\">Chỉ LightGBM: " + money(data.lightgbmOnly) + "</p><p class=\"mt-2 text-xs text-zinc-500\">" + data.symbol + " · " + data.timeframe + " · chênh lệch " + data.spread + " · " + data.testSamples + " nến kiểm tra / " + data.samples + " mẫu · " + data.trainedAt + "</p></article>";
}

async function loadLatestModel() {
  try {
    const response = await fetch(apiBase + "/api/models/latest");
    if (!response.ok) return;
    const data = await response.json();
    if (data.ok) {
      renderTrainResult(data);
      document.getElementById("train-status").textContent = "Lần gần nhất " + data.trainedAt + ". Chưa gửi lệnh.";
    }
  } catch (_error) {
    document.getElementById("train-status").textContent = "Không đọc được kết quả cũ.";
  }
}

document.getElementById("train-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = document.getElementById("train-button");
  const status = document.getElementById("train-status");
  button.disabled = true;
  status.textContent = "Đang lấy nến và huấn luyện...";
  try {
    const response = await fetch(apiBase + "/api/models/train", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        timeframe: document.getElementById("train-timeframe").value,
        bars: Number(document.getElementById("train-bars").value),
      }),
    });
    const data = await response.json();
    renderTrainResult(data);
    status.textContent = data.ok ? "Xong. Bốn mô hình ở bên dưới. Chưa gửi lệnh." : data.message;
    if (data.ok) toast("Đã có kết quả huấn luyện.");
  } catch (_error) {
    status.textContent = "Không gọi được dịch vụ huấn luyện.";
  } finally {
    button.disabled = false;
  }
});
