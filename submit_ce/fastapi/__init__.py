"""Submission mutation REST API (SUBMISSION-257).

A FastAPI service that lets other services (starting with arxiv-check) mutate
submissions through the Submit 2.0 event model (`SubmitApi.save()`), never by
writing the database directly. Deliberately separate from `submit_ce.sword`;
built on the same non-Flask wiring (`FastapiSubmitImplementation`).
"""
