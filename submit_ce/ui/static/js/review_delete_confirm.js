// review_delete_confirm.js  (SUBMISSION-253)
//
// Progressive enhancement for the Review Files page: a confirmation dialog on
// Continue, mirroring Submit 1.5's confirm-on-delete. The Review page deletes
// every checked file when the user continues (including the unused files it
// auto-checks, SUBMISSION-222), invalidating preflight and routing back to
// Upload. That is destructive and, unlike the Upload page's per-file/dir
// deletes, previously had no confirmation. This intercepts Continue when any
// deletable files are checked, lists them, and only submits on confirm.
//
// With JavaScript off, the modal never appears and Continue behaves exactly as
// before -- the no-JS path is unchanged.
(function () {
  "use strict";

  // Files marked for deletion: checked, submittable per-file checkboxes. The
  // folder cascade checkbox has no `name`, so it is naturally excluded.
  function deletions() {
    return Array.prototype.slice.call(
      document.querySelectorAll('input[name="selected_files"]:checked')
    );
  }

  window.addEventListener("DOMContentLoaded", function () {
    var overlay = document.getElementById("review-delete-overlay");
    var dialog = document.getElementById("review-delete-dialog");
    var listEl = document.getElementById("review-delete-list");
    var countEl = document.getElementById("review-delete-count");
    var cancelBtn = document.getElementById("review-delete-cancel");
    var proceedBtn = document.getElementById("review-delete-proceed");
    var closeBtn = document.getElementById("review-delete-close");
    var form = document.getElementById("form");

    // If the modal partial isn't on the page, leave native behavior in place.
    if (!overlay || !dialog || !proceedBtn || !form) { return; }

    var pendingButton = null;  // the Continue button we intercepted
    var lastFocus = null;

    function openModal(files, button) {
      pendingButton = button;
      lastFocus = document.activeElement;
      listEl.innerHTML = "";
      files.forEach(function (cb) {
        var li = document.createElement("li");
        li.textContent = cb.value;
        listEl.appendChild(li);
      });
      countEl.textContent = "By continuing the following " + files.length +
        (files.length === 1 ? " file will be deleted:" : " files will be deleted:");
      overlay.hidden = false;
      dialog.focus();
      document.addEventListener("keydown", onKeydown);
    }

    function closeModal() {
      overlay.hidden = true;
      pendingButton = null;
      document.removeEventListener("keydown", onKeydown);
      if (lastFocus) { lastFocus.focus(); }
    }

    function onKeydown(e) {
      if (e.key === "Escape") { closeModal(); }
    }

    // Intercept only the "Continue" (next) action, and only when files are
    // actually marked for deletion. Go Back and other actions are untouched;
    // continuing with nothing checked proceeds straight through.
    document.querySelectorAll('button[name="action"][value="next"]').forEach(
      function (btn) {
        btn.addEventListener("click", function (e) {
          var files = deletions();
          if (files.length === 0) { return; }  // nothing to confirm
          e.preventDefault();
          openModal(files, btn);
        });
      }
    );

    proceedBtn.addEventListener("click", function () {
      var btn = pendingButton;
      closeModal();
      // Submit as if the intercepted Continue button was the submitter so its
      // name/value (action=next) is included -- form.submit()/requestSubmit()
      // with no submitter would drop it, and the controller keys off action.
      if (form.requestSubmit && btn) {
        form.requestSubmit(btn);
      } else {
        if (btn && btn.name) {
          var hidden = document.createElement("input");
          hidden.type = "hidden";
          hidden.name = btn.name;
          hidden.value = btn.value;
          form.appendChild(hidden);
        }
        form.submit();
      }
    });

    cancelBtn.addEventListener("click", closeModal);
    if (closeBtn) { closeBtn.addEventListener("click", closeModal); }
    overlay.addEventListener("click", function (e) {
      if (e.target === overlay) { closeModal(); }
    });
  });
})();
