// Small progressive enhancements. Every page works without this file.
(function () {
  // Performance ranges: switch the number, caption and growth line.
  document.querySelectorAll("[data-perf]").forEach(function (box) {
    var num = box.querySelector("[data-perf-num]"), cap = box.querySelector("[data-perf-caption]");
    var line = box.querySelector("[data-line]"), area = box.querySelector("[data-area]"), note = box.querySelector("[data-chart-note]");
    box.querySelectorAll("[data-range]").forEach(function (b) {
      b.addEventListener("click", function () {
        box.querySelectorAll("[data-range]").forEach(function (o) { o.setAttribute("aria-pressed", o === b ? "true" : "false"); });
        num.textContent = b.dataset.pct; num.className = "perf-num " + b.dataset.tone; cap.textContent = b.dataset.caption;
        if (line) {
          var oneDay = b.dataset.range === "1D";
          line.setAttribute("points", b.dataset.points);
          line.setAttribute("stroke-dasharray", oneDay ? "6 6" : "none");
          area.setAttribute("points", oneDay ? "" : "0,250 " + b.dataset.points + " 1000,250");
          if (note) note.hidden = !oneDay;
        }
      });
    });
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
