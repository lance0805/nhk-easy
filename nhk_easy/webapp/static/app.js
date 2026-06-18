// NHK Easy Reader - interaction layer. Zero-dependency vanilla JS.
// The early theme/font/furigana bootstrap runs inline in <head> (see base.html)
// to avoid FOUC; this deferred script wires up the controls and shortcuts.
(function () {
  "use strict";

  var root = document.documentElement;
  var LS = {
    theme: "nhk-theme",          // "light" | "dark" | absent (= follow system)
    furigana: "nhk-furigana",    // "off" when hidden
    font: "nhk-font-scale",      // number string
    read: "nhk-read-ids",        // JSON array of news_id
  };

  // ---------- Helpers ----------
  function $(sel, ctx) { return (ctx || document).querySelector(sel); }
  function $all(sel, ctx) { return Array.prototype.slice.call((ctx || document).querySelectorAll(sel)); }

  function isTyping(el) {
    if (!el) return false;
    var tag = el.tagName;
    return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable;
  }

  var toastTimer;
  function toast(msg) {
    var t = $("#toast");
    if (!t) return;
    t.textContent = msg;
    t.classList.add("is-visible");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.classList.remove("is-visible"); }, 1400);
  }

  // ---------- Theme ----------
  function systemPrefersDark() {
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  }
  function effectiveDark() {
    var pref = localStorage.getItem(LS.theme);
    if (pref === "dark") return true;
    if (pref === "light") return false;
    return systemPrefersDark();
  }
  function syncThemeColor() {
    var meta = $('meta[name="theme-color"]:not([media])') || $('meta[name="theme-color"]');
    if (meta) {
      meta.setAttribute("content", effectiveDark() ? "#0e1014" : "#f4f5f7");
    }
  }
  function applyTheme(pref) {
    if (pref) { root.setAttribute("data-theme", pref); }
    else { root.removeAttribute("data-theme"); }
    syncThemeColor();
    var btn = $("#theme-toggle");
    if (btn) btn.setAttribute("aria-pressed", String(effectiveDark()));
  }
  function toggleTheme() {
    // Toggle relative to what is currently shown.
    var next = effectiveDark() ? "light" : "dark";
    localStorage.setItem(LS.theme, next);
    applyTheme(next);
    toast(next === "dark" ? "ダークモード" : "ライトモード");
  }
  // React to OS theme changes when following the system.
  if (window.matchMedia) {
    var mq = window.matchMedia("(prefers-color-scheme: dark)");
    var onChange = function () { if (!localStorage.getItem(LS.theme)) syncThemeColor(); };
    if (mq.addEventListener) mq.addEventListener("change", onChange);
    else if (mq.addListener) mq.addListener(onChange);
  }

  // ---------- Furigana ----------
  function furiganaOn() { return root.getAttribute("data-furigana") !== "off"; }
  function applyFurigana(on) {
    if (on) { root.removeAttribute("data-furigana"); localStorage.removeItem(LS.furigana); }
    else { root.setAttribute("data-furigana", "off"); localStorage.setItem(LS.furigana, "off"); }
    var btn = $("#furigana-toggle");
    if (btn) btn.setAttribute("aria-pressed", String(!on));
  }
  function toggleFurigana() {
    var next = !furiganaOn();
    applyFurigana(next);
    toast(next ? "ふりがな表示" : "ふりがな非表示");
  }

  // ---------- Font scale ----------
  var MIN_FONT = 0.8, MAX_FONT = 1.6, STEP = 0.1;
  function currentFont() {
    return parseFloat(getComputedStyle(root).getPropertyValue("--font-scale")) || 1;
  }
  function setFont(v) {
    v = Math.max(MIN_FONT, Math.min(MAX_FONT, Math.round(v * 10) / 10));
    root.style.setProperty("--font-scale", String(v));
    if (Math.abs(v - 1) < 0.001) localStorage.removeItem(LS.font);
    else localStorage.setItem(LS.font, String(v));
    toast("文字サイズ " + Math.round(v * 100) + "%");
  }
  function bumpFont(dir) { setFont(currentFont() + dir * STEP); }

  // ---------- Read marks ----------
  function readSet() {
    try { return new Set(JSON.parse(localStorage.getItem(LS.read) || "[]")); }
    catch (e) { return new Set(); }
  }
  function markRead(id) {
    var s = readSet();
    if (s.has(id)) return;
    s.add(id);
    localStorage.setItem(LS.read, JSON.stringify(Array.prototype.slice.call(s)));
  }

  // ---------- Help overlay ----------
  var lastFocused = null;
  function openHelp() {
    var ov = $("#help-overlay");
    if (!ov) return;
    lastFocused = document.activeElement;
    ov.classList.add("is-open");
    ov.setAttribute("aria-hidden", "false");
    var close = $("#help-close", ov);
    if (close) close.focus();
  }
  function closeHelp() {
    var ov = $("#help-overlay");
    if (!ov) return;
    ov.classList.remove("is-open");
    ov.setAttribute("aria-hidden", "true");
    if (lastFocused && lastFocused.focus) lastFocused.focus();
  }
  function helpOpen() { var ov = $("#help-overlay"); return ov && ov.classList.contains("is-open"); }

  // ---------- List page: search + selection ----------
  function initList() {
    var grid = $("#card-grid");
    if (!grid) return;
    var cards = $all(".card", grid);

    // Mark already-read cards.
    var read = readSet();
    cards.forEach(function (c) { if (read.has(c.dataset.id)) c.classList.add("is-read"); });

    // Reveal thumbnails that load; drop the ones that 404 so the letter
    // placeholder shows through (no image was downloaded for that article).
    $all("img[data-thumb]", grid).forEach(function (img) {
      if (img.complete && img.naturalWidth > 0) { img.classList.add("is-loaded"); return; }
      img.addEventListener("load", function () { img.classList.add("is-loaded"); });
      img.addEventListener("error", function () { img.remove(); });
    });

    var input = $("#search-input");
    var countEl = $("#list-count");

    function visibleCards() { return cards.filter(function (c) { return c.style.display !== "none"; }); }

    function applyFilter(q) {
      q = (q || "").trim().toLowerCase();
      var shown = 0;
      cards.forEach(function (c) {
        var hit = !q || (c.dataset.title || "").toLowerCase().indexOf(q) !== -1;
        c.style.display = hit ? "" : "none";
        if (hit) shown++;
      });
      if (countEl) countEl.textContent = shown + " / " + cards.length;
      var none = $("#no-results");
      if (none) none.hidden = shown !== 0 || cards.length === 0;
      clearSelection();
    }

    // URL <-> search sync (state in query param per guidelines).
    if (input) {
      var params = new URLSearchParams(window.location.search);
      var initial = params.get("q") || "";
      if (initial) { input.value = initial; }
      applyFilter(initial);

      var t;
      input.addEventListener("input", function () {
        clearTimeout(t);
        t = setTimeout(function () {
          applyFilter(input.value);
          var p = new URLSearchParams(window.location.search);
          if (input.value.trim()) p.set("q", input.value.trim()); else p.delete("q");
          var qs = p.toString();
          history.replaceState(null, "", qs ? "?" + qs : window.location.pathname);
        }, 120);
      });
    } else {
      applyFilter("");
    }

    // Keyboard selection (j/k/Enter/o).
    var selected = -1;
    function clearSelection() {
      cards.forEach(function (c) { c.classList.remove("is-selected"); });
      selected = -1;
    }
    function move(delta) {
      var vis = visibleCards();
      if (!vis.length) return;
      var curr = vis.indexOf(cards[selected]);
      var next = curr === -1 ? (delta > 0 ? 0 : vis.length - 1) : curr + delta;
      next = Math.max(0, Math.min(vis.length - 1, next));
      clearSelection();
      var card = vis[next];
      card.classList.add("is-selected");
      selected = cards.indexOf(card);
      card.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
    function openSelected() {
      if (selected < 0) return;
      var link = $(".card__title a", cards[selected]);
      if (link) link.click();
    }

    document.addEventListener("keydown", function (e) {
      if (helpOpen()) return;
      if (e.key === "/" && !isTyping(e.target)) {
        e.preventDefault();
        if (input) input.focus();
        return;
      }
      if (isTyping(e.target)) {
        if (e.key === "Escape" && input && e.target === input) { input.blur(); }
        return;
      }
      if (e.key === "j" || e.key === "ArrowDown") { e.preventDefault(); move(1); }
      else if (e.key === "k" || e.key === "ArrowUp") { e.preventDefault(); move(-1); }
      else if (e.key === "Enter" || e.key === "o") { openSelected(); }
    });
  }

  // ---------- Detail page: progress + audio + read mark ----------
  function initDetail() {
    var article = $("#article");
    if (!article) return;
    if (article.dataset.id) markRead(article.dataset.id);

    // Reading progress (compositor-friendly scaleX).
    var bar = $("#progress-bar");
    if (bar) {
      var ticking = false;
      function update() {
        var max = document.documentElement.scrollHeight - window.innerHeight;
        var p = max > 0 ? window.scrollY / max : 0;
        bar.style.transform = "scaleX(" + Math.max(0, Math.min(1, p)) + ")";
        ticking = false;
      }
      window.addEventListener("scroll", function () {
        if (!ticking) { ticking = true; requestAnimationFrame(update); }
      }, { passive: true });
      window.addEventListener("resize", update, { passive: true });
      update();
    }

    // Audio: enhance the native <audio> with Plyr (modern, accessible, large
    // controls + built-in keyboard support), and layer the repeat-N-times loop
    // on top by listening to the underlying media element's events.
    var media = $("#player");
    var plyr = null;
    var RATES = [0.5, 0.75, 1, 1.25, 1.5, 2];
    if (media) {
      if (window.Plyr) {
        plyr = new Plyr(media, {
          controls: ["play", "rewind", "fast-forward", "progress",
                     "current-time", "duration", "mute", "volume", "settings"],
          settings: ["speed"],
          seekTime: 5,
          speed: { selected: parseFloat(localStorage.getItem("nhk-rate")) || 1, options: RATES },
          keyboard: { focused: true, global: false },
          iconUrl: "/static/vendor/plyr.svg?v=3.8.4",
          tooltips: { controls: true, seek: true },
          i18n: {
            play: "再生", pause: "一時停止", mute: "ミュート", unmute: "ミュート解除",
            settings: "設定", speed: "再生速度", normal: "標準", restart: "最初から",
            rewind: "5秒戻る", fastForward: "5秒進む"
          }
        });
        plyr.on("ratechange", function () {
          try { localStorage.setItem("nhk-rate", String(plyr.speed)); } catch (e) {}
        });
      }

      // Repeat the clip N times for shadowing practice.
      var countInput = $("#loop-count");
      var progress = $("#loop-progress");
      var KEY = "nhk-easy-loop-count";
      var DEFAULT_LOOPS = 20;
      countInput.value = parseInt(localStorage.getItem(KEY), 10) || DEFAULT_LOOPS;
      countInput.addEventListener("change", function () {
        var v = Math.max(1, parseInt(countInput.value, 10) || DEFAULT_LOOPS);
        countInput.value = v;
        localStorage.setItem(KEY, v);
      });
      var played = 0;
      function showProgress() { progress.textContent = played + " / " + countInput.value; }
      media.addEventListener("play", function () {
        if (played >= parseInt(countInput.value, 10)) played = 0;
        if (played === 0) showProgress();
      });
      media.addEventListener("ended", function () {
        played += 1;
        showProgress();
        if (played < parseInt(countInput.value, 10)) { media.currentTime = 0; media.play(); }
      });
      showProgress();
    }

    document.addEventListener("keydown", function (e) {
      if (helpOpen() || isTyping(e.target)) return;
      if (!media) {
        if (e.key === "u" || e.key === "Backspace") { e.preventDefault(); window.location.href = "/"; }
        return;
      }
      // When focus is inside the player controls, let Plyr handle the key.
      var inControls = e.target && e.target.closest && e.target.closest(".plyr");
      switch (e.key) {
        case " ":
          if (inControls) return;
          e.preventDefault();
          if (plyr) plyr.togglePlay(); else (media.paused ? media.play() : media.pause());
          break;
        case "ArrowRight":
          e.preventDefault();
          media.currentTime = Math.min(media.duration || 1e9, media.currentTime + 5);
          break;
        case "ArrowLeft":
          e.preventDefault();
          media.currentTime = Math.max(0, media.currentTime - 5);
          break;
        case "[":
        case "]": {
          var cur = plyr ? plyr.speed : media.playbackRate;
          var i = RATES.indexOf(cur);
          if (i < 0) i = RATES.indexOf(1);
          i = Math.max(0, Math.min(RATES.length - 1, i + (e.key === "]" ? 1 : -1)));
          if (plyr) plyr.speed = RATES[i]; else media.playbackRate = RATES[i];
          toast("再生速度 " + RATES[i] + "x");
          break;
        }
        case "u":
        case "Backspace":
          e.preventDefault();
          window.location.href = "/";
          break;
      }
    });
  }

  // ---------- Global controls + shortcuts ----------
  function initGlobal() {
    var themeBtn = $("#theme-toggle");
    if (themeBtn) themeBtn.addEventListener("click", toggleTheme);
    var furiBtn = $("#furigana-toggle");
    if (furiBtn) {
      furiBtn.setAttribute("aria-pressed", String(!furiganaOn()));
      furiBtn.addEventListener("click", toggleFurigana);
    }
    var inc = $("#font-inc"), dec = $("#font-dec");
    if (inc) inc.addEventListener("click", function () { bumpFont(1); });
    if (dec) dec.addEventListener("click", function () { bumpFont(-1); });
    var helpBtn = $("#help-toggle");
    if (helpBtn) helpBtn.addEventListener("click", openHelp);

    var ov = $("#help-overlay");
    if (ov) {
      ov.addEventListener("click", function (e) { if (e.target === ov) closeHelp(); });
      var cls = $("#help-close", ov);
      if (cls) cls.addEventListener("click", closeHelp);
    }

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && helpOpen()) { e.preventDefault(); closeHelp(); return; }
      if (isTyping(e.target) || helpOpen()) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      switch (e.key) {
        case "?": e.preventDefault(); openHelp(); break;
        case "t": toggleTheme(); break;
        case "f": toggleFurigana(); break;
        case "+": case "=": e.preventDefault(); bumpFont(1); break;
        case "-": case "_": e.preventDefault(); bumpFont(-1); break;
        case "0": setFont(1); break;
      }
    });
  }

  function init() {
    syncThemeColor();
    initGlobal();
    initList();
    initDetail();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
