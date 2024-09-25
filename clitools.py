import os
import tempfile
import time
import subprocess
import random
from typing import Optional

import fire

def gen_openapi_json(file:str = "openapi.json"):
    """Generate an openapi.yaml file for the current server code."""
    import uvicorn
    import requests
    port = random.randint(9000, 12000)
    command = f"uvicorn submit_ce.api.app:app --host 127.0.0.1 --port {port}".split()
    process = subprocess.Popen(command)
    time.sleep(1)
    try:
        response = requests.get("http://127.0.0.1:%d/openapi.json" % port)
        if response.status_code != 200:
            raise RuntimeError(f"Could not get openapi.yaml from server {response.status_code}: {response.text}")
        with open(file, "w") as f:
            f.write(response.text)
        print(f"Wrote openapi spec in json format to {file}")
    finally:
        process.kill()


def gen_client(gen_spec:bool = True):
    """Generate the API client for the current server code.

    ARGS:
        gen_spec (bool): Whether to generate a spec file or attempt to use an exsiting one.
    """

    if gen_spec:
        print(f"* Generating to openapi.json for current code")
        gen_openapi_json()

    command = f"""
      docker run --rm
      --user {str(os.getuid()) + ":" + str(os.getgid())}
      -v ./:/local
      openapitools/openapi-generator-cli generate
      -i /local/openapi.json
      -g python
      -o /local/submit_client
      --api-package submit_client
      --minimal-update
    """
    print(command)
    process = subprocess.Popen(command.split())
    process.wait()


if __name__ == "__main__":
    fire.Fire(
        {
        "gen_openapi_json":gen_openapi_json,
            "gen_client":gen_client,
            }
        )
