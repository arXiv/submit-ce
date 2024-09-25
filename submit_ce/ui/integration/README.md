Integration tests for submission system
============================

The test in test_integration runs through all the submission steps in
a basic manner.

Running the integration test
============================

``` bash
export INTEGRATION_JWT=eyJ0ex...
export INTEGRATION_URL='http://localhost:8000'
pipenv run python -m submit.integration.test_integration
```

TODO: Docker compose for Integration

TODO: Automate integration test on travis or something similar 

