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

    def get_files_from_preflight(preflight_data: dict) -> list:
        files = {}
        for section in ('detected_toplevel_files', 'tex_files', 'ancillary_files', 'maybe_used_files', 'image_files'):
            for f in preflight_data.get(section, []):
                filename = f.get('filename')
                if filename and filename not in files:
                    files[filename] = {'filename': filename}

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

        return list(files.values())