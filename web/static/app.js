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

  // Settings: search filter and selected count.
  document.querySelectorAll("[data-filter]").forEach(function (input) {
    input.addEventListener("input", function () {
      var q = input.value.trim().toLowerCase();
      document.querySelectorAll(input.dataset.filter).forEach(function (el) {
        if (el.dataset.text) el.hidden = q && el.dataset.text.indexOf(q) === -1;
      });
    });
  });
  var count = document.querySelector("[data-count]");
  if (count) {
    var boxes = document.querySelectorAll('input[name="ticker"]'), max = +count.dataset.max;
    var update = function () {
      var n = Array.prototype.filter.call(boxes, function (b) { return b.checked; }).length;
      count.textContent = n + " of " + max + " selected";
      boxes.forEach(function (b) { b.disabled = !b.checked && n >= max; });
    };
    boxes.forEach(function (b) { b.addEventListener("change", update); });
    update();
  }
})();
