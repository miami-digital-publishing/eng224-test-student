/*
  Search box for student sites. build_site.py writes every page's title,
  menu section, and text to _theme/search-index.js; this file loads it the
  first time someone uses the search box and searches it in the browser.
  Press "/" anywhere on a page to jump to the search box.
*/
(function () {
  var base = new URL("../", document.currentScript.src);
  var loading = null;
  var MAX = 8;

  function loadIndex() {
    if (!loading) {
      loading = new Promise(function (resolve) {
        var s = document.createElement("script");
        s.src = new URL("_theme/search-index.js", base).href;
        s.onload = function () { resolve(window.SEARCH_INDEX || []); };
        s.onerror = function () { resolve([]); };
        document.head.appendChild(s);
      });
    }
    return loading;
  }

  function escapeHtml(s) {
    return s.replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  function escapeRegex(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }

  // Wraps every search word in <mark>, escaping everything else
  function highlight(text, terms) {
    var re = new RegExp(terms.map(escapeRegex).join("|"), "gi");
    var out = "", last = 0, m;
    while ((m = re.exec(text))) {
      out += escapeHtml(text.slice(last, m.index)) + "<mark>" + escapeHtml(m[0]) + "</mark>";
      last = m.index + m[0].length;
      if (!m[0].length) re.lastIndex++;
    }
    return out + escapeHtml(text.slice(last));
  }

  function snippet(text, terms) {
    var lower = text.toLowerCase(), at = -1;
    terms.forEach(function (t) {
      var i = lower.indexOf(t);
      if (i >= 0 && (at < 0 || i < at)) at = i;
    });
    if (at < 0) return text.slice(0, 140) + (text.length > 140 ? "…" : "");
    var start = Math.max(0, text.lastIndexOf(" ", Math.max(0, at - 50)));
    var end = text.indexOf(" ", Math.min(text.length, at + 110));
    if (end < 0) end = text.length;
    return (start > 0 ? "…" : "") + text.slice(start, end).trim() + (end < text.length ? "…" : "");
  }

  function search(index, query) {
    var terms = query.toLowerCase().split(/\s+/).filter(Boolean);
    if (!terms.length) return { terms: terms, hits: [] };
    var hits = [];
    index.forEach(function (page) {
      var title = page.t.toLowerCase(), section = page.s.toLowerCase(), text = page.x.toLowerCase();
      var heads = (page.h || "").toLowerCase();
      var score = 0;
      for (var i = 0; i < terms.length; i++) {
        var t = terms[i], found = false;
        if (title.indexOf(t) >= 0) { score += 20; found = true; }
        if (new RegExp("\\b" + escapeRegex(t)).test(title)) score += 10;
        if (section.indexOf(t) >= 0) { score += 6; found = true; }
        if (heads.indexOf(t) >= 0) score += 8;
        var count = text.split(t).length - 1;
        if (count) { score += Math.min(count, 6); found = true; }
        if (!found) return;  // every word must appear somewhere on the page
      }
      hits.push({ page: page, score: score });
    });
    hits.sort(function (a, b) { return b.score - a.score; });
    return { terms: terms, hits: hits };
  }

  function setUp(box) {
    var input = box.querySelector("input");
    var panel = box.querySelector(".search-results");

    function close() { panel.hidden = true; }

    function render() {
      var q = input.value.trim();
      if (!q) { panel.innerHTML = ""; close(); return; }
      loadIndex().then(function (index) {
        if (input.value.trim() !== q) return;  // the reader kept typing
        var r = search(index, q);
        var html;
        if (!r.hits.length) {
          html = '<p class="search-count">No pages match “' + escapeHtml(q) + '”.</p>';
        } else {
          var n = r.hits.length;
          html = '<p class="search-count">' + n + (n === 1 ? " page" : " pages") +
                 (n > MAX ? ", showing the best " + MAX : "") + "</p><ul>";
          r.hits.slice(0, MAX).forEach(function (h) {
            var p = h.page;
            html += '<li><a href="' + escapeHtml(new URL(p.u, base).href) + '">' +
                    '<span class="sr-title">' + highlight(p.t, r.terms) + "</span>" +
                    (p.s ? '<span class="sr-section">' + escapeHtml(p.s) + "</span>" : "") +
                    '<span class="sr-snippet">' + highlight(snippet(p.x, r.terms), r.terms) + "</span>" +
                    "</a></li>";
          });
          html += "</ul>";
        }
        panel.innerHTML = html;
        panel.hidden = false;
      });
    }

    function links() { return Array.prototype.slice.call(panel.querySelectorAll("a")); }

    input.addEventListener("input", render);
    input.addEventListener("focus", function () { loadIndex(); if (input.value.trim()) render(); });
    box.addEventListener("keydown", function (e) {
      var list = links(), i = list.indexOf(document.activeElement);
      if (e.key === "ArrowDown" && list.length) {
        e.preventDefault();
        list[Math.min(i + 1, list.length - 1)].focus();
      } else if (e.key === "ArrowUp" && list.length) {
        e.preventDefault();
        if (i <= 0) input.focus(); else list[i - 1].focus();
      } else if (e.key === "Enter" && document.activeElement === input && list.length) {
        e.preventDefault();
        location.href = list[0].href;
      } else if (e.key === "Escape") {
        close();
        input.focus();
      }
    });
    document.addEventListener("click", function (e) { if (!box.contains(e.target)) close(); });
  }

  function start() {
    var boxes = document.querySelectorAll(".site-search");
    Array.prototype.forEach.call(boxes, setUp);
    document.addEventListener("keydown", function (e) {
      var tag = (document.activeElement && document.activeElement.tagName) || "";
      if (e.key !== "/" || /INPUT|TEXTAREA|SELECT/.test(tag) || e.metaKey || e.ctrlKey) return;
      var visible = Array.prototype.filter.call(boxes, function (b) { return b.offsetParent; })[0];
      if (visible) { e.preventDefault(); visible.querySelector("input").focus(); }
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
