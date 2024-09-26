# Change log, Reasoning and History
(Newest at top)

# 2024-09-26 UI ever so slightly working, generated client
Brian Caruso

I've got the UI working to render the first page. tests/make_test_db.py works to
make a test db with users and auth works.

There is a generated client in `client`. It can be built with `clitools.py`. I'm
starting to wire up the UI to use that.

I took the NG submission-core and submission-ui and put them in the same project
and then refactored the pacakges. 

# 2024-09-24 Start of UI
Brian Caruso

Starting the UI. I'm going tou use fastapi and reuse the templates and controllers from NG. 
My hope is that the move from flask to fastapi will force us to deal with how controllers get 
data by breaking any place NG uses access to resources via the app or request context or dynamically.

# 2024-09-23 Start of API
Brian Caruso

This project was started as a proof of concept and intendeds to replace the
legacy submit UI. The scope is limited to the UI to submit a paper to arxiv.org
and an API that the UI uses to record and modify submissions. It is also limited
to parity with the existing legacy system.

### API handles both metadata and files

To avoid race conditions related to the handling of files, the API will handle
both files and metadata. This is for simplicity. A hash based file set model was
considered and discarded. A hash based system is not excessively complicated,
but it is more complicated and the NG implementation indicate how easy can go wrong.

### Openapi schema via Fastapi

The new system is starting with a fastapi submission CRUD for paper metadata and
file upload. It took little time to get a bare-bones API working and the fastapi
swagger doc can be used as a primitive UI to submit a paper.

There are several mature libraries that can generate a client from the openapi
spec. This will elevate the writing of boilerplate seen in the NG projects.

### Legacy API integration as v1

The API will start with an implementation that uses the legacy DB and legacy CIT
SFS as the backend.  Once that is in place it can be run at CIT and the UI can
be served at CIT or from the cloud.

There is imperative to get a modernized submit version working ASAP and to not
gold plate the first version since any work put into the legacy is moribund Once
we have a modernized API and UI work can be done that will be forward-looking.

This initial version was quickly bootstrapped using code from modapi as a reference 
and some components from NG.
### Future API implementation v2

Once the API is in operation it will provide a foundation to create a v2 API
that supports future needs.

### Use and install of arxiv-base

The new submit does not use flask. It installs the arxiv-base package without
dependencies. This minimizes the size of the installation.

At this point, the new submit uses pydantic 2 and arxiv-base uses v1. So there
is a feature branch of arxiv-base modified to use pydantic v2 and work well
without flask. This will need to be merged to arxiv-base master soon.

### Current state
*WORKING*
- creates a submission
- uplaod and unpacks tar.gz
- license, policy and author attestation
- metadata: title abstract etc
- docker file
- tests

*NOT YET STARTED*
- no PDF compile
- no field validation other than pydantic
- no legacy "stage" integration
- no admin_log inserts
- no UI other than fastapi swagger
- no firing of pubsub events of changes

# 2024-09  NG assessment
Brian Caruso

The "NG" project in 2016 at arxiv started a replacement for the submit system. A
barrier to modernizing submit was the question if the NG systems could be
quickly put into production. A review of that code found it to have technical
problems. From that: "The NG system cannot be put into immediate use.  It has
flaws that demonstrate a misunderstanding with distributed software
development. It has restrictions on how it interoperates with the legacy
system. It also lacks a usable API to uniformly handle db and file CRUD."  See
https://docs.google.com/document/d/1zGmJWdCn5HIJLCTJqPTrxcuMRgcmMzhLNCz0M9r4Jng/edit?usp=sharing

I presented my assessment and proposed mostly starting from scratch and that was
accepted.  I hope to reuse isolated useful packages from NG.
