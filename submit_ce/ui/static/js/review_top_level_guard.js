// review_top_level_guard.js  (SUBMISSION-209)
//
// Progressive enhancement for the Review Files page. Keeps each file's Delete
// checkbox in sync with the currently-selected top-level TeX file(s) *without*
// a server round-trip: a selected top-level file is what we are about to
// compile, so it must not be deletable, and a file that is no longer a
// top-level should become deletable again.
//
// This only mirrors, in the browser, a rule the server already enforces
// authoritatively (SetDecisions refuses to delete a selected top-level file).
// With JavaScript off, the page still behaves correctly -- the checkbox states
// simply update on the next server render instead of live.
//
// Written to handle one OR MORE top-level selects, so it is ready for the
// multiple-top-level UI (C2).
(function () {
  "use strict";

  function topLevelSelects() {
    return document.querySelectorAll(
      'select[name="source_file"], select[name="top_level_tex_files[]"]'
    );
  }

  function selectedTopLevelFiles() {
    var files = [];
    topLevelSelects().forEach(function (sel) {
      if (sel.value && files.indexOf(sel.value) === -1) {
        files.push(sel.value);
      }
    });
    return files;
  }

  function deleteCheckboxes() {
    return document.querySelectorAll('input[name="selected_files"]');
  }

  // Recompute every delete checkbox from the current top-level selection.
  function syncGuards() {
    var selected = selectedTopLevelFiles();
    deleteCheckboxes().forEach(function (cb) {
      // Never touch server-locked rows: "permanent" (00README.json) or "used"
      // (a confidently-used file protected from deletion, SUBMISSION-221 /
      // C3.2a). Without this, the else-branch below would re-enable used-file
      // checkboxes that the server rendered disabled.
      if (cb.dataset.lock) {
        return;
      }
      if (selected.indexOf(cb.value) !== -1) {
        // A selected top-level file: uncheck and lock against deletion.
        cb.checked = false;
        cb.disabled = true;
      } else {
        // No longer a top-level file: allow deletion again.
        cb.disabled = false;
      }
    });
  }

  window.addEventListener("DOMContentLoaded", function () {
    topLevelSelects().forEach(function (sel) {
      sel.addEventListener("change", syncGuards);
    });
    // Re-assert on load so the client state matches the current selection.
    syncGuards();
  });
})();
