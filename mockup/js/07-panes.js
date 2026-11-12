const paneNotes = {
  positions: "1 lệnh đang mở · quyết định CHỜ không được gửi",
  history: "Mỗi nến M15 (và M30 của sổ phụ) đóng lưu một dòng. XH = Theo xu hướng, HG = Hồi giá: số điều kiện vào lệnh đã đạt trên tổng số. Cột Dừng ở đâu ghi điều kiện đầu tiên chưa đạt.",
};
function setDecisionDrawer(open) {
  const drawer = document.getElementById("decision-drawer");
  if (!drawer) return;
  drawer.classList.toggle("hidden", !open);
}
document.getElementById("decision-open").addEventListener("click", () => setDecisionDrawer(true));
document.getElementById("decision-close").addEventListener("click", () => setDecisionDrawer(false));
document.getElementById("decision-backdrop").addEventListener("click", () => setDecisionDrawer(false));
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") setDecisionDrawer(false);
});
document.querySelectorAll(".pane-btn").forEach((button) => {
  button.addEventListener("click", () => {
    const name = button.dataset.pane;
    document.getElementById("pane-positions").classList.toggle("hidden", name !== "positions");
    document.getElementById("pane-history").classList.toggle("hidden", name !== "history");
    document.getElementById("pane-note").textContent = paneNotes[name];
    document.querySelectorAll(".pane-btn").forEach((item) => {
      const active = item === button;
      item.classList.toggle("bg-white/5", active);
      item.classList.toggle("text-gold", active);
      item.classList.toggle("text-zinc-400", !active);
    });
  });
});
