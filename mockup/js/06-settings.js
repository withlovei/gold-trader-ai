const apiBase = window.location.port === "8787" ? "" : "http://127.0.0.1:8787";

async function loadMt5Settings() {
  try {
    const response = await fetch(apiBase + "/api/settings/mt5");
    if (!response.ok) {
      return;
    }
    const data = await response.json();
    document.getElementById("mt5-path").value = data.terminalPath || "";
    document.getElementById("mt5-server").value = data.server || "";
    document.getElementById("mt5-login").value = data.login || "";
    document.getElementById("mt5-symbol").value = data.symbol || "XAUUSDm";
    const password = document.getElementById("mt5-password");
    password.value = "";
    password.placeholder = data.hasPassword ? "Đã lưu. Để trống nếu không đổi." : "Nhập mật khẩu Exness";
    document.getElementById("settings-status").textContent = data.hasPassword
      ? "Đã có mật khẩu trên máy này."
      : "Chưa lưu mật khẩu.";
  } catch (_error) {
    document.getElementById("settings-status").textContent = "Dịch vụ kết nối chưa chạy.";
  }
}

document.getElementById("settings-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const status = document.getElementById("settings-status");
  status.textContent = "Đang kết nối MetaTrader...";
  try {
    const response = await fetch(apiBase + "/api/mt5/connect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        terminalPath: document.getElementById("mt5-path").value,
        server: document.getElementById("mt5-server").value,
        login: document.getElementById("mt5-login").value,
        password: document.getElementById("mt5-password").value,
        symbol: document.getElementById("mt5-symbol").value,
      }),
    });
    const data = await response.json();
    if (data.ok) {
      document.getElementById("mt5-password").value = "";
      document.getElementById("mt5-password").placeholder = "Đã lưu. Để trống nếu không đổi.";
      status.textContent = "Đã vào tài khoản " + data.login + ". Số dư " + data.balance + " " + data.currency + ".";
      toast("Đã kết nối MetaTrader.");
      return;
    }
    status.textContent = data.message || "Không kết nối được.";
    toast(status.textContent);
  } catch (_error) {
    status.textContent = "Không gọi được dịch vụ kết nối.";
    toast(status.textContent);
  }
});
function riskNumber(value) {
  return Number(value).toLocaleString(LOCALE, { maximumFractionDigits: 2 });
}

function fillRiskForm(limits) {
  document.getElementById("risk-per-trade").value = limits.perTradePercent;
  document.getElementById("risk-daily").value = limits.dailyLossPercent;
  document.getElementById("risk-dd").value = limits.drawdownPercent;
  document.getElementById("risk-positions").value = limits.maxPositions;
  document.getElementById("risk-streak").value = limits.maxLossStreak;
  document.getElementById("risk-rr").value = limits.minRewardRatio;
  document.getElementById("risk-minlot").value = limits.minLotPercent ?? 0;
  document.getElementById("risk-open").value = limits.maxOpenRiskPercent ?? 6;
}

function paintRiskUsage(usage) {
  if (!usage) return;
  const trade = usage.perTradePercent === null || usage.perTradePercent === undefined
    ? usage.perTradeNote || "—"
    : riskNumber(usage.perTradePercent) + "%";
  document.getElementById("risk-now-trade").textContent = trade;
  document.getElementById("risk-now-daily").textContent = riskNumber(usage.dailyLossPercent) + "%";
  document.getElementById("risk-now-dd").textContent = riskNumber(usage.drawdownPercent) + "%";
  document.getElementById("risk-now-positions").textContent = String(usage.positions);
  document.getElementById("risk-now-streak").textContent = String(usage.lossStreak);
  const ratio = usage.planRewardRatio;
  document.getElementById("risk-now-rr").textContent = ratio ? "1 : " + riskNumber(ratio) : "chưa có kế hoạch";
  document.getElementById("risk-now-minlot").textContent = usage.planRiskPercent === null || usage.planRiskPercent === undefined
    ? "chưa có kế hoạch"
    : "0,01 lot của kế hoạch này = " + riskNumber(usage.planRiskPercent) + "% vốn";
  const status = document.getElementById("risk-status");
  if (status.textContent === "Đang đọc tài khoản...") status.textContent = "Số bên trái cập nhật theo tài khoản.";
}

async function loadRiskSettings() {
  try {
    const response = await fetch(apiBase + "/api/settings/risk");
    if (!response.ok) return;
    fillRiskForm(await response.json());
  } catch (_error) {
    document.getElementById("risk-status").textContent = "Chưa đọc được giới hạn.";
  }
}

document.getElementById("risk-default").addEventListener("click", async () => {
  const status = document.getElementById("risk-status");
  status.textContent = "Đang tính mức phù hợp với tài khoản...";
  try {
    const response = await fetch(apiBase + "/api/settings/risk/default", { method: "POST" });
    const data = await response.json();
    if (!data.ok) {
      status.textContent = data.message || "Không đặt được mức mặc định.";
      return;
    }
    fillRiskForm(data);
    status.textContent = data.reason || "Đã đặt mức mặc định.";
    toast("Đã đặt giới hạn mặc định.");
  } catch (_error) {
    status.textContent = "Không gọi được dịch vụ rủi ro.";
  }
});

document.getElementById("risk-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const status = document.getElementById("risk-status");
  status.textContent = "Đang lưu...";
  try {
    const response = await fetch(apiBase + "/api/settings/risk", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        perTradePercent: Number(document.getElementById("risk-per-trade").value),
        dailyLossPercent: Number(document.getElementById("risk-daily").value),
        drawdownPercent: Number(document.getElementById("risk-dd").value),
        maxPositions: Number(document.getElementById("risk-positions").value),
        maxLossStreak: Number(document.getElementById("risk-streak").value),
        minRewardRatio: Number(document.getElementById("risk-rr").value),
        minLotPercent: Number(document.getElementById("risk-minlot").value),
        maxOpenRiskPercent: Number(document.getElementById("risk-open").value),
      }),
    });
    const data = await response.json();
    if (!data.ok) {
      status.textContent = "Không lưu được giới hạn.";
      return;
    }
    fillRiskForm(data);
    status.textContent = "Đã lưu. Lần chấm sau dùng các giới hạn này.";
    toast("Đã lưu giới hạn rủi ro.");
  } catch (_error) {
    status.textContent = "Không gọi được dịch vụ rủi ro.";
  }
});
loadMt5Settings();
loadRiskSettings();
document.querySelectorAll("[data-mock]").forEach((button) => {
  button.addEventListener("click", () => toast("Chỉ là bản xem thử. " + button.dataset.mock + " chưa được nối."));
});
