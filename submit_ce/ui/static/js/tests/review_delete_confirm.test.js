// Node test for review_delete_confirm.js (SUBMISSION-253).
// No DOM library / test runner needed -- run with:
//   node review_delete_confirm.test.js
// Exits non-zero on failure.
//
// The source file is DOM-driven (it wires a confirmation modal to the Review
// Files Continue button), so this provides a minimal hand-rolled DOM stub --
// just enough of document/window for the file's selectors and event wiring --
// and drives it through the three behaviors that matter:
//   1. Continue with files checked  -> intercepted, modal opens listing them.
//   2. Proceed                      -> submits via requestSubmit(button) so the
//                                       action=next value is preserved.
//   3. Continue with nothing checked -> NOT intercepted (native submit).
// Plus Cancel/Escape closing without submitting.

const assert = require("assert");

// --- minimal DOM stub -------------------------------------------------------

function makeEl(props) {
  const listeners = {};
  const el = Object.assign({
    tagName: "DIV",
    children: [],
    hidden: false,
    textContent: "",
    _innerHTML: "",
    disabled: false,
    checked: false,
    name: "",
    value: "",
    attrs: {},
    classList: { contains: function () { return false; } },
    addEventListener: function (type, fn) {
      (listeners[type] = listeners[type] || []).push(fn);
    },
    dispatch: function (type, evt) {
      evt = evt || {};
      evt.type = type;
      evt.target = evt.target || el;
      (listeners[type] || []).forEach(function (fn) { fn(evt); });
    },
    appendChild: function (child) { el.children.push(child); },
    focus: function () {},
  }, props || {});
  Object.defineProperty(el, "innerHTML", {
    get: function () { return el._innerHTML; },
    set: function (v) { el._innerHTML = v; if (v === "") { el.children = []; } },
  });
  return el;
}

function buildDom(checkedFiles) {
  const overlay = makeEl({ id: "review-delete-overlay", hidden: true });
  const dialog = makeEl({ id: "review-delete-dialog" });
  const list = makeEl({ id: "review-delete-list" });
  const count = makeEl({ id: "review-delete-count" });
  const cancel = makeEl({ id: "review-delete-cancel" });
  const proceed = makeEl({ id: "review-delete-proceed" });

  let requestSubmitArg = "UNSET";
  const form = makeEl({
    id: "form",
    requestSubmit: function (submitter) { requestSubmitArg = submitter; },
    submit: function () { requestSubmitArg = "form.submit"; },
  });

  const continueBtn = makeEl({
    tagName: "BUTTON", name: "action", value: "next",
    attrs: { name: "action", value: "next" },
  });

  // checkedFiles: array of {value, checked}
  const fileEls = checkedFiles.map(function (f) {
    return makeEl({
      tagName: "INPUT", name: "selected_files",
      value: f.value, checked: f.checked, disabled: false,
    });
  });

  const byId = {
    "review-delete-overlay": overlay,
    "review-delete-dialog": dialog,
    "review-delete-list": list,
    "review-delete-count": count,
    "review-delete-cancel": cancel,
    "review-delete-proceed": proceed,
    "form": form,
  };

  const windowListeners = {};
  const documentListeners = {};

  global.document = {
    getElementById: function (id) { return byId[id] || null; },
    createElement: function (tag) { return makeEl({ tagName: tag.toUpperCase() }); },
    querySelectorAll: function (sel) {
      if (sel === 'input[name="selected_files"]:checked') {
        return fileEls.filter(function (e) { return e.checked; });
      }
      if (sel === 'button[name="action"][value="next"]') {
        return [continueBtn];
      }
      return [];
    },
    addEventListener: function (t, fn) {
      (documentListeners[t] = documentListeners[t] || []).push(fn);
    },
    removeEventListener: function (t, fn) {
      documentListeners[t] = (documentListeners[t] || [])
        .filter(function (f) { return f !== fn; });
    },
    dispatchDocument: function (type, evt) {
      evt = evt || {}; evt.type = type;
      (documentListeners[type] || []).slice().forEach(function (fn) { fn(evt); });
    },
    activeElement: makeEl({}),
  };

  global.window = {
    addEventListener: function (t, fn) {
      (windowListeners[t] = windowListeners[t] || []).push(fn);
    },
    fire: function (type) { (windowListeners[type] || []).forEach(function (fn) { fn(); }); },
  };

  return {
    overlay: overlay, list: list, count: count,
    cancel: cancel, proceed: proceed, form: form, continueBtn: continueBtn,
    ready: function () { global.window.fire("DOMContentLoaded"); },
    requestSubmitArg: function () { return requestSubmitArg; },
    escape: function () { global.document.dispatchDocument("keydown", { key: "Escape" }); },
  };
}

