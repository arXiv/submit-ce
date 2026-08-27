// Node test for review_used_recompute.js (SUBMISSION-231 part 2).
// No DOM / test runner needed -- run with:  node review_used_recompute.test.js
// Exits non-zero on failure. Covers (a) the reachability walk and (b) the pure
// per-file classify() decision, including the safety rule that a detected but
// unselected top-level is never auto-checked for deletion.
//
// PARITY: reachableFrom() here must match DirectiveManager.reachable_from() in
// submit_ce/implementations/compile/directive_manager.py -- the Python unit
// tests assert the same expected sets on the same graph.

const assert = require("assert");
const { reachableFrom, classify, buildSets } =
  require("../review_used_recompute.js");

// Two independent top-levels with disjoint subtrees + a shared file + a guess.
const DATA = {
  edges: {
    "main1.tex": ["chap1.tex", "shared.png"],
    "chap1.tex": ["fig1.png"],
    "main2.tex": ["chap2.tex", "refs.bib"],
    "chap2.tex": ["fig2.png"],
  },
  candidates: ["main1.tex", "main2.tex"],
  maybe_used: ["guess.sty"],
  unanalyzed: ["stray.txt"],
};

function keys(setObj) { return Object.keys(setObj).sort(); }

// --- reachability (mirror of Python reachable_from) ---
assert.deepStrictEqual(
  keys(reachableFrom(["main1.tex"], DATA.edges)),
  ["chap1.tex", "fig1.png", "shared.png"]);
assert.deepStrictEqual(
  keys(reachableFrom(["main2.tex"], DATA.edges)),
  ["chap2.tex", "fig2.png", "refs.bib"]);
assert.deepStrictEqual(
  keys(reachableFrom(["main1.tex", "main2.tex"], DATA.edges)),
  ["chap1.tex", "chap2.tex", "fig1.png", "fig2.png", "refs.bib", "shared.png"]);
// cycle-safe, roots excluded
assert.deepStrictEqual(
  keys(reachableFrom(["a"], { a: ["b", "a"], b: ["a", "c"] })), ["b", "c"]);
assert.deepStrictEqual(keys(reachableFrom([], DATA.edges)), []);

// --- classify() decisions ---
function state(fn, roots) {
  const s = classify(fn, buildSets(DATA, roots));
  return { disabled: s.disabled, checked: s.checked, note: s.note };
}

// main1 selected
assert.deepStrictEqual(state("main1.tex", ["main1.tex"]),
  { disabled: true, checked: false, note: "Used: top-level file" });
assert.deepStrictEqual(state("fig1.png", ["main1.tex"]),
  { disabled: true, checked: false, note: "Used" });
// detected candidate, unselected -> NOT auto-checked (safety)
assert.deepStrictEqual(state("main2.tex", ["main1.tex"]),
  { disabled: false, checked: false, note: "Not used" });
// genuinely unused -> auto-checked
assert.deepStrictEqual(state("fig2.png", ["main1.tex"]),
  { disabled: false, checked: true, note: "Not used" });
assert.deepStrictEqual(state("guess.sty", ["main1.tex"]),
  { disabled: false, checked: false, note: "Possibly used" });

// main2 selected -> the halves swap
assert.deepStrictEqual(state("main1.tex", ["main2.tex"]),
  { disabled: false, checked: false, note: "Not used" });
assert.deepStrictEqual(state("fig2.png", ["main2.tex"]),
  { disabled: true, checked: false, note: "Used" });

// both selected -> nothing unused
assert.deepStrictEqual(state("chap1.tex", ["main1.tex", "main2.tex"]),
  { disabled: true, checked: false, note: "Used" });
assert.deepStrictEqual(state("chap2.tex", ["main1.tex", "main2.tex"]),
  { disabled: true, checked: false, note: "Used" });

// unanalyzed file: "Not analyzed", never auto-checked, selection-independent
// (SUBMISSION-246)
assert.deepStrictEqual(state("stray.txt", ["main1.tex"]),
  { disabled: false, checked: false, note: "Not analyzed" });
assert.deepStrictEqual(state("stray.txt", ["main2.tex"]),
  { disabled: false, checked: false, note: "Not analyzed" });

// ancillary (anc/) file: "Ancillary", never auto-checked, path-based &
// selection-independent (SUBMISSION-252)
assert.deepStrictEqual(state("anc/readme.txt", ["main1.tex"]),
  { disabled: false, checked: false, note: "Ancillary" });
assert.deepStrictEqual(state("anc/code/lib/helper.py", ["main2.tex"]),
  { disabled: false, checked: false, note: "Ancillary" });

console.log("review_used_recompute.test.js: all assertions passed");
