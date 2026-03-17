"""
Are there tests in the graveyard?
YES

What api tests are in the graveyard?
1. test_api.py has some UnitTest style tests that use mocking. USELESS: ALMOST ALL MOCKED
4. DONE tests/schedule has tests of the publish schedule
7. DONE domain/tests and domain/events/tests has tests of events.

API tests done for now, 78% coverage.

Other tests in the graveyard?
2. test_classic_integration has some extensive tests.
3. tests/examples has some good flask app tests of common use cases
5. tests/serializer has test of save and load of a submission
6. services/tests has some tests with legacy integration

This is a good set of tests. Let's try to reuse these.
"""