// openevaluations.si: data loading, number formats, tables and one SVG line chart.
// No dependencies. All data text goes into the DOM through textContent.
(function () {
  "use strict";
  var NS = "http://www.w3.org/2000/svg";
  var OE = (window.OE = {});

  OE.load = function (name) {
    return fetch("/data/" + name + ".json").then(function (r) {
      if (!r.ok) throw new Error(name + ": HTTP " + r.status);
      return r.json();
    });
  };

  OE.pct = function (x) { return x == null ? "–" : (x * 100).toFixed(0) + "%"; };
  OE.delta = function (x) { return x == null ? "–" : (x >= 0 ? "+" : "−") + Math.abs(x * 100).toFixed(1) + "%"; };
  OE.usd = function (x) { return x == null ? "–" : "$" + (x < 0.1 ? x.toFixed(4) : x.toFixed(2)); };
  OE.num = function (x) { return x == null ? "–" : (Math.round(x * 10) / 10).toLocaleString("en-US"); };
  OE.date = function (s) { return s ? s.slice(0, 10) : "–"; };
  OE.ci = function (lo, hi, f) { return lo == null || hi == null ? "" : "[" + f(lo) + ", " + f(hi) + "]"; };

  OE.el = function (tag, attrs, text) {
    var e = document.createElement(tag);
    if (attrs) for (var k in attrs) if (attrs[k] != null) e.setAttribute(k, attrs[k]);
    if (text != null) e.textContent = text;
    return e;
  };

  // columns: [{label, value(row) -> string|Node, num?: bool}]
  OE.table = function (columns, rows) {
    var wrap = OE.el("div", { class: "table-wrap" });
    var t = OE.el("table");
    var tr = OE.el("tr");
    columns.forEach(function (c) { tr.appendChild(OE.el("th", { class: c.num ? "num" : null, scope: "col" }, c.label)); });
    var thead = OE.el("thead"); thead.appendChild(tr); t.appendChild(thead);
    var tb = OE.el("tbody");
    rows.forEach(function (r) {
      var row = OE.el("tr");
      columns.forEach(function (c) {
        var v = c.value(r);
        var td = OE.el("td", { class: c.num ? "num" : null });
        if (v instanceof Node) td.appendChild(v); else td.textContent = v == null ? "–" : String(v);
        row.appendChild(td);
      });
      tb.appendChild(row);
    });
    t.appendChild(tb); wrap.appendChild(t);
    return wrap;
  };

  OE.flags = function (flags) {
    var span = OE.el("span");
    (flags || []).forEach(function (f) {
      var bad = f === "degraded" || f === "tool_calls_up" || f === "budget_stopped";
      var ok = f === "recovered";
      span.appendChild(OE.el("span", { class: "flag " + (bad ? "bad" : ok ? "ok" : "") }, (bad ? "▼ " : ok ? "▲ " : "") + f.replace("_", " ")));
      span.appendChild(document.createTextNode(" "));
    });
    return span;
  };

  function s(tag, attrs) {
    var e = document.createElementNS(NS, tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  }

  // One line chart over ordinal x (one position per run, in date order).
  // opts: {title, sub, series: [{name, color, points: [{label, y, lo?, hi?, rows: [[k, v], ...]}]}],
  //        yMin, yMax, yFormat}
  OE.lineChart = function (opts) {
    var W = 520, H = 220, m = { t: 12, r: 64, b: 30, l: 44 };
    var box = OE.el("figure", { class: "chart" });
    box.style.margin = "0";
    box.appendChild(OE.el("h4", null, opts.title));
    if (opts.sub) box.appendChild(OE.el("div", { class: "sub" }, opts.sub));
    var n = Math.max.apply(null, opts.series.map(function (x) { return x.points.length; }));
    var ys = [];
    opts.series.forEach(function (x) { x.points.forEach(function (p) { [p.y, p.lo, p.hi].forEach(function (v) { if (v != null) ys.push(v); }); }); });
    var y0 = opts.yMin != null ? opts.yMin : 0;
    var y1 = opts.yMax != null ? opts.yMax : (ys.length ? Math.max.apply(null, ys) * 1.1 : 1) || 1;
    var X = function (i) { return n <= 1 ? m.l + (W - m.l - m.r) / 2 : m.l + i * (W - m.l - m.r) / (n - 1); };
    var Y = function (v) { return H - m.b - (v - y0) / (y1 - y0) * (H - m.t - m.b); };
    var svg = s("svg", { viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": opts.title });
    for (var g = 0; g <= 4; g++) {
      var v = y0 + (y1 - y0) * g / 4, yy = Y(v);
      svg.appendChild(s("line", { class: "gridline", x1: m.l, x2: W - m.r, y1: yy, y2: yy }));
      var tl = s("text", { x: m.l - 8, y: yy + 4, "text-anchor": "end" }); tl.textContent = opts.yFormat(v); svg.appendChild(tl);
    }
    var labels = (opts.series[0] || { points: [] }).points.map(function (p) { return p.label; });
    // first, middle and last only: run labels are long and several runs can share a date
    var ticks = n <= 1 ? [0] : n < 5 ? [0, n - 1] : [0, Math.floor((n - 1) / 2), n - 1];
    labels.forEach(function (l, i) {
      if (ticks.indexOf(i) < 0) return;
      var anchor = n <= 1 ? "middle" : i === 0 ? "start" : i === n - 1 ? "end" : "middle";
      var t = s("text", { x: X(i), y: H - 10, "text-anchor": anchor }); t.textContent = l; svg.appendChild(t);
    });
    opts.series.forEach(function (sr) {
      var pts = sr.points;
      var band = pts.filter(function (p) { return p.lo != null && p.hi != null; });
      if (band.length === pts.length && pts.length > 1) {
        var d = pts.map(function (p, i) { return (i ? "L" : "M") + X(i) + "," + Y(p.hi); }).join("") +
          pts.slice().reverse().map(function (p, j) { return "L" + X(pts.length - 1 - j) + "," + Y(p.lo); }).join("") + "Z";
        svg.appendChild(s("path", { class: "band", d: d, style: "fill:" + sr.color }));
      }
      var seg = "", started = false;
      pts.forEach(function (p, i) {
        if (p.y == null) { started = false; return; }
        seg += (started ? "L" : "M") + X(i) + "," + Y(p.y); started = true;
      });
      svg.appendChild(s("path", { class: "line", d: seg, style: "stroke:" + sr.color }));
      pts.forEach(function (p, i) {
        if (p.y == null) return;
        svg.appendChild(s("circle", { class: "dot", cx: X(i), cy: Y(p.y), r: 4.5, style: "fill:" + sr.color }));
      });
      var last = pts.length - 1;
      while (last >= 0 && pts[last].y == null) last--;
      if (last >= 0) {
        var dl = s("text", { x: X(last) + 9, y: Y(pts[last].y) + 4 });
        dl.textContent = (opts.series.length > 1 ? sr.name + " " : "") + opts.yFormat(pts[last].y);
        dl.setAttribute("style", "fill: var(--text); font-weight: 600");
        svg.appendChild(dl);
      }
    });
    var hair = s("line", { class: "hair", y1: m.t, y2: H - m.b, x1: -10, x2: -10 });
    svg.appendChild(hair);
    var hit = s("rect", { x: m.l - 10, y: 0, width: W - m.l - m.r + 20, height: H, fill: "transparent", tabindex: "0" });
    svg.appendChild(hit);
    box.appendChild(svg);
    var tip = OE.el("div", { class: "tip", hidden: "" });
    box.appendChild(tip);
    function show(i) {
      if (i < 0 || i >= n) return;
      hair.setAttribute("x1", X(i)); hair.setAttribute("x2", X(i));
      tip.textContent = "";
      opts.series.forEach(function (sr) {
        var p = sr.points[i]; if (!p) return;
        var head = OE.el("strong", null, opts.yFormat(p.y == null ? null : p.y));
        var key = OE.el("span", { class: "k" }, (opts.series.length > 1 ? sr.name + " · " : "") + p.label);
        var keyline = OE.el("span", null, "▬ ");
        keyline.style.color = sr.color;
        var top = OE.el("div"); top.appendChild(head); top.appendChild(keyline); top.appendChild(key);
        tip.appendChild(top);
        (p.rows || []).forEach(function (kv) {
          var d = OE.el("div"); d.appendChild(OE.el("span", { class: "k" }, kv[0] + " ")); d.appendChild(document.createTextNode(kv[1])); tip.appendChild(d);
        });
      });
      tip.hidden = false;
      var bw = box.clientWidth, px = X(i) / W * svg.clientWidth + svg.offsetLeft;
      tip.style.left = Math.min(Math.max(8, px + 12), bw - tip.offsetWidth - 8) + "px";
      tip.style.top = (svg.offsetTop + 8) + "px";
    }
    function at(evt) {
      var r = svg.getBoundingClientRect();
      var x = (evt.clientX - r.left) / r.width * W;
      var best = 0, bd = Infinity;
      for (var i = 0; i < n; i++) { var dd = Math.abs(X(i) - x); if (dd < bd) { bd = dd; best = i; } }
      return best;
    }
    var cur = n - 1;
    hit.addEventListener("pointermove", function (e) { cur = at(e); show(cur); });
    hit.addEventListener("pointerleave", function () { tip.hidden = true; hair.setAttribute("x1", -10); hair.setAttribute("x2", -10); });
    hit.addEventListener("focus", function () { show(cur); });
    hit.addEventListener("blur", function () { tip.hidden = true; });
    hit.addEventListener("keydown", function (e) {
      if (e.key === "ArrowLeft") { cur = Math.max(0, cur - 1); show(cur); e.preventDefault(); }
      if (e.key === "ArrowRight") { cur = Math.min(n - 1, cur + 1); show(cur); e.preventDefault(); }
    });
    return box;
  };

  OE.nav = function (current) {
    document.querySelectorAll(".nav nav a").forEach(function (a) {
      if (a.getAttribute("href") !== current) return;
      a.setAttribute("aria-current", "page");
      // On phones the links scroll sideways: bring the current one into view.
      var nav = a.parentNode;
      if (nav.scrollWidth > nav.clientWidth) nav.scrollLeft = a.offsetLeft - nav.offsetLeft - 16;
    });
  };
})();
