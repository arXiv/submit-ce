# Preflight error test submissions

A set of small TeX/PDF submissions, each crafted to trigger one of the important
preflight issue codes surfaced on the Review Files page (SUBMISSION-210 / C1).
Every case was **run through `tex2pdf_tools.preflight` and verified** to produce
the intended result (see `VERIFICATION.txt` and the table below).

Each source folder contains an `EXPECTED_ERRORS.txt` describing the code and the
mechanism. Upload-ready archives are in `tarballs/`.

## How to run preflight locally

```bash
# from the tex2pdf-tools checkout (needs Python 3.11+, or PYTHONPATH on 3.10)
python -m tex2pdf_tools.preflight parse <source_dir>
```

The JSON has issues in two places: `tex_files[].issues` (per file) and
`detected_toplevel_files[].issues` (per top-level). `issue_in_subfile` is a
benign meta-issue (the UI treats it as *silent*) and appears alongside many
real issues.

## Cases (all verified)

| # | Folder | Expected code | Severity | Verified result |
|---|--------|---------------|----------|-----------------|
| 01 | `01_conflicting_file_type` | `conflicting_file_type` | danger | fires in issues[] |
| 02 | `02_latex209` | `unsupported_compiler_type_latex209` | danger | fires |
| 03 | `03_conflicting_output_type` | `conflicting_output_type` | warning | **detected but NOT surfaced** — producer bug (see note) |
| 04 | `04_file_not_found` | `file_not_found` | warning | fires |
| 05 | `05_graphics_driver_unsupported` | `graphics_driver_unsupported` | warning | fires |
| 06 | `06_graphics_driver_option` | `graphics_driver_option` | info | fires |
| 08 | `08_unsupported_zzrm_format` | `unsupported_zzrm_format` | warning | fires |
| 09 | `09_multiple_bibliography_types` | `multiple_bibliography_types` (+`file_not_found`) | danger | fires |
| 10 | `10_bbl_bib_file_missing` | `bbl_bib_file_missing` (+`file_not_found`) | danger | fires |
| 11 | `11_bbl_version_mismatch` | `bbl_version_mismatch` (+`file_not_found`) | danger | fires |
| 12 | `12_bbl_version_needs_previous` | `bbl_version_needs_previous_version` (+`file_not_found`) | warning | fires |
| 13 | `13_bbl_usage_mismatch` | `bbl_usage_mismatch` | danger | fires |
| 14 | `14_no_top_level_file` | `no_top_level_file` (derived) | danger | `status=success`, **empty** `detected_toplevel_files` |
| 15 | `15_oversized_image` | `oversized_image` | warning | fires (36 MP > 34 MP) — but flat PNG is **env-dependent** (needs `pngcheck` to be fast-copy); see 20 |
| 16 | `16_pdf_not_pdf` | `pdf_not_pdf` | danger | surfaces as `status=error` QA message |
| 17 | `17_pdf_javascript` | `pdf_javascript` | warning | fires (PDF-only submission) |
| 18 | `18_index_definition_missing` | `index_definition_missing` | warning | fires |
| 19 | `19_multiple_issues` | **many at once**: `multiple_bibliography_types` (danger) + `file_not_found` x3, `graphics_driver_unsupported`, `oversized_image`, `index_definition_missing`, `unsupported_zzrm_format` (warning) + `hyperref_not_found` (info) | mixed | fires; reaches Review Files |
| 20 | `20_oversized_fastcopy_vs_slow` | `oversized_image` (warning) — demonstrates the **oversize row highlight** | warning | JPEG (36 MP) = fast-copy → shown, **not** highlighted; RGBA PNG (36 MP) = not fast-copy → shown **and** highlighted. Deterministic across environments. |
| 21 | `21_delete_protection_tiers` | `oversized_image` (warning) — but the point is the **delete-protection tiers** (C3.2a) + used/not-used labels (C3.1a) + image size (C3.5) | warning | used files (top-level, `\input`, `\usepackage`, `\includegraphics`) delete-**disabled** & "Used by…"; `.pygtex` → "Possibly used", deletable; unreferenced → "Not used", deletable; RGBA PNG 36 MP → oversized row highlight. Also exercises the string-typed `maybe_used_files` path. |
| 22 | `22_dotslash_delete_bug` | **regression fixture** (not an issue-code test) — archive-path normalization | — | Packed **with `./`** on purpose (`tar -C dir .`) so files store as `.../src/./…`. Until the extraction-normalization bug is fixed, checking `orphan.txt` for deletion + Continue does **nothing** (files_to_delete emptied by the `./` mismatch). After the fix, the file deletes. See its `EXPECTED_ERRORS.txt`. |
| 23 | `23_nested_directories` | **cascade UI fixture** (SUBMISSION-223) — nested directories | — | Folders on load: `junk/` CHECKED (all children unused), `sections/` + `figures/` + `figures/extra/` INDETERMINATE (mix of locked-used and auto-checked-unused). Toggling `figures/` cascades into `figures/extra/` (nested), skipping locked used files. Packed without `./`. |
| 24 | `24_corrupt_archive` | **corrupt-archive handling fixture** — truncated `.tar.gz` | — | The tarball IS the corrupt upload (valid gzip header, truncated mid-stream). Upload it on Upload Files: before the fix → generic "problem uploading"; after → specific "we couldn't read your file…" message. No 500 either way. See its `EXPECTED_ERRORS.txt`. |
| 25 | `25_two_top_levels` | **multiple top-level probe** (C2 / C2.1) — two standalone TeX files | — | main1.tex + main2.tex, each a complete document, no deps. Upload to **production 1.5** to observe deployed multi-top-level behavior (are both offered/orderable; does the PDF concatenate both; any max-top-level message). Informs the C2.1 compile-cap questions. |
| 26 | `26_path_traversal` | **security/hardening fixture** (SUBMISSION-230) — unsafe archive member | — | Three artifacts, each `main.tex` + one unsafe member: `.tar.gz` (`../../evil.tex`), `.zip` (`../evil.tex`), and `_absolute.tar.gz` (`/etc/evil.tex`). Upload any on Upload Files: extraction must **reject the whole archive** (friendly "unsafe path" flash), writing nothing under the submission's source — not even the valid `main.tex` — and never 500. Sibling of case 22 (benign `./`). See its `EXPECTED_ERRORS.txt`. |

