// Frasberg Game Builder — WorldGraph runtime bridge (FRASBERG INC.)
// Loaded only for /api/game-builder/worlds/{id}/play. window.FRASBERG_WORLD is injected by the server:
// { id, name, tagline, engine, config, environment: {time_of_day, weather}, world: <WorldDefinition> }
(function () {
  var FW = window.FRASBERG_WORLD || {};
  window.FWC = FW.config || {};
  var env = FW.environment || {};

  // Environment: engines ask /api/games/{gid}/environment — the world's time of day / weather win.
  if (window.fetch && (env.time_of_day || env.weather)) {
    var _fetch = window.fetch.bind(window);
    window.fetch = function (input, init) {
      var url = typeof input === "string" ? input : (input && input.url) || "";
      if (url.indexOf("/environment") !== -1 && url.indexOf("/api/games/") !== -1) {
        return _fetch(input, init).then(function (r) { return r.json(); }).catch(function () { return {}; })
          .then(function (base) {
            var merged = Object.assign({}, base, env, { source: "worldgraph" });
            return new Response(JSON.stringify(merged), { status: 200, headers: { "Content-Type": "application/json" } });
          });
      }
      return _fetch(input, init);
    };
  }

  function applyText() {
    if (FW.name) document.title = FW.name + " — Frasberg Game Builder";
    var start = document.getElementById("start") || document.getElementById("loading");
    if (start) {
      var h = start.querySelector("h1");
      if (h && FW.name) h.textContent = "⬡ " + FW.name.toUpperCase();
      var p = start.querySelector("p");
      if (p && FW.tagline) p.textContent = FW.tagline;
      var cfg = window.FWC || {};
      if (cfg.bossEvery) {
        start.querySelectorAll("p").forEach(function (el) {
          el.textContent = el.textContent.replace(/every \d+ waves/i, "every " + cfg.bossEvery + " waves");
        });
      }
      var lv = document.getElementById("lives");
      if (lv && cfg.lives) lv.textContent = cfg.lives;
      var hp = document.getElementById("hp");
      if (hp && cfg.playerHp) hp.textContent = cfg.playerHp;
    }
    if (!document.getElementById("fw-badge")) {
      var b = document.createElement("div");
      b.id = "fw-badge";
      b.setAttribute("data-testid", "world-badge");
      b.textContent = "◈ WorldGraph · " + (FW.engineTitle || FW.engine || "engine") + (FW.id ? " · " + FW.id.slice(0, 11) : "");
      b.style.cssText = "position:fixed;right:10px;bottom:10px;z-index:99999;padding:4px 10px;border-radius:999px;" +
        "font:600 11px/1.4 ui-monospace,monospace;letter-spacing:.08em;color:#9ef0ff;background:rgba(8,12,24,.72);" +
        "border:1px solid rgba(80,220,255,.35);pointer-events:none;text-transform:uppercase";
      document.body.appendChild(b);
    }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", applyText);
  else applyText();
})();
