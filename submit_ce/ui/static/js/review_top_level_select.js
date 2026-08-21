// review_top_level_select.js  (SUBMISSION-226)
//
// Progressive enhancement for the Review Files "Top-level TeX file(s)" widget.
// The server renders one or more <select name="top_level_tex_files[]"> rows
// (at least one, so a single top-level is always selectable without JS). This
// script adds the add / remove / move-up / move-down controls, keeps the
// selects de-duplicated (a file can be top-level only once), caps the number of
// rows at the number of candidate TeX files, and -- after any change -- nudges
// review_top_level_guard.js so the delete checkboxes re-sync to the current
// top-level set. With JS off, the rendered row(s) still submit.
(function () {
  "use strict";

  function field() { return document.getElementById("top-level-tex"); }
  function rowsContainer() { return document.getElementById("top-level-rows"); }
  function addButton() { return document.getElementById("tl-add"); }

  function rows() {
    return Array.prototype.slice.call(
      document.querySelectorAll("#top-level-rows .top-level-row"));
  }
  function selects() {
    return Array.prototype.slice.call(
      document.querySelectorAll("#top-level-rows select.top-level-select"));
  }
  function candidateCap() {
    var f = field();
    return f ? parseInt(f.dataset.candidateCount || "0", 10) : 0;
  }

  // Disable, in each select, the options chosen in OTHER selects.
  function dedupe() {
    var chosen = selects().map(function (s) { return s.value; });
    selects().forEach(function (s) {
      Array.prototype.forEach.call(s.options, function (opt) {
        opt.disabled = (opt.value !== s.value && chosen.indexOf(opt.value) !== -1);
      });
    });
  }

  // Tell the top-level guard the selection changed so it re-syncs delete boxes.
  function notifyGuard() {
    var s = selects()[0];
    if (s) { s.dispatchEvent(new Event("change", { bubbles: true })); }
  }

  function refresh() {
    var rs = rows();
    rs.forEach(function (r, i) {
      var rm = r.querySelector(".tl-remove");
      var up = r.querySelector(".tl-move-up");
      var down = r.querySelector(".tl-move-down");
      if (rm) { rm.disabled = rs.length <= 1; }        // keep at least one
      if (up) { up.disabled = (i === 0); }
      if (down) { down.disabled = (i === rs.length - 1); }
    });
    var add = addButton();
    if (add) { add.disabled = rs.length >= candidateCap(); }
    dedupe();
    notifyGuard();
  }

  function wire(row) {
    var rm = row.querySelector(".tl-remove");
    if (rm) rm.addEventListener("click", function () {
      if (rows().length > 1) { row.remove(); refresh(); }
    });
    var up = row.querySelector(".tl-move-up");
    if (up) up.addEventListener("click", function () {
      var prev = row.previousElementSibling;
      if (prev) { rowsContainer().insertBefore(row, prev); refresh(); }
    });
    var down = row.querySelector(".tl-move-down");
    if (down) down.addEventListener("click", function () {
      var next = row.nextElementSibling;
      if (next) { rowsContainer().insertBefore(next, row); refresh(); }
    });
    var sel = row.querySelector("select.top-level-select");
    if (sel) sel.addEventListener("change", refresh);
  }

  function addRow() {
    var rs = rows();
    if (!rs.length || rs.length >= candidateCap()) { return; }
    var clone = rs[rs.length - 1].cloneNode(true);
    var sel = clone.querySelector("select.top-level-select");
    // Default the new row to the first candidate not already chosen.
    var chosen = selects().map(function (s) { return s.value; });
    Array.prototype.some.call(sel.options, function (opt) {
      if (chosen.indexOf(opt.value) === -1) { sel.value = opt.value; return true; }
      return false;
    });
    rowsContainer().appendChild(clone);
    wire(clone);
    refresh();
  }

  window.addEventListener("DOMContentLoaded", function () {
    if (!rowsContainer()) { return; }
    rows().forEach(wire);
    var add = addButton();
    if (add) { add.addEventListener("click", addRow); }
    refresh();
  });
})();
