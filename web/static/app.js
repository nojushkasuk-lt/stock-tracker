// Small progressive enhancements. Every page works without this file.
(function () {
  // Performance chart: one chart, ranges 1D to MAX; the number and caption follow the selected range.
  document.querySelectorAll("[data-perf]").forEach(function (box) {
    var num = box.querySelector("[data-perf-num]"), cap = box.querySelector("[data-perf-caption]");
    var line = box.querySelector("[data-line]"), area = box.querySelector("[data-area]");
    var span = box.querySelector("[data-chart-range]"), svg = box.querySelector("svg");
    var cursor = box.querySelector("[data-cursor]"), tip = box.querySelector("[data-tip]");
    var series = [], pts = [];
    function select(b) {
      box.querySelectorAll("[data-range]").forEach(function (o) { o.setAttribute("aria-pressed", o === b ? "true" : "false"); });
      num.textContent = b.dataset.pct; num.className = "perf-num " + b.dataset.tone; cap.textContent = b.dataset.caption;
      line.setAttribute("points", b.dataset.points);
      area.setAttribute("points", "0,250 " + b.dataset.points + " 1000,250");
      series = JSON.parse(b.dataset.series);
      pts = b.dataset.points.split(" ").map(function (p) { return p.split(",").map(Number); });
      if (span && series.length) span.textContent = series[0][0] + " – " + series[series.length - 1][0];
    }
    var buttons = box.querySelectorAll("[data-range]");
    buttons.forEach(function (b) { b.addEventListener("click", function () { select(b); }); });
    if (buttons.length) select(buttons[0]);
    if (!svg || !tip) return;
    svg.addEventListener("mousemove", function (e) {
      if (!pts.length) return;
      var r = svg.getBoundingClientRect(), x = (e.clientX - r.left) / r.width * 1000;
      var i = 0, best = Infinity;
      pts.forEach(function (p, k) { var d = Math.abs(p[0] - x); if (d < best) { best = d; i = k; } });
      var first = series[0][1], v = series[i][1], ch = (v / first - 1) * 100;
      cursor.setAttribute("x1", pts[i][0]); cursor.setAttribute("x2", pts[i][0]); cursor.setAttribute("visibility", "visible");
      tip.hidden = false; tip.style.left = (pts[i][0] / 1000 * 100) + "%";
      tip.textContent = series[i][0] + " · $" + v.toFixed(2) + " · " + (ch >= 0 ? "+" : "\u2212") + Math.abs(ch).toFixed(1) + "%";
    });
    svg.addEventListener("mouseleave", function () { tip.hidden = true; cursor.setAttribute("visibility", "hidden"); });
  });

  // Tabs (profile sections).
  document.querySelectorAll("[data-tabs]").forEach(function (box) {
    var tabs = box.querySelectorAll('[role="tab"]');
    tabs.forEach(function (t) {
      t.addEventListener("click", function () {
        tabs.forEach(function (o) {
          var on = o === t;
          o.setAttribute("aria-selected", on ? "true" : "false");
          document.getElementById(o.getAttribute("aria-controls")).hidden = !on;
        });
      });
    });
  });

  // Footnote markers open the sources panel.
  document.querySelectorAll('sup.ref a').forEach(function (a) {
    a.addEventListener("click", function () { var d = document.getElementById("sources"); if (d) d.open = true; });
  });
})();

// Settings and setup: stock filters, selected list, outlet presets, copy link, unsaved marker.
(function () {
  var pick = document.querySelector("[data-pick]");
  if (pick) {
    var q = document.querySelector("[data-stock-q]"), sector = document.querySelector("[data-stock-sector]");
    var region = document.querySelector("[data-stock-region]"), onlyMine = document.querySelector("[data-stock-mine]");
    var none = document.querySelector("[data-none]");
    var apply = function () {
      var text = (q && q.value.trim().toLowerCase()) || "", sec = sector ? sector.value : "", reg = region ? region.value : "";
      var shown = 0;
      pick.querySelectorAll("label").forEach(function (l) {
        var box = l.querySelector("input");
        var ok = (!text || l.dataset.text.indexOf(text) !== -1) && (!sec || l.dataset.sector === sec) &&
                 (!reg || l.dataset.region === reg) && (!onlyMine || !onlyMine.checked || box.checked);
        l.hidden = !ok; if (ok) shown++;
      });
      if (none) none.hidden = shown > 0;
    };
    [q, sector, region, onlyMine].forEach(function (el) { if (el) el.addEventListener(el.tagName === "INPUT" && el.type === "search" ? "input" : "change", apply); });
    document.querySelectorAll("[data-unpick]").forEach(function (b) {
      b.addEventListener("click", function () {
        var box = pick.querySelector('input[value="' + b.dataset.unpick + '"]');
        if (box) { box.checked = false; box.dispatchEvent(new Event("change", { bubbles: true })); }
        var row = b.closest("[data-sel]"); if (row) row.remove();
      });
    });
    var count = document.querySelector("[data-count]"), short = document.querySelector("[data-count-short]");
    var need = document.querySelector("[data-need-min]");
    var update = function () {
      var boxes = pick.querySelectorAll('input[name="ticker"]'), n = 0;
      boxes.forEach(function (b) { if (b.checked) n++; });
      var max = count ? +count.dataset.max : 15, min = count ? +(count.dataset.min || 0) : 0;
      if (count) count.textContent = n + " of " + max + " selected" + (min && n < min ? " · pick " + (min - n) + " more" : "");
      if (short) short.textContent = n;
      boxes.forEach(function (b) { b.disabled = !b.checked && n >= max; });
      if (need) need.disabled = n < min;
    };
    pick.addEventListener("change", update); update();
  }

  document.querySelectorAll("[data-outlets]").forEach(function (b) {
    b.addEventListener("click", function () {
      var mode = b.dataset.outlets;
      document.querySelectorAll('input[name="outlet"]').forEach(function (box) {
        var l = box.closest("label");
        box.checked = mode === "free" ? l.dataset.paywall === "0" : mode === "wires" ? l.dataset.group === "Wires & markets" : false;
      });
      var c = document.querySelector("[data-outlet-count]"), n = document.querySelectorAll('input[name="outlet"]:checked').length;
      if (c) c.textContent = (n || "All") + " selected";
      var d = document.querySelector("[data-dirty]"); if (d) d.hidden = false;
    });
  });

  var form = document.querySelector("form.settings"), dirty = document.querySelector("[data-dirty]");
  if (form && dirty) form.addEventListener("change", function () { dirty.hidden = false; });

  document.querySelectorAll("[data-copy]").forEach(function (b) {
    b.addEventListener("click", function () {
      var src = document.querySelector("[data-copy-src]");
      if (!src) return;
      src.select();
      (navigator.clipboard ? navigator.clipboard.writeText(src.value) : Promise.reject()).then(
        function () { b.textContent = "Copied"; }, function () { document.execCommand("copy"); b.textContent = "Copied"; });
    });
  });
})();

