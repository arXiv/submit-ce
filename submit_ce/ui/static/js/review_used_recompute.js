// review_used_recompute.js  (SUBMISSION-231, part 2)
//
// Live, client-side recompute of each file's used / not-used state as the
// top-level TeX selection changes -- WITHOUT a server round-trip and WITHOUT
// deleting or persisting anything. Deletion still happens only when the
// submitter clicks Continue with their final selection.
//
// Why this exists: "used" is not a fixed property of a file; it's reachability
// from the *selected* top-level(s) over preflight's resolved-reference graph
// (see DirectiveManager.reachable_from / used_edges, SUBMISSION-231). The server
// renders the correct state for the initial selection and re-derives it
// authoritatively on Continue; this script mirrors that same walk in the
// browser so the "Auto-detected Notes" and the delete checkboxes update the
// instant the submitter changes the top-level -- important because a large
// submission's server render is far too slow to round-trip on every change.
//
// It supersedes the partial top-level guard (SUBMISSION-209) by running last
// and setting the complete per-row state (top-level / used / candidate /
// possibly-used / unused). With JS off, the server render still applies.
//
// PARITY: reachableFrom() below must stay behaviourally identical to the Python
// DirectiveManager.reachable_from(). A shared fixture asserts they agree
// (see the parity test).
(function () {
  "use strict";

  function readData() {
    var el = document.getElementById("review-recompute-data");
    if (!el) { return null; }
    try { return JSON.parse(el.textContent || "{}"); }
    catch (e) { return null; }
  }

  // Files reachable from `roots` over the adjacency `edges`
  // ({filename: [referenced...]}), transitively, excluding the roots
  // themselves. Mirror of DirectiveManager.reachable_from.
  function reachableFrom(roots, edges) {
    var rootSet = {};
    (roots || []).forEach(function (r) { if (r) { rootSet[r] = true; } });
    var used = {};
    var stack = Object.keys(rootSet);
    while (stack.length) {
      var node = stack.pop();
      var refs = (edges && edges[node]) || [];
      for (var i = 0; i < refs.length; i++) {
        var ref = refs[i];
        if (ref && !used[ref] && !rootSet[ref]) {
          used[ref] = true;
          stack.push(ref);
        }
      }
    }
    return used;  // set-as-object: {filename: true}
  }

  function topLevelSelects() {
    return document.querySelectorAll(
      'select[name="source_file"], select[name="top_level_tex_files[]"]');
  }

  function selectedTopLevels() {
    var out = [];
    topLevelSelects().forEach(function (sel) {
      if (sel.value && out.indexOf(sel.value) === -1) { out.push(sel.value); }
    });
    return out;
  }

  function fileCheckboxes() {
    return document.querySelectorAll('input[name="selected_files"]');
  }

  function setNote(cb, text) {
    var row = cb.closest("tr");
    var note = row && row.querySelector(".file-usage-note");
    if (note) { note.textContent = text; }
  }

  function setTint(cb) {
    var row = cb.closest("tr");
    // The yellow marked-for-deletion tint (styled by SUBMISSION-228) follows the
    // checkbox; no-op visually on branches without that CSS.
    if (row) { row.classList.toggle("marked-for-deletion", cb.checked); }
  }

  // Pure per-file decision, given the current selection state. Returns the DOM
  // state to apply: {disabled, checked, lock (or null), note}. Mirrors the
  // server-side build_file_rows classification (SUBMISSION-220/221/222/231),
  // with the added rule that a detected-but-unselected top-level is never
  // auto-checked. Kept pure so it can be unit-tested without a DOM.
  function classify(fn, sets) {
    if (sets.rootSet[fn]) {
      // Selected top-level: what we compile -- not deletable.
      return { disabled: true, checked: false, lock: null, note: "Used: top-level file" };
    }
    if (fn && fn.indexOf("anc/") === 0) {
      // Ancillary file (under anc/) -- supplementary, selection-independent.
      // Never auto-checked for deletion; labeled. Mirrors build_file_rows
      // (SUBMISSION-252). Kept out of the used/unused reclassification so the
      // live recompute can't re-check it.
      return { disabled: false, checked: false, lock: null, note: "Ancillary" };
    }
    if (sets.unanalyzedSet[fn]) {
      // Stored in the bucket but absent from the preflight report -- preflight
      // couldn't analyze it (SUBMISSION-246). Selection-independent: shown,
      // deletable, but never auto-checked.
      return { disabled: false, checked: false, lock: null, note: "Not analyzed" };
    }
    if (sets.used[fn]) {
      // Needed by the current selection: protected from deletion here.
      return { disabled: true, checked: false, lock: "used", note: "Used" };
    }
    if (sets.candidateSet[fn]) {
      // Detected top-level the submitter hasn't selected: deletable, but never
      // auto-checked -- they may pick it next.
      return { disabled: false, checked: false, lock: null, note: "Not used" };
    }
    if (sets.maybeSet[fn]) {
      // Coarse "possibly used" guess: deletable but not suggested.
      return { disabled: false, checked: false, lock: null, note: "Possibly used" };
    }
    // Nothing in the current selection references it: pre-check for deletion
    // (mirrors the server auto-check, SUBMISSION-222). Nothing is deleted until
    // Continue.
    return { disabled: false, checked: true, lock: null, note: "Not used" };
  }

  function buildSets(data, roots) {
    var candidateSet = {};
    ((data && data.candidates) || []).forEach(function (f) { candidateSet[f] = true; });
    var maybeSet = {};
    ((data && data.maybe_used) || []).forEach(function (f) { maybeSet[f] = true; });
    var unanalyzedSet = {};
    ((data && data.unanalyzed) || []).forEach(function (f) { unanalyzedSet[f] = true; });
    var rootSet = {};
    (roots || []).forEach(function (r) { rootSet[r] = true; });
    return {
      rootSet: rootSet,
      used: reachableFrom(roots, (data && data.edges) || {}),
      candidateSet: candidateSet,
      maybeSet: maybeSet,
      unanalyzedSet: unanalyzedSet,
    };
  }

  function recompute(data) {
    var sets = buildSets(data, selectedTopLevels());
    fileCheckboxes().forEach(function (cb) {
      // 00README is permanently locked server-side; never touch it.
      if (cb.dataset.lock === "permanent") { return; }
      var s = classify(cb.value, sets);
      cb.disabled = s.disabled;
      cb.checked = s.checked;
      if (s.lock) { cb.dataset.lock = s.lock; } else { delete cb.dataset.lock; }
      setNote(cb, s.note);
      setTint(cb);
    });
  }

  if (typeof window !== "undefined") { window.addEventListener("DOMContentLoaded", function () {
    var data = readData();
    if (!data) { return; }  // no graph -> leave the server render as-is
    // Re-run on any top-level change. The multi-select widget
    // (review_top_level_select.js) dispatches a change on the first select
    // after add/remove/reorder, so that path is covered too.
    topLevelSelects().forEach(function (sel) {
      sel.addEventListener("change", function () { recompute(data); });
    });
    document.addEventListener("change", function (e) {
      if (e.target && e.target.classList &&
          e.target.classList.contains("top-level-select")) {
        recompute(data);
      }
    });
    // Establish a consistent state on load (also unchecks any detected
    // top-level candidate the server pre-checked).
    recompute(data);
  }); }

  // Exported for the parity/classification tests (Node). No effect in browser.
  if (typeof module !== "undefined" && module.exports) {
    module.exports = { reachableFrom: reachableFrom, classify: classify, buildSets: buildSets };
  }
})();
