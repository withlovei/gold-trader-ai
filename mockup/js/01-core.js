const notes = {
  analysis: "Chỉ xem. Quyết định hiện trên màn hình và không chuẩn bị lệnh.",
  signal: "Chế độ tín hiệu hiện điểm vào, cắt lỗ và chốt lời. Bạn tự đặt lệnh.",
  semi: "Duyệt tay chờ bạn bấm đồng ý. Nến này là CHỜ, nên không chuẩn bị lệnh.",
  full: "Tự động chấm mỗi khi nến M15 đóng (mỗi 15 phút), mọi agent ở chế độ tiền thật chạy song song dưới agent tổng (bật tắt từng agent trong \"Quản lý agent\"), chạy nền kể cả khi đóng trang. Lệnh chỉ gửi khi agent có tín hiệu và cổng rủi ro đạt.",
};
const pills = { analysis: "Chỉ xem", signal: "Tín hiệu", semi: "Duyệt tay", full: "Tự động" };
const navButtons = document.querySelectorAll(".nav-btn");
const screens = document.querySelectorAll(".screen");
const modeButtons = document.querySelectorAll(".mode-btn");

function showScreen(name) {
  screens.forEach((screen) => {
    screen.classList.toggle("hidden", screen.id !== "screen-" + name);
  });
  navButtons.forEach((button) => {
    button.classList.toggle("is-active", button.dataset.nav === name);
  });
  if (name === "dashboard") {
    const activeTf = document.querySelector(".tf-btn.text-gold");
    loadChart(activeTf ? activeTf.dataset.tf : "M15");
  }
  if (name === "models") {
    loadLatestModel();
    loadSignalModel();
  }
  if (name === "journal") loadJournal();
  if (name === "settings") loadTelegram();
  if (name === "strategies") {
    if (latestChart) renderStrategies(latestChart.strategy, latestChart);
    else loadChart(activeTimeframe);
  }
}

function strategyStatus(status) {
  if (status === "selected") return "Đang chọn";
  if (status === "ready") return "Đủ điều kiện";
  if (status === "blocked") return "Đang tắt";
  return "Đang chờ";
}