> **Tarball packing:** every case except **22** and **26** is packed **without**
> a leading `./` (repacked via `find . -mindepth 1 -printf '%P\n' | tar
> --no-recursion -T -`), so filenames match preflight/workspace paths and file
> deletion works. Case 22 intentionally keeps `./` to reproduce the
> extraction-normalization bug; case 26 intentionally packs a `..` traversal
> member to exercise rejection — do not "fix" either.

### Not included
- **`unsupported_compiler_type_unicode`** — currently unreachable: a `fontspec`
  document compiles under XeTeX/LuaTeX, which *are* supported compilers, so the
  "Unicode engine not available" branch never triggers in the present config.

## Notes worth knowing

**`conflicting_output_type` never surfaces (producer bug).** Case 03 sets both
`\pdfoutput=1` and `\pdfoutput=0`. Preflight detects both flags, appends the
issue to `tl.issues` (`preflight/__init__.py` ~line 1435), but then the end of
`guess_compilation_parameters()` runs `tl.issues = issues` (~line 1553), which
**overwrites** the just-appended issue with a fresh list. Every other issue in
that function is appended to the local `issues` list instead, so only
`conflicting_output_type` is lost. Our UI directive for it is effectively dead
until the producer is fixed. Case 03 is kept as a regression case.

**`pdf_not_pdf` and no-top-level surface via `status`, not `issues[]`.** Case 16
comes back as `status=error` with `info="QA check failed: Found 1 PDFs that
don't look like a PDF."`; case 14 comes back as `status=success` with an empty
`detected_toplevel_files`. Neither lands in an `issues[]` array, so the 2.0
Review-page extractor (`build_issue_context`, which reads `issues[]`) would need
to also inspect `status` / the empty-top-level condition to show these — worth
confirming during C1.

**What Submit 1.5 does with no top-level file (case 14).** In 1.5's
`addfiles`/`checkfiles` flow (`Submit.pm` ~line 852), preflight's
`detected_top_level_files` is present but an empty list, so the loop that builds
the top-level dropdown and compiler options runs zero times: the Review page
renders with **no top-level file to choose and no compiler options**, and no
explicit error banner (the `no_top_level_file` directive was kept *silent* in
1.5). The user is effectively stuck with an empty selector. This is the case to
open in a running 1.5 to confirm the live behavior, and it motivates 2.0
surfacing an explicit `no_top_level_file` danger message rather than a silent
empty selector.
