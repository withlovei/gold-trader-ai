// ---------------------------------------------------------------- "Phòng làm việc" (canvas, game-style)
const OfficeGame = (() => {
  const W = 1100;
  let H = 480;
  // Compact floor: every agent on a small desk, real-money zone 7 per row beside the head of
  // desk, research room 9 per row; the whole floor is scaled to fit the visible window.
  const CELL = 150;
  const ROW = 110;
  const REAL_X = 332;
  const REAL_COLS = Math.floor((W - REAL_X - 16) / CELL);
  const LAB_COLS = Math.floor((W - 32) / CELL);
  let L = { compact: true, realH: 220, labTop: 318, labH: 150 };
  function layoutFor(staffCount, labCount) {
    const realRows = Math.max(1, Math.ceil(staffCount / REAL_COLS));
    const realH = Math.max(220, 40 + realRows * ROW);
    const labTop = 84 + realH + 10;
    const labH = 34 + Math.max(1, Math.ceil(labCount / LAB_COLS)) * ROW;
    return { compact: true, realH, labTop, labH, H: labTop + labH + 8 };
  }
  const PAL = {
    floor1: "#1b1d24", floor2: "#20232b", wall: "#14161c", wallLine: "#2a2d36", glass: "rgba(227,179,65,0.06)",
    glassEdge: "rgba(227,179,65,0.45)", lab: "rgba(56,189,248,0.05)", labEdge: "rgba(56,189,248,0.35)",
    deskTop: "#6b4f35", deskFront: "#4e3826", deskEdge: "#83623f", screen: "#0b1220", screenEdge: "#3f4656",
    text: "#e4e4e7", dim: "#71717a", gold: "#e3b341", green: "#34d399", red: "#fb7185", amber: "#fbbf24", blue: "#38bdf8",
  };
  const SKIN = ["#f1c7a3", "#e0ac84", "#c68b62", "#a86f4c", "#f5d5b8"];
  const HAIR = ["#2b1d14", "#4a3020", "#7a5230", "#bfa070", "#1f1f24", "#8a8a8a", "#a33b20"];
  let canvas = null;
  let ctx = null;
  let tip = null;
  let feed = null;
  let crew = null;
  let extra = { bid: null, closed: false };
  let running = false;
  let hits = [];
  let hover = null;
  let particles = [];
  let floaters = [];
  let lastStates = {};
  let events = [];
  const boss = { x: 165, y: 172, homeX: 165, homeY: 172, tx: 165, ty: 172, until: 0, say: "" };

  function hash(text) {
    let value = 0;
    for (const char of String(text || "")) value = (value * 31 + char.charCodeAt(0)) >>> 0;
    return value;
  }
  function short(text, max) {
    const clean = String(text || "").replace(/\s+/g, " ").trim();
    return clean.length > max ? clean.slice(0, max - 1) + "…" : clean;
  }
  function round(x, y, w, h, r, fill, stroke) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
    if (fill) { ctx.fillStyle = fill; ctx.fill(); }
    if (stroke) { ctx.strokeStyle = stroke; ctx.lineWidth = 1; ctx.stroke(); }
  }
  function label(text, x, y, color, size, weight, align) {
    ctx.font = (weight || 600) + " " + (size || 11) + "px Inter, system-ui, sans-serif";
    ctx.fillStyle = color || PAL.text;
    ctx.textAlign = align || "center";
    ctx.textBaseline = "middle";
    ctx.fillText(I18N.translate(text), x, y);
  }

  // ------------------------------------------------------------ scene
  function room() {
    for (let y = 70; y < H; y += 20) {
      for (let x = 0; x < W; x += 20) {
        ctx.fillStyle = ((x + y) / 20) % 2 ? PAL.floor1 : PAL.floor2;
        ctx.fillRect(x, y, 20, 20);
      }
    }
    ctx.fillStyle = PAL.wall;
    ctx.fillRect(0, 0, W, 70);
    ctx.fillStyle = PAL.wallLine;
    ctx.fillRect(0, 68, W, 3);
    // window with city
    round(24, 12, 150, 46, 4, "#0d1726", PAL.wallLine);
    for (let i = 0; i < 9; i += 1) {
      const h = 12 + (hash("b" + i) % 26);
      ctx.fillStyle = "#18263a";
      ctx.fillRect(30 + i * 16, 56 - h, 12, h);
      ctx.fillStyle = (Math.floor(performance.now() / 900) + i) % 3 ? "rgba(251,191,36,0.55)" : "rgba(251,191,36,0.15)";
      ctx.fillRect(33 + i * 16, 58 - h + 4, 3, 3);
    }
    // ticker board
    const mid = W / 2;
    round(mid - 140, 10, 280, 50, 6, "#07090d", PAL.gold);
    label("XAUUSD", mid - 80, 26, PAL.dim, 10, 600);
    label(extra.bid ? Number(extra.bid).toFixed(2) : "—", mid - 80, 44, PAL.gold, 18, 700);
    const risk = crew ? Number(crew.openRisk || 0).toFixed(2) + "% / " + Number(crew.openRiskCap || 6) + "%" : "—";
    label("RỦI RO MỞ", mid + 60, 26, PAL.dim, 10, 600);
    label(risk, mid + 60, 44, PAL.text, 14, 700);
    // clock + status lamp
    round(W - 180, 14, 150, 42, 6, "#07090d", PAL.wallLine);
    label(extra.closed ? "PHIÊN ĐÓNG" : "ĐANG GIAO DỊCH", W - 105, 27, extra.closed ? PAL.red : PAL.green, 10, 700);
    label(extra.time || "", W - 105, 44, PAL.text, 13, 600);
    // zones
    round(16, 84, 300, 220, 10, PAL.glass, PAL.glassEdge);
    label("PHÒNG TRƯỞNG PHÒNG", 166, 98, PAL.gold, 10, 700);
    round(REAL_X, 84, W - REAL_X - 16, L.realH, 10, "rgba(52,211,153,0.04)", "rgba(52,211,153,0.35)");
    label("BÀN GIAO DỊCH · TIỀN THẬT", (REAL_X + W - 16) / 2, 98, PAL.green, 10, 700);
    round(16, L.labTop, W - 32, L.labH, 10, PAL.lab, PAL.labEdge);
    label("PHÒNG NGHIÊN CỨU · LỆNH GIẤY", W / 2, L.labTop + 14, PAL.blue, 10, 700);
    // boss room: bookshelf + capital vault
    round(228, 112, 74, 70, 4, "#3b2a1c", "#5a4129");
    for (let shelf = 0; shelf < 3; shelf += 1) {
      ctx.fillStyle = "#5a4129";
      ctx.fillRect(230, 134 + shelf * 22, 70, 2);
      for (let book = 0; book < 6; book += 1) {
        ctx.fillStyle = ["#b45309", "#1d4ed8", "#047857", "#9f1239", "#a16207", "#6d28d9"][(book + shelf) % 6];
        ctx.fillRect(234 + book * 11, 118 + shelf * 22, 8, 16);
      }
    }
    round(30, 244, 100, 54, 6, "#2a2d36", "#52525b");
    ctx.strokeStyle = "#71717a";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(52, 271, 11, 0, Math.PI * 2);
    ctx.stroke();
    label("KÉT VỐN", 98, 256, PAL.dim, 8.5, 700);
    label(extra.equity ? "$" + Number(extra.equity).toLocaleString("en-US", { maximumFractionDigits: 0 }) : "—", 98, 272, PAL.gold, 12, 800);
    label("DD " + (extra.drawdown !== undefined ? (extra.drawdown * 100).toFixed(1) + "%" : "—"), 98, 287, PAL.dim, 8.5, 600);
    plant(300, 290);
    plant(W - 32, 84 + L.realH - 14);
    plant(W - 36, H - 18);
    cooler(W - 40, L.labTop + 40);
  }
  function plant(x, y) {
    ctx.fillStyle = "#5a3d28";
    ctx.fillRect(x - 7, y - 10, 14, 12);
    ctx.fillStyle = "#2f7d4f";
    for (let i = 0; i < 5; i += 1) {
      ctx.beginPath();
      ctx.ellipse(x - 8 + i * 4, y - 16 - (i % 2) * 5, 4, 8, (i - 2) * 0.4, 0, Math.PI * 2);
      ctx.fill();
    }
  }
  function cooler(x, y) {
    ctx.fillStyle = "#cbd5e1";
    ctx.fillRect(x - 8, y - 6, 16, 26);
    ctx.fillStyle = "rgba(56,189,248,0.55)";
    ctx.fillRect(x - 7, y - 22, 14, 16);
  }

  // ------------------------------------------------------------ people
  function person(x, y, look, pose, t, scale) {
    const s = scale || 1;
    const bob = pose === "sleep" ? 0 : Math.sin(t / 380 + look.seed) * 1.2;
    ctx.save();
    ctx.translate(x, y + bob);
    ctx.scale(s, s);
    // chair back
    ctx.fillStyle = "#30333d";
    round(-15, -6, 30, 30, 5, "#30333d");
    // body
    ctx.fillStyle = look.shirt;
    round(-13, 2, 26, 24, 7, look.shirt);
    if (look.tie) {
      ctx.fillStyle = look.tie;
      ctx.fillRect(-2, 4, 4, 14);
    }
    if (look.coat) {
      ctx.fillStyle = "#f4f4f5";
      ctx.fillRect(-13, 4, 6, 20);
      ctx.fillRect(7, 4, 6, 20);
    }
    // head
    const tilt = pose === "sleep" ? 5 : 0;
    ctx.fillStyle = look.skin;
    ctx.beginPath();
    ctx.arc(tilt, -8 + tilt, 10, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = look.hair;
    ctx.beginPath();
    ctx.arc(tilt, -11 + tilt, 10, Math.PI, Math.PI * 2);
    ctx.fill();
    if (look.goggles) {
      ctx.fillStyle = "rgba(56,189,248,0.7)";
      ctx.fillRect(-7 + tilt, -10 + tilt, 5, 3);
      ctx.fillRect(2 + tilt, -10 + tilt, 5, 3);
    }
    // eyes
    ctx.fillStyle = "#18181b";
    if (pose === "sleep") {
      ctx.fillRect(-5 + tilt, -6 + tilt, 4, 1);
      ctx.fillRect(2 + tilt, -6 + tilt, 4, 1);
    } else {
      const blink = Math.sin(t / 900 + look.seed * 3) > 0.97;
      ctx.fillRect(-5, -8, 2, blink ? 1 : 2);
      ctx.fillRect(3, -8, 2, blink ? 1 : 2);
    }
    // arms
    ctx.fillStyle = look.skin;
    if (pose === "cheer") {
      const up = Math.abs(Math.sin(t / 160)) * 6;
      ctx.fillRect(-19, -10 - up, 5, 14);
      ctx.fillRect(14, -10 - up, 5, 14);
    } else if (pose === "type") {
      const a = Math.sin(t / 90 + look.seed) > 0 ? 2 : 0;
      ctx.fillRect(-11, 22 - a, 7, 4);
      ctx.fillRect(4, 22 - (2 - a), 7, 4);
    } else if (pose === "stop") {
      ctx.fillRect(14, -4, 5, 12);
      ctx.fillRect(-11, 22, 7, 4);
    } else {
      ctx.fillRect(-11, 22, 7, 4);
      ctx.fillRect(4, 22, 7, 4);
    }
    ctx.restore();
  }
  function walker(x, y, look, t, moving) {
    ctx.save();
    ctx.translate(x, y);
    const swing = moving ? Math.sin(t / 110) * 4 : 0;
    ctx.fillStyle = "#1f2937";
    ctx.fillRect(-6, 18, 5, 12 + swing / 2);
    ctx.fillRect(1, 18, 5, 12 - swing / 2);
    round(-12, -2, 24, 22, 7, look.shirt);
    ctx.fillStyle = look.tie;
    ctx.fillRect(-2, 0, 4, 13);
    ctx.fillStyle = look.skin;
    ctx.fillRect(-16, 2 + swing, 4, 12);
    ctx.fillRect(12, 2 - swing, 4, 12);
    ctx.beginPath();
    ctx.arc(0, -12, 10, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = look.hair;
    ctx.beginPath();
    ctx.arc(0, -15, 10, Math.PI, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#18181b";
    ctx.fillRect(-5, -12, 2, 2);
    ctx.fillRect(3, -12, 2, 2);
    ctx.restore();
  }
  function starLine(agent, x, y) {
    const stars = Number(agent.stars || 0);
    const trades = Number(agent.trades || 0);
    const text = "★".repeat(stars) + "☆".repeat(5 - stars);
    ctx.font = "700 10px Inter, system-ui, sans-serif";
    const starsW = ctx.measureText(text).width;
    ctx.font = "600 8.5px Inter, system-ui, sans-serif";
    const tail = " · " + trades + " lệnh";
    const tailW = ctx.measureText(tail).width;
    const left = x - (starsW + tailW) / 2;
    label(text, left + starsW / 2, y, stars ? PAL.gold : "#3f3f46", 10, 700);
    label(tail, left + starsW + tailW / 2, y, trades ? PAL.text : PAL.dim, 8.5, 600);
  }
  function desk(x, y, w, color, name, sub) {
    round(x - w / 2, y + 18, w, 12, 3, PAL.deskTop, PAL.deskEdge);
    ctx.fillStyle = PAL.deskFront;
    ctx.fillRect(x - w / 2 + 4, y + 30, w - 8, 22);
    round(x - 46, y + 33, 92, 16, 3, "#111318", color);
    label(name, x, y + 41, color, 9.5, 700);
    if (sub) label(sub, x, y + 60, PAL.dim, 9, 500);
  }
  function monitor(x, y, w, h, draw) {
    round(x, y, w, h, 3, PAL.screen, PAL.screenEdge);
    ctx.fillStyle = PAL.screenEdge;
    ctx.fillRect(x + w / 2 - 3, y + h, 6, 6);
    ctx.save();
    ctx.beginPath();
    ctx.rect(x + 2, y + 2, w - 4, h - 4);
    ctx.clip();
    draw(x + 2, y + 2, w - 4, h - 4);
    ctx.restore();
  }
  function sparkline(x, y, w, h, color, t, seed) {
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    for (let i = 0; i <= 16; i += 1) {
      const v = Math.sin((i + t / 400 + seed) * 0.9) * 0.3 + Math.sin((i + seed) * 2.3) * 0.2;
      const px = x + (i / 16) * w;
      const py = y + h / 2 - v * h;
      if (i) ctx.lineTo(px, py); else ctx.moveTo(px, py);
    }
    ctx.stroke();
  }
  function bubble(x, y, text, color, t) {
    const lift = Math.sin(t / 300) * 1.5;
    ctx.font = "700 11px Inter, system-ui, sans-serif";
    text = I18N.translate(text);
    const w = Math.max(22, ctx.measureText(text).width + 14);
    round(x - w / 2, y - 22 + lift, w, 18, 8, "#f4f4f5");
    ctx.beginPath();
    ctx.moveTo(x - 4, y - 4 + lift);
    ctx.lineTo(x + 4, y - 4 + lift);
    ctx.lineTo(x, y + 2 + lift);
    ctx.fillStyle = "#f4f4f5";
    ctx.fill();
    label(text, x, y - 13 + lift, color, 11, 700);
  }

  // ------------------------------------------------------------ actors
  function lookOf(alias, color, kind) {
    const seed = hash(alias);
    return {
      seed: (seed % 100) / 10, skin: SKIN[seed % SKIN.length], hair: HAIR[(seed >> 3) % HAIR.length],
      shirt: color, tie: kind === "boss" ? PAL.gold : null, coat: kind === "lab", goggles: kind === "lab" && seed % 2 === 0,
    };
  }
  function stateOfDesk(agent) {
    const act = agent.activity || {};
    if (extra.closed) return { key: "sleep", pose: "sleep", bubble: "Zz", color: PAL.blue, line: "Phiên đóng, đang nghỉ." };
    const pos = (agent.positions || [])[0];
    if (pos) return { key: "holding", pose: "type", bubble: (pos.profit >= 0 ? "+" : "") + Number(pos.profit).toFixed(2) + "$", color: pos.profit >= 0 ? PAL.green : PAL.red, line: act.text };
    if (act.state === "sent") return { key: "sent", pose: "cheer", bubble: "VÀO LỆNH!", color: PAL.green, line: act.text };
    if (act.state === "blocked") return { key: "blocked", pose: "stop", bubble: "BỊ CHẶN", color: PAL.red, line: act.text };
    if (act.state === "waiting") return { key: "waiting", pose: "type", bubble: "…", color: PAL.amber, line: act.text };
    return { key: "idle", pose: "idle", bubble: "", color: PAL.dim, line: act.text };
  }
  function stateOfLab(agent) {
    if (agent.stage === "draft") return { key: "draft", pose: "idle", bubble: "?", color: PAL.dim, line: "Chưa triển khai: mới có khung, chưa viết luật." };
    if (extra.closed) return { key: "sleep", pose: "sleep", bubble: "Zz", color: PAL.blue, line: "Phiên đóng, đang nghỉ." };
    if (agent.signal) return { key: "signal", pose: "cheer", bubble: "! " + agent.signal, color: PAL.amber, line: agent.activity };
    return { key: "watch", pose: "type", bubble: "", color: PAL.dim, line: agent.activity };
  }
  function gateScore(gates) {
    const counted = (gates || []).filter((gate) => gate.state !== "skip");
    return [counted.filter((gate) => gate.state === "ok").length, counted.length];
  }

  function drawDeskAgent(agent, x, y, t) {
    const color = agentColor(agent.id);
    const st = stateOfDesk(agent);
    const look = lookOf(agent.alias, color, "desk");
    person(x, y, look, st.pose, t, 1.15);
    // monitor at the side, screen toward the viewer
    monitor(x - 92, y - 22, 64, 42, (sx, sy, sw, sh) => {
      if (st.key === "holding") {
        sparkline(sx, sy + 4, sw, sh - 14, st.color, t, look.seed);
        label(st.bubble, sx + sw / 2, sy + sh - 6, st.color, 9, 700);
      } else if (st.key === "sent") {
        ctx.fillStyle = Math.floor(t / 250) % 2 ? "rgba(52,211,153,0.35)" : "rgba(52,211,153,0.1)";
        ctx.fillRect(sx, sy, sw, sh);
        label("VÀO LỆNH", sx + sw / 2, sy + sh / 2, PAL.green, 9, 800);
      } else if (st.key === "blocked") {
        label("✗ CHẶN", sx + sw / 2, sy + sh / 2, PAL.red, 10, 800);
      } else if (st.key === "sleep") {
        label("—", sx + sw / 2, sy + sh / 2, PAL.dim, 10, 600);
      } else {
        const [ok, total] = gateScore(agent.gates);
        label("ĐIỀU KIỆN", sx + sw / 2, sy + 8, PAL.dim, 7.5, 700);
        ctx.fillStyle = "rgba(255,255,255,0.1)";
        ctx.fillRect(sx + 6, sy + 18, sw - 12, 6);
        ctx.fillStyle = color;
        ctx.fillRect(sx + 6, sy + 18, (sw - 12) * (total ? ok / total : 0), 6);
        label(ok + "/" + total, sx + sw / 2, sy + 32, PAL.text, 9, 700);
      }
    });
    desk(x - 20, y, 190, color, agent.alias || agent.name, agent.name);
    starLine(agent, x - 20, y + 74);
    if (st.bubble) bubble(x, y - 24, st.bubble, st.color, t);
    hits.push({ x: x - 110, y: y - 50, w: 190, h: 120, kind: "desk", agent, st });
    if (lastStates[agent.id] && lastStates[agent.id] !== st.key) onChange(agent, st, x, y);
    lastStates[agent.id] = st.key;
    if (st.key === "holding" && Math.random() < 0.004) floaters.push({ x: x + 20, y: y - 30, text: st.bubble, color: st.color, life: 1 });
  }
  function drawSmallDesk(agent, x, y, t) {
    const color = agentColor(agent.id);
    const st = stateOfDesk(agent);
    const look = lookOf(agent.alias, color, "desk");
    person(x, y, look, st.pose, t, 0.85);
    monitor(x - 66, y - 14, 42, 28, (sx, sy, sw, sh) => {
      if (st.key === "holding") {
        sparkline(sx, sy + 3, sw, sh - 8, st.color, t, look.seed);
      } else if (st.key === "sent") {
        ctx.fillStyle = Math.floor(t / 250) % 2 ? "rgba(52,211,153,0.35)" : "rgba(52,211,153,0.1)";
        ctx.fillRect(sx, sy, sw, sh);
        label("VÀO", sx + sw / 2, sy + sh / 2, PAL.green, 8.5, 800);
      } else if (st.key === "blocked") {
        label("✗", sx + sw / 2, sy + sh / 2, PAL.red, 11, 800);
      } else if (st.key === "sleep") {
        label("—", sx + sw / 2, sy + sh / 2, PAL.dim, 10, 600);
      } else {
        const [ok, total] = gateScore(agent.gates);
        ctx.fillStyle = "rgba(255,255,255,0.1)";
        ctx.fillRect(sx + 4, sy + 8, sw - 8, 4);
        ctx.fillStyle = color;
        ctx.fillRect(sx + 4, sy + 8, (sw - 8) * (total ? ok / total : 0), 4);
        label(total ? ok + "/" + total : "…", sx + sw / 2, sy + 19, PAL.text, 7.5, 700);
      }
    });
    round(x - 70, y + 14, 140, 9, 3, PAL.deskTop, PAL.deskEdge);
    ctx.fillStyle = PAL.deskFront;
    ctx.fillRect(x - 66, y + 23, 132, 14);
    ctx.fillStyle = color;
    ctx.fillRect(x - 66, y + 23, 3, 14);
    label(short(agent.alias || agent.name, 18), x, y + 30, PAL.text, 9, 700);
    label(short(agent.name, 26), x, y + 46, PAL.dim, 8, 500);
    starLine(agent, x, y + 59);
    if (st.bubble) bubble(x, y - 20, short(st.bubble, 16), st.color, t);
    hits.push({ x: x - 72, y: y - 40, w: 144, h: 92, kind: "desk", agent, st });
    if (lastStates[agent.id] && lastStates[agent.id] !== st.key) onChange(agent, st, x, y);
    lastStates[agent.id] = st.key;
  }
  function drawLabAgent(agent, x, y, t) {
    const st = stateOfLab(agent);
    const look = lookOf(agent.alias, "#3f6f8f", "lab");
    if (st.key !== "draft") person(x, y, look, st.pose, t, 0.8);
    else {
      ctx.globalAlpha = 0.45;
      person(x, y, look, "idle", t, 0.8);
      ctx.globalAlpha = 1;
    }
    monitor(x - 64, y - 14, 40, 28, (sx, sy, sw, sh) => {
      if (st.key === "signal") {
        ctx.fillStyle = Math.floor(t / 300) % 2 ? "rgba(251,191,36,0.35)" : "rgba(251,191,36,0.1)";
        ctx.fillRect(sx, sy, sw, sh);
        label(agent.signal || "!", sx + sw / 2, sy + sh / 2, PAL.amber, 8.5, 800);
      } else if (st.key === "draft") {
        label("?", sx + sw / 2, sy + sh / 2, PAL.dim, 11, 800);
      } else {
        const [ok, total] = gateScore(agent.gates);
        ctx.fillStyle = "rgba(255,255,255,0.1)";
        ctx.fillRect(sx + 4, sy + 8, sw - 8, 4);
        ctx.fillStyle = PAL.blue;
        ctx.fillRect(sx + 4, sy + 8, (sw - 8) * (total ? ok / total : 0), 4);
        label(total ? ok + "/" + total : "…", sx + sw / 2, sy + 19, PAL.text, 7.5, 700);
      }
    });
    round(x - 70, y + 14, 140, 9, 3, PAL.deskTop, PAL.deskEdge);
    ctx.fillStyle = PAL.deskFront;
    ctx.fillRect(x - 66, y + 23, 132, 14);
    label(short(agent.alias, 18), x, y + 30, st.key === "draft" ? PAL.dim : PAL.text, 9, 700);
    label(short(agent.name, 26), x, y + 46, PAL.dim, 8, 500);
    starLine(agent, x, y + 59);
    if (st.bubble) bubble(x, y - 20, st.bubble, st.color, t);
    hits.push({ x: x - 72, y: y - 40, w: 144, h: 92, kind: "lab", agent, st });
    const key = "lab-" + agent.id;
    if (lastStates[key] && lastStates[key] !== st.key && st.key === "signal") pushEvent(agent.alias + " thấy tín hiệu " + (agent.signal || "") + " (lệnh giấy)", PAL.amber);
    lastStates[key] = st.key;
  }
  function onChange(agent, st, x, y) {
    if (st.key === "sent") {
      for (let i = 0; i < 40; i += 1) particles.push({ x, y: y - 20, vx: (Math.random() - 0.5) * 5, vy: -Math.random() * 5 - 1, life: 1, color: [PAL.gold, PAL.green, "#f472b6", PAL.blue][i % 4] });
      pushEvent(agent.alias + " vào lệnh", PAL.green);
    } else if (st.key === "blocked") {
      pushEvent(agent.alias + " bị chặn: " + short(st.line, 70), PAL.red);
    } else if (st.key === "holding") {
      pushEvent(agent.alias + " đang giữ lệnh", PAL.gold);
    } else if (st.key === "waiting" || st.key === "idle") {
      pushEvent(agent.alias + ": " + short(st.line, 70), PAL.dim);
    }
    if (st.key === "sent" || st.key === "blocked") {
      boss.tx = x - 60;
      boss.ty = y + 6;
      boss.until = performance.now() + 6000;
      boss.say = st.key === "sent" ? "Tốt!" : "Dừng!";
    }
  }
  function pushEvent(text, color) {
    const now = new Date();
    events.unshift({ at: String(now.getHours()).padStart(2, "0") + ":" + String(now.getMinutes()).padStart(2, "0"), text, color });
    events = events.slice(0, 8);
    if (feed) {
      feed.innerHTML = events.map((item) => '<li class="flex gap-2"><span class="font-mono text-zinc-500">' + item.at + '</span><span style="color:' + item.color + '">' + escapeHtml(item.text) + "</span></li>").join("");
    }
  }
  function drawBoss(t) {
    const now = performance.now();
    if (boss.until && now > boss.until) {
      boss.tx = boss.homeX;
      boss.ty = boss.homeY;
      boss.until = 0;
      boss.say = "";
    }
    const dx = boss.tx - boss.x;
    const dy = boss.ty - boss.y;
    const dist = Math.hypot(dx, dy);
    const moving = dist > 1.5;
    if (moving) {
      boss.x += (dx / dist) * Math.min(2.2, dist);
      boss.y += (dy / dist) * Math.min(2.2, dist);
    }
    const look = lookOf(crew ? crew.coordinator : "PTJ", "#27272a", "boss");
    const atHome = Math.hypot(boss.x - boss.homeX, boss.y - boss.homeY) < 2;
    // boss desk (always at home)
    monitor(70, 150, 56, 36, (sx, sy, sw, sh) => {
      const used = Number((crew || {}).openRisk || 0);
      const cap = Number((crew || {}).openRiskCap || 6);
      label("RỦI RO", sx + sw / 2, sy + 7, PAL.dim, 7.5, 700);
      ctx.fillStyle = "rgba(255,255,255,0.1)";
      ctx.fillRect(sx + 5, sy + 15, sw - 10, 6);
      ctx.fillStyle = used / cap > 0.8 ? PAL.red : PAL.gold;
      ctx.fillRect(sx + 5, sy + 15, (sw - 10) * Math.min(1, used / cap), 6);
      label(used.toFixed(1) + "%", sx + sw / 2, sy + 28, PAL.text, 8.5, 700);
    });
    if (atHome && !moving) {
      person(boss.x, boss.y, look, "idle", t, 1.25);
    }
    desk(160, 172, 220, PAL.gold, crew ? crew.coordinator : "Paul Tudor Jones", "Trưởng phòng · agent tổng");
    if (!(atHome && !moving)) walker(boss.x, boss.y, look, t, moving);
    const say = boss.say || (crew && /chặn/i.test(crew.coordinatorActivity || "") ? "Giữ rủi ro!" : "");
    if (say) bubble(boss.x, boss.y - 28, say, PAL.gold, t);
    hits.push({ x: 40, y: 120, w: 250, h: 120, kind: "boss" });
  }
  function drawEffects() {
    particles = particles.filter((p) => p.life > 0);
    particles.forEach((p) => {
      p.x += p.vx;
      p.y += p.vy;
      p.vy += 0.15;
      p.life -= 0.012;
      ctx.globalAlpha = Math.max(0, p.life);
      ctx.fillStyle = p.color;
      ctx.fillRect(p.x, p.y, 4, 4);
    });
    floaters = floaters.filter((f) => f.life > 0);
    floaters.forEach((f) => {
      f.y -= 0.5;
      f.life -= 0.01;
      ctx.globalAlpha = Math.max(0, f.life);
      label(f.text, f.x, f.y, f.color, 11, 800);
    });
    ctx.globalAlpha = 1;
  }

  // ------------------------------------------------------------ loop
  function frame(t) {
    if (!running || !canvas) return;
    L = layoutFor(((crew && crew.agents) || []).length, ((crew && crew.lab) || []).length);
    H = L.H;
    const holder = canvas.parentElement;
    const roomW = (holder && holder.clientWidth) || W;
    const top = canvas.getBoundingClientRect().top;
    const roomH = Math.max(260, window.innerHeight - Math.max(16, Math.min(top, 140)) - 16);
    const scale = Math.min(roomW / W, roomH / H);
    const cssW = Math.floor(W * scale);
    const dpr = window.devicePixelRatio || 1;
    const wantW = Math.round(cssW * dpr);
    const wantH = Math.round(H * scale * dpr);
    if (canvas.width !== wantW || canvas.height !== wantH) {
      canvas.width = wantW;
      canvas.height = wantH;
      canvas.style.width = cssW + "px";
      canvas.style.height = Math.floor(H * scale) + "px";
    }
    ctx.setTransform(dpr * scale, 0, 0, dpr * scale, 0, 0);
    hits = [];
    room();
    drawBoss(t);
    const staff = (crew && crew.agents) || [];
    const realRows = Math.max(1, Math.ceil(staff.length / REAL_COLS));
    const realTop = 84 + 40 + Math.max(0, (L.realH - 40 - realRows * ROW) / 2);
    const realLeft = REAL_X + (W - REAL_X - 16 - Math.min(staff.length, REAL_COLS) * CELL) / 2 + CELL / 2;
    staff.forEach((agent, index) => drawSmallDesk(agent, realLeft + (index % REAL_COLS) * CELL, realTop + 26 + Math.floor(index / REAL_COLS) * ROW, t));
    const lab = (crew && crew.lab) || [];
    const labLeft = 16 + (W - 32 - Math.min(lab.length, LAB_COLS) * CELL) / 2 + CELL / 2;
    lab.forEach((agent, index) => {
      drawLabAgent(agent, labLeft + (index % LAB_COLS) * CELL, L.labTop + 34 + 30 + Math.floor(index / LAB_COLS) * ROW, t);
    });
    if (!lab.length && crew) label("Chưa có agent nào ở phòng nghiên cứu: tất cả đang dùng tiền thật.", W / 2, L.labTop + 70, PAL.dim, 11, 600);
    if (!crew) label("Đang gọi các agent…", W / 2, H / 2, PAL.dim, 14, 600);
    drawEffects();
    if (hover) {
      ctx.strokeStyle = PAL.gold;
      ctx.lineWidth = 1.5;
      ctx.setLineDash([4, 3]);
      ctx.strokeRect(hover.x, hover.y, hover.w, hover.h);
      ctx.setLineDash([]);
    }
    window.requestAnimationFrame(frame);
  }
  function tipHtml(hit) {
    if (hit.kind === "boss") {
      return "<b>" + escapeHtml(crew.coordinator || "") + "</b> · Trưởng phòng<br>" + escapeHtml(crew.coordinatorActivity || "") +
        "<br><span class='text-zinc-400'>Rủi ro mở " + Number(crew.openRisk || 0).toFixed(2) + "% / " + Number(crew.openRiskCap || 6) + "%</span>";
    }
    const agent = hit.agent;
    const [ok, total] = gateScore(agent.gates);
    const failed = (agent.gates || []).find((gate) => gate.state === "fail");
    const pos = (agent.positions || [])[0];
    return "<b>" + escapeHtml(agent.alias || "") + "</b> · " + escapeHtml(agent.name || "") +
      (hit.kind === "lab" ? " <span class='text-sky-300'>(" + (agent.stage === "draft" ? "chưa triển khai" : "lệnh giấy") + ")</span>" : " <span class='text-emerald-300'>(tiền thật)</span>") +
      "<br><span class='text-gold'>" + "★".repeat(Number(agent.stars || 0)) + "☆".repeat(5 - Number(agent.stars || 0)) + "</span> <span class='text-zinc-400'>" +
      (agent.trades ? agent.trades + " lệnh thật · lãi ròng " + (agent.net >= 0 ? "+" : "") + Number(agent.net || 0).toFixed(2) + " $" : "chưa có lệnh thật") + "</span>" +
      "<br>" + escapeHtml(short(hit.st.line || "", 220)) +
      (total ? "<br><span class='text-zinc-400'>Điều kiện " + ok + "/" + total + (failed ? " · đang chờ: " + escapeHtml(failed.name) : "") + "</span>" : "") +
      (pos ? "<br><span class='text-zinc-300'>" + pos.side + " " + pos.volume + " lot @ " + Number(pos.open).toFixed(2) + " · " + (pos.profit >= 0 ? "+" : "") + Number(pos.profit).toFixed(2) + " $</span>" : "") +
      (agent.llm && agent.llm.calls ? "<br><span class='text-zinc-400'>Claude: " + agent.llm.calls + " lần · " + usd(agent.llm.cost) + "</span>" : "");
  }
  function onMove(event) {
    if (!canvas || !crew) return;
    const box = canvas.getBoundingClientRect();
    const scale = box.width / W;
    const x = (event.clientX - box.left) / scale;
    const y = (event.clientY - box.top) / scale;
    hover = hits.slice().reverse().find((hit) => x >= hit.x && x <= hit.x + hit.w && y >= hit.y && y <= hit.y + hit.h) || null;
    canvas.style.cursor = hover ? "pointer" : "default";
    if (!hover) {
      tip.hidden = true;
      return;
    }
    tip.innerHTML = tipHtml(hover);
    tip.hidden = false;
    const left = Math.min(event.clientX - box.left + 14, box.width - 290);
    tip.style.left = Math.max(4, left) + "px";
    tip.style.top = event.clientY - box.top + 14 + "px";
  }
  function closeMenu() {
    const menu = document.getElementById("office-menu");
    if (menu) menu.hidden = true;
  }
  function onClick(event) {
    if (!canvas || !crew) return;
    const box = canvas.getBoundingClientRect();
    const scale = box.width / W;
    const x = (event.clientX - box.left) / scale;
    const y = (event.clientY - box.top) / scale;
    const hit = hits.slice().reverse().find((item) => x >= item.x && x <= item.x + item.w && y >= item.y && y <= item.y + item.h);
    const menu = document.getElementById("office-menu");
    if (!hit || !menu) { closeMenu(); return; }
    tip.hidden = true;
    if (hit.kind === "boss") {
      menu.innerHTML = "<p class='font-semibold text-gold'>" + escapeHtml(crew.coordinator || "Trưởng phòng") + " · Trưởng phòng</p>" +
        "<p class='mt-1 text-zinc-400'>Họp: đánh giá các agent, cho lên tiền thật hoặc xuống nghiên cứu, giao sửa mã nguồn.</p>" +
        "<div class='mt-2 flex gap-1.5'><button type='button' data-meeting-run class='rounded-md border border-gold/60 bg-gold/15 px-2.5 py-1 font-semibold text-gold hover:bg-gold/25'>Họp ngay</button>" +
        "<button type='button' data-office-close class='rounded-md border border-line px-2.5 py-1 text-zinc-300 hover:bg-white/5'>Đóng</button></div>";
    } else {
      const agent = hit.agent;
      const real = hit.kind !== "lab";
      menu.innerHTML = "<p class='font-semibold' style='color:" + agentColor(agent.id) + "'>" + escapeHtml(agent.alias || agent.id) + "</p>" +
        "<p class='text-zinc-400'>" + escapeHtml(agent.name || "") + " · " + (real ? "<span class='text-emerald-300'>tiền thật</span>" : "<span class='text-sky-300'>nghiên cứu</span>") + "</p>" +
        "<p class='mt-1 text-zinc-400'><span class='text-gold'>" + "★".repeat(Number(agent.stars || 0)) + "☆".repeat(5 - Number(agent.stars || 0)) + "</span> · " + Number(agent.trades || 0) + " lệnh thật</p>" +
        "<div class='mt-2 flex flex-wrap gap-1.5'>" + modeButton(Object.assign({}, agent, { real })) +
        "<button type='button' data-office-close class='rounded-md border border-line px-2.5 py-1 text-zinc-300 hover:bg-white/5'>Đóng</button></div>";
    }
    const left = Math.min(event.clientX - box.left + 8, box.width - 264);
    menu.style.left = Math.max(4, left) + "px";
    menu.style.top = Math.min(event.clientY - box.top + 8, box.height - 40) + "px";
    menu.hidden = false;
  }
  function init() {
    canvas = document.getElementById("office-canvas");
    tip = document.getElementById("office-tip");
    feed = document.getElementById("office-feed");
    if (!canvas) return false;
    ctx = canvas.getContext("2d");
    canvas.addEventListener("mousemove", onMove);
    canvas.addEventListener("mouseleave", () => { hover = null; tip.hidden = true; });
    canvas.addEventListener("click", onClick);
    document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeMenu(); });
    document.addEventListener("click", (event) => {
      const menu = document.getElementById("office-menu");
      if (menu && !menu.hidden && !menu.contains(event.target) && event.target !== canvas && !event.target.closest("dialog")) closeMenu();
    });
    pushEvent("Phòng mở cửa. Trưởng phòng đang theo dõi các bàn.", PAL.gold);
    return true;
  }
  return {
    update(data, info) {
      crew = data || crew;
      extra = Object.assign(extra, info || {});
    },
    start() {
      if (!ctx && !init()) return;
      if (running) return;
      running = true;
      window.requestAnimationFrame(frame);
    },
    stop() {
      running = false;
      closeMenu();
    },
    closeMenu,
  };
})();
