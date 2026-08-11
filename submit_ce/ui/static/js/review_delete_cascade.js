// review_delete_cascade.js  (SUBMISSION-223)
//
// Progressive enhancement for the Review Files page. A directory row's Delete
// checkbox toggles every DELETABLE file checkbox beneath it, and reflects the
// combined state of those files (checked / unchecked / indeterminate).
//
// The folder checkbox has no `name`, so it is never submitted -- only the
// per-file `selected_files` checkboxes are. With JavaScript off the page still
// works; the folder box simply does nothing and files are toggled individually.
//
// A file "belongs to" a directory when its checkbox value starts with the
// directory's `data-dir` prefix (values are the preflight-normalized paths, so
// a nested file matches every ancestor directory's prefix).
(function () {
  "use strict";

  function dirCheckboxes() {
    return document.querySelectorAll('input.dir-delete[data-dir]');
  }

  function fileCheckboxes() {
    return document.querySelectorAll('input[name="selected_files"]');
  }

  // Deletable descendants of a directory: file checkboxes under its prefix that
  // are not disabled/locked (used, top-level and 00README can't be deleted
  // here, so they never participate in the cascade or its state).
  function descendants(dir) {
    var prefix = dir.dataset.dir;
    var out = [];
    fileCheckboxes().forEach(function (cb) {
      if (!cb.disabled && cb.value.indexOf(prefix) === 0) {
        out.push(cb);
      }
    });
    return out;
  }

  // Recompute every folder's checked/indeterminate from its descendants.
  function syncDirStates() {
    dirCheckboxes().forEach(function (dir) {
      var kids = descendants(dir);
      var checked = kids.filter(function (cb) { return cb.checked; }).length;
      if (kids.length === 0 || checked === 0) {
        dir.checked = false;
        dir.indeterminate = false;
      } else if (checked === kids.length) {
        dir.checked = true;
        dir.indeterminate = false;
      } else {
        dir.checked = false;
        dir.indeterminate = true;
      }
    });
  }

  window.addEventListener("DOMContentLoaded", function () {
    dirCheckboxes().forEach(function (dir) {
      dir.addEventListener("change", function () {
        descendants(dir).forEach(function (cb) { cb.checked = dir.checked; });
        syncDirStates();
      });
    });
    fileCheckboxes().forEach(function (cb) {
      cb.addEventListener("change", syncDirStates);
    });
    // "Keep All" unchecks boxes directly (no change event); resync afterward.
    document.querySelectorAll('.keep-all-link').forEach(function (link) {
      link.addEventListener("click", function () { setTimeout(syncDirStates, 0); });
    });
    // Initialise folder states from the server-rendered (auto-checked) files.
    syncDirStates();
  });
})();
