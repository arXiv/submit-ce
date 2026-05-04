import json
import os
import sys

try:
    from .preflight import PreflightResponse
    from .zerozeroreadme import ZeroZeroReadMe
    from .directives import DirectiveManager as DM
except ImportError:
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
    from submit_ce.implementations.compile.preflight import PreflightResponse
    from submit_ce.implementations.compile.zerozeroreadme import ZeroZeroReadMe
    from submit_ce.implementations.compile.directives import DirectiveManager as DM


class DirectiveManager:

    def convert_preflight_to_directives(
            self,
            zzrm_content: str,
            preflight_content: str,
    ) -> dict:

        # To keep this version of the submission-tools as
        # similar as possible to the legacy repo, this is 
        # a hack, that tells the directive manager that the
        # 00README does not exist, and not to try to load
        # it from the local filesystem.
        if zzrm_content == None:
            zzrm_content = ""

        dm = DM(zzrm_content=zzrm_content, preflight_content=preflight_content)
        directives = {}
        serial = dm.process_directives()
        directives["directives"] = serial
        preflight_data = dm.load_preflight_data(preflight_content=preflight_content)
        directives["preflight"] = preflight_data
        return directives


# python directive_manager2.py 00README.json 
if __name__ == "__main__":
    if sys.argv[1] == "":
        zzrm_content = ""
    else:
        zzrm_content = open(sys.argv[1]).read()
 
    preflight_content = open(sys.argv[2]).read()

    #print("zzrm_content", type(zzrm_content))
    #print("preflight_content", type(preflight_content))

    print(json.dumps(
        DirectiveManager().convert_preflight_to_directives(
            zzrm_content,
            preflight_content,
        ), indent=2)
    )