// Top-bar search: stocks and funds by ticker or name. "/" focuses it; arrows and Enter pick a result.
(function () {
  var box = document.querySelector("[data-qs]");
  if (!box) return;
  var input = box.querySelector("[data-qs-input]"), list = box.querySelector("[data-qs-list]");
  var items = null, shown = [], active = -1;
  function load() {
    if (items) return Promise.resolve(items);
    return fetch("/search.json", { credentials: "same-origin" }).then(function (r) { return r.ok ? r.json() : []; })
      .then(function (d) { items = d; return d; }, function () { items = []; return items; });
  }
  function score(it, q) {
    var t = it.t.toLowerCase(), n = it.n.toLowerCase();
    if (t === q) return 0;
    if (t.indexOf(q) === 0) return 1;
    if (n.indexOf(q) === 0) return 2;
    if (n.indexOf(" " + q) !== -1) return 3;
    if (n.indexOf(q) !== -1 || t.indexOf(q) !== -1) return 4;
    return -1;
  }
  function render() {
    var q = input.value.trim().toLowerCase();
    list.textContent = "";
    if (!q) { list.hidden = true; input.setAttribute("aria-expanded", "false"); return; }
    shown = items.map(function (it) { return [score(it, q), it]; }).filter(function (p) { return p[0] >= 0; })
      .sort(function (a, b) { return a[0] - b[0] || a[1].t.localeCompare(b[1].t); }).slice(0, 8).map(function (p) { return p[1]; });
    active = shown.length ? 0 : -1;
    if (!shown.length) {
      var li = document.createElement("li"); li.className = "qs-empty"; li.textContent = "No stock or fund matches \u201c" + input.value.trim() + "\u201d";
      list.appendChild(li);
    }
    shown.forEach(function (it, i) {
      var li = document.createElement("li"), a = document.createElement("a");
      a.href = it.u; a.setAttribute("role", "option"); a.setAttribute("aria-selected", i === active ? "true" : "false");
      var tk = document.createElement("span"); tk.className = "mono tk"; tk.textContent = it.t;
      var nm = document.createElement("span"); nm.textContent = it.n;
      var k = document.createElement("span"); k.className = "k"; k.textContent = it.k;
      a.append(tk, nm, k); li.appendChild(a); list.appendChild(li);
    });
    list.hidden = false; input.setAttribute("aria-expanded", "true");
  }
  function mark() { list.querySelectorAll("a").forEach(function (a, i) { a.setAttribute("aria-selected", i === active ? "true" : "false"); }); }
  input.addEventListener("focus", load);
  input.addEventListener("input", function () { load().then(render); });
  input.addEventListener("keydown", function (e) {
    if (e.key === "ArrowDown" && shown.length) { active = (active + 1) % shown.length; mark(); e.preventDefault(); }
    else if (e.key === "ArrowUp" && shown.length) { active = (active - 1 + shown.length) % shown.length; mark(); e.preventDefault(); }
    else if (e.key === "Enter" && active >= 0) { window.location.href = shown[active].u; e.preventDefault(); }
    else if (e.key === "Escape") { input.value = ""; render(); input.blur(); }
  });
  document.addEventListener("click", function (e) { if (!box.contains(e.target)) { list.hidden = true; input.setAttribute("aria-expanded", "false"); } });
  document.addEventListener("keydown", function (e) {
    var tag = (document.activeElement && document.activeElement.tagName) || "";
    if (e.key === "/" && !/INPUT|TEXTAREA|SELECT/.test(tag)) { input.focus(); e.preventDefault(); }
  });
})();
