from typing import Optional


class DirectiveManager:
    '''This class is used for simple tasks related to the compiler.
    See compile_api_service.py for endpoints called in tex2pdf-api.'''

    _PREFLIGHT_LANG_TO_SOURCE_FORMAT = {
        "tex": "tex",
        "pdf": "pdf",
        "latex": "tex",
        "html": "html",
    }

    def get_lang_from_preflight(preflight_data: dict) -> Optional[str]:
        '''Return a SourceFormat value derived from gcp_preflight.json.

        Looks at detected_toplevel_files[0].process.compiler.lang and maps
        it to a valid `submit_ce.domain.uploads.SourceFormat` value:
        "pdf" -> "pdf", "latex" -> "tex", "html" -> "html". Returns None
        if preflight data is missing or the lang isn't one of those.
        detected_toplevel_files is an array; we use the first element.
        '''
        if not preflight_data:
            return None
        toplevel = preflight_data.get('detected_toplevel_files') or []
        if not toplevel:
            return None
        process = toplevel[0].get('process') or {}
        compiler = process.get('compiler') or {}
        lang = compiler.get('lang')
        return DirectiveManager._PREFLIGHT_LANG_TO_SOURCE_FORMAT.get(lang)

    def convert_zzrm_to_user_decisions(zzrm: dict) -> dict:
        '''Example user_decisions.json:
        {
            "sources": [{"filename": "main1.tex", "usage" : "toplevel"}],
            "texlive_version": "2025",
            "process": {"compiler": "pdflatex"}
        }
        '''
        result = {}
        if 'sources' in zzrm:
            result['sources'] = [
                {'filename': s['filename']}
                for s in zzrm['sources']
                if s.get('usage') == 'toplevel'
            ]
        if 'texlive_version' in zzrm:
            result['texlive_version'] = zzrm['texlive_version']
        if 'process' in zzrm:
            result['process'] = {k: v for k, v in zzrm['process'].items()
                                 if k in ('compiler',)}
        return result

    def used_source_filenames(preflight_data: dict) -> set:
        '''Filenames preflight *resolved* a reference to (confidently used).

        The union of every tex file's ``used_other_files`` / ``used_tex_files`` /
        ``used_bib_files`` -- the resolved-edge set. These are high-confidence
        "this file is needed" signals (unlike ``maybe_used_files``, a coarse
        guess). Used by the Review Files delete-guard to refuse deletion of
        confidently-used files (SUBMISSION-221 / C3.2a).
        '''
        used: set = set()
        for tex_file in (preflight_data or {}).get('tex_files', []):
            for key in ('used_other_files', 'used_tex_files', 'used_bib_files'):
                for name in tex_file.get(key, []):
                    if name:
                        used.add(name)
        return used

    def used_edges(preflight_data: dict) -> dict:
        '''Adjacency list ``{tex_filename: [referenced filenames]}``.

        Preflight's resolved-reference graph, flattened per tex file from
        ``used_tex_files`` / ``used_other_files`` / ``used_bib_files``. Shared by
        ``reachable_from`` (the server-side rooted walk) and embedded verbatim in
        the Review Files page so the client-side live recompute walks the *same*
        graph (SUBMISSION-231). One definition, two consumers.
        '''
        adjacency: dict = {}
        for tex_file in (preflight_data or {}).get('tex_files', []):
            name = tex_file.get('filename')
            if not name:
                continue
            refs = adjacency.setdefault(name, [])
            for key in ('used_tex_files', 'used_other_files', 'used_bib_files'):
                refs.extend(r for r in tex_file.get(key, []) if r)
        return adjacency

    def reachable_from(roots, preflight_data: dict) -> set:
        '''Files reachable from `roots` over preflight's resolved-edge graph.

        The rooted counterpart of ``used_source_filenames``: instead of the flat
        union of *every* tex file's resolved edges, walk the reference graph
        starting from the selected top-level file(s) and return every file
        transitively referenced. This is what lets the "used / not used"
        classification change with the top-level selection (SUBMISSION-231)
        **without re-running preflight** -- the edges are already in the report,
        so re-rooting is just a graph traversal (consistent with SUBMISSION-215,
        which keeps the report valid on selection-only changes).

        Traversal is transitive (a used ``.tex`` may pull in further files). The
        roots themselves are excluded from the result -- they are the selected
        top-levels, classified separately (is_toplevel) and protected on their
        own. Uses the same adjacency (`used_edges`) embedded for the client.
        '''
        adjacency = DirectiveManager.used_edges(preflight_data)
        root_set = {r for r in (roots or []) if r}
        used: set = set()
        stack = list(root_set)
        while stack:
            node = stack.pop()
            for ref in adjacency.get(node, ()):
                if ref not in used and ref not in root_set:
                    used.add(ref)
                    stack.append(ref)  # transitive: a used file may reference more
        return used

    def get_files_from_preflight(preflight_data: dict) -> list:
        files = {}
        # Object sections: each entry is a dict carrying a 'filename'.
        for section in ('detected_toplevel_files', 'tex_files', 'image_files'):
            for f in preflight_data.get(section, []):
                filename = f.get('filename')
                if filename and filename not in files:
                    files[filename] = {'filename': filename}
        # Plain-string sections: PreflightResponse types ancillary_files and
        # maybe_used_files as list[str], so each entry is a filename string, not
        # a dict. (These are almost always empty, which is why treating them as
        # dicts went unnoticed until a .pygtex file populated maybe_used_files.)
        for section in ('ancillary_files', 'maybe_used_files'):
            for filename in preflight_data.get(section, []):
                if filename and filename not in files:
                    files[filename] = {'filename': filename}

        # Tag maybe-used files (SUBMISSION-221 / C3.2a). These are a low-confidence
        # guess -- preflight kept them (by extension: only .pygtex) but couldn't
        # resolve a reference. Tagging lets the UI label them "Possibly used" (not
        # "Not used") and leave them deletable but unprotected. A resolved edge
        # below wins over this flag (handled in build_file_rows).
        for filename in preflight_data.get('maybe_used_files', []):
            if filename:
                files[filename]['is_maybe_used'] = True

        for tex_file in preflight_data.get('tex_files', []):
            tex_name = tex_file.get('filename')
            if not tex_name:
                continue
            for key, ref_key in (('used_other_files', 'used_by'),
                                  ('used_tex_files',   'used_by_tex'),
                                  ('used_bib_files',   'used_by_bib')):
                for used in tex_file.get(key, []):
                    files.setdefault(used, {'filename': used})
                    files[used].setdefault(ref_key, []).append(tex_name)

        # Carry per-image size metadata so the Review Files table can show
        # dimensions and highlight oversized images (SUBMISSION-172).
        # is_oversized is authoritative from preflight -- it already encodes
        # "megapixels > threshold AND not pdftex-fast-copy", so a fast-copy
        # image (e.g. JPEG, clean RGB PNG) is never oversized regardless of
        # size. We surface these fields; we do not recompute the flag.
        for img in preflight_data.get('image_files', []):
            filename = img.get('filename')
            if not filename:
                continue
            entry = files.setdefault(filename, {'filename': filename})
            entry['width'] = img.get('width')
            entry['height'] = img.get('height')
            entry['megapixels'] = img.get('megapixels')
            entry['file_bytes'] = img.get('file_bytes')
            entry['is_oversized'] = img.get('is_oversized', False)

        return list(files.values())