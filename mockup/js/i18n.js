// i18n: the UI source text is Vietnamese. When the language is English, every Vietnamese phrase that
// reaches the page (static HTML, text built by scripts, API replies) is replaced by its English phrase
// from I18N_EN (js/i18n-en.js). Switching language reloads the page.
const LANG = (() => {
  let saved = null;
  const asked = new URLSearchParams(window.location.search).get("lang"); // ?lang=en|vi
  if (asked === "vi" || asked === "en") return asked;
  try { saved = localStorage.getItem("lang"); } catch (e) { /* storage blocked */ }
  if (saved === "vi" || saved === "en") return saved;
  return (navigator.language || "vi").toLowerCase().startsWith("vi") ? "vi" : "en";
})();
const LOCALE = LANG === "vi" ? "vi-VN" : "en-US";

const I18N = (() => {
  const VN = /[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]/i;
  const cache = new Map();
  let matcher = null;
  function build() {
    const keys = Object.keys(window.I18N_EN || {}).filter((k) => k.length > 0).sort((a, b) => b.length - a.length);
    const esc = keys.map((k) => k.replace(/[.*+?^${}()|[\]\\]/g, (c) => "\\" + c));
    // a phrase only matches as a whole (not inside a longer word)
    const L = "\\p{L}\\p{N}";
    matcher = esc.length ? new RegExp("(?<![" + L + "])(?:" + esc.join("|") + ")(?![" + L + "])", "gu") : null;
  }
  function translate(text) {
    if (LANG === "vi" || typeof text !== "string" || !VN.test(text)) return text;
    if (cache.has(text)) return cache.get(text);
    if (!matcher) build();
    const out = matcher ? text.replace(matcher, (m) => window.I18N_EN[m] ?? m) : text;
    if (cache.size > 5000) cache.clear();
    cache.set(text, out);
    return out;
  }
  const ATTRS = ["placeholder", "title", "aria-label", "alt"];
  function node(n) {
    if (n.nodeType === 3) {
      const next = translate(n.data);
      if (next !== n.data) n.data = next;
    } else if (n.nodeType === 1) {
      if (n.tagName === "SCRIPT" || n.tagName === "STYLE") return;
      for (const a of ATTRS) {
        const v = n.getAttribute(a);
        if (v) { const next = translate(v); if (next !== v) n.setAttribute(a, next); }
      }
      n.childNodes.forEach(node);
    }
  }
  function start() {
    document.documentElement.lang = LANG;
    const select = document.getElementById("lang-select");
    if (select) {
      select.value = LANG;
      select.addEventListener("change", () => {
        try { localStorage.setItem("lang", select.value); } catch (e) { /* ignore */ }
        window.location.reload();
      });
    }
    if (LANG === "vi") return;
    document.title = translate(document.title);
    node(document.body);
    new MutationObserver((records) => {
      for (const r of records) {
        if (r.type === "characterData") node(r.target);
        else if (r.type === "attributes") node(r.target);
        else r.addedNodes.forEach(node);
      }
    }).observe(document.body, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ATTRS });
  }
  return { translate, start };
})();

// t("Vietnamese text") for strings that are drawn on the canvas or placed in places the observer cannot see.
function t(text) { return I18N.translate(text); }
I18N.start();