function loadFresh() {
  delete require.cache[require.resolve("../review_delete_confirm.js")];
  require("../review_delete_confirm.js");
}

// --- 1. Continue with files checked -> intercept + open modal ---------------
{
  const dom = buildDom([{ value: "unused1.tex", checked: true },
                        { value: "fig/extra.png", checked: true }]);
  loadFresh();
  dom.ready();

  let prevented = false;
  dom.continueBtn.dispatch("click", { preventDefault: function () { prevented = true; } });

  assert.strictEqual(prevented, true, "Continue is intercepted when files are checked");
  assert.strictEqual(dom.overlay.hidden, false, "modal is shown");
  assert.strictEqual(dom.list.children.length, 2, "both checked files are listed");
  assert.deepStrictEqual(dom.list.children.map(function (li) { return li.textContent; }),
    ["unused1.tex", "fig/extra.png"], "listed values match the checked files");
  assert.ok(/2 files/.test(dom.count.textContent), "count reflects 2 files");
  assert.strictEqual(dom.requestSubmitArg(), "UNSET", "nothing submitted yet");

  // Proceed -> submits with the intercepted button as submitter.
  dom.proceed.dispatch("click");
  assert.strictEqual(dom.requestSubmitArg(), dom.continueBtn,
    "proceed submits via requestSubmit(continueButton) so action=next is kept");
  assert.strictEqual(dom.overlay.hidden, true, "modal closes on proceed");
}

// --- 2. Cancel closes without submitting ------------------------------------
{
  const dom = buildDom([{ value: "unused1.tex", checked: true }]);
  loadFresh();
  dom.ready();
  dom.continueBtn.dispatch("click", { preventDefault: function () {} });
  assert.strictEqual(dom.overlay.hidden, false);
  dom.cancel.dispatch("click");
  assert.strictEqual(dom.overlay.hidden, true, "modal closes on cancel");
  assert.strictEqual(dom.requestSubmitArg(), "UNSET", "cancel submits nothing");
}

// --- 3. Escape closes without submitting ------------------------------------
{
  const dom = buildDom([{ value: "unused1.tex", checked: true }]);
  loadFresh();
  dom.ready();
  dom.continueBtn.dispatch("click", { preventDefault: function () {} });
  dom.escape();
  assert.strictEqual(dom.overlay.hidden, true, "modal closes on Escape");
  assert.strictEqual(dom.requestSubmitArg(), "UNSET", "escape submits nothing");
}

// --- 4. Continue with nothing checked -> NOT intercepted (native submit) ----
{
  const dom = buildDom([{ value: "unused1.tex", checked: false }]);
  loadFresh();
  dom.ready();
  let prevented = false;
  dom.continueBtn.dispatch("click", { preventDefault: function () { prevented = true; } });
  assert.strictEqual(prevented, false, "Continue not intercepted when nothing is checked");
  assert.strictEqual(dom.overlay.hidden, true, "modal stays hidden");
}

// --- 5. Count uses singular for exactly one file ----------------------------
{
  const dom = buildDom([{ value: "solo.tex", checked: true }]);
  loadFresh();
  dom.ready();
  dom.continueBtn.dispatch("click", { preventDefault: function () {} });
  assert.ok(/1 file will/.test(dom.count.textContent), "singular phrasing for one file");
}

console.log("review_delete_confirm.test.js: all assertions passed");
