# File: sword-getting-started

Quick developer onboarding.

## Setup

Start the local ui and sword apps. See the main readme, for details like how to add your username for the dev submit bucket prefix path.

Who can use sword:
```bash
sqlite3 legacy.db "
  select n.user_id, n.nickname, d.flag_xml, d.flag_proxy, d.veto_status,
         d.flag_group_cs, d.flag_group_physics, d.flag_group_test,
         l.license
    from arXiv_demographics d
    join tapir_nicknames n on n.user_id=d.user_id
    left join arXiv_sword_licenses l on l.user_id=d.user_id
   where d.flag_xml=1 and d.flag_proxy=1"
```

Update a submitter, user_id 1, with sword access.
```bash
sqlite3 legacy.db "
  update arXiv_demographics set 
         flag_xml=1, flag_proxy=1,
         flag_group_cs=1, flag_group_physics=1, flag_group_test=1
   where user_id=1"
```

Create a password for the submitter:
```python
uv run python << EOF
MYP = 'swordlocal'
from arxiv.auth.legacy.passwords import hash_password
print(f'hashed password: {hash_password(MYP)}')
# 9JnT7xiWDAOR+6wcLWjrsHJWQgMJrFMh
EOF
```

Store the password:
```bash
sqlite3 legacy.db "
  insert into tapir_users_password values(1,0,'9JnT7xiWDAOR+6wcLWjrsHJWQgMJrFMh') "
```

Check local submit ui:
```bash
curl http://localhost:8000/status
```

Login to submit-ce ui and set the submitter license:
- http://localhost:8000/debug/login
- http://localhost:8000/sword-license

Check the sword nextid:
```bash
gcloud storage cat gs://arxiv-submit-dev/brianm/sword-deposits/nextid
  # {"yymm": "2608", "seq": 13}
```

Check local sword api:
```bash
curl http://localhost:8001/status
```

Get sword options for the submitter account:
```bash
export USERPASS="indirect_1913:swordlocal"
curl -u $USERPASS http://localhost:8001/sword-app/servicedocument
   # it will list your categories, by collection.
```

## Upload the submission files

Create a zip, containing the tex and readme files.
```bash
cd submit-ce/testdata/1/src
zip test-sword.zip main-test1.tex 00README.json

# 2 ways to calculate the MD5:
export MYMD5=`openssl dgst -md5 -binary test-sword.zip | base64`
echo $MYMD5
  # fWzLkSkZc2VHZJEsxp94Rg==
md5sum test-sword.zip | cut -d' ' -f1 | xxd -r -p | base64
  # fWzLkSkZc2VHZJEsxp94Rg==
```

Upload the zip, saving the response:
```bash
curl -su $USERPASS -H "Content-Type: application/zip" \
     -H "Content-MD5: ${MYMD5}" \
     --data-binary @test-sword.zip \
     http://localhost:8001/sword-app/test-collection > response-media.xml

     # 201 Created
```

The response contains the media link with sword id:
```bash
grep edit-media response-media.xml
  # <link rel="edit-media" 
  #       href="http://localhost:8001/sword-app/edit/26080013"/>
```

The response is also saved in the bucket, using sword id as filename:
```bash
gcloud storage cat gs://arxiv-submit-dev/brianm/sword-deposits/2609/26090001.atom | grep edit-media
  # Same as the local response-media.xml
```

So far your sword submission is 2 files: an uploaded zip, and the api atom response:
```bash
gcloud storage ls gs://arxiv-submit-dev/brianm/sword-deposits/2609
  # gs://arxiv-submit-dev/brianm/sword-deposits/2609/26090001.atom
  # gs://arxiv-submit-dev/brianm/sword-deposits/2609/26090001.zip
```

You upload was assigned the next sword id, then it was incremented:
```bash
gcloud storage cat gs://arxiv-submit-dev/brianm/sword-deposits/nextid
  # {"yymm": "2609", "seq": 2}
```

The submission tables in the local db have not changed:
```bash
sqlite3 ../../../legacy.db "
  select sword_id, paper_id from arXiv_tracking 
   order by sword_id desc limit 3"

sqlite3 ../../../legacy.db "
  select submission_id, status, proxy, submitter_email, title
    from arXiv_submissions order by submission_id desc limit 3"
```


## Upload the metadata 

Set the title, primary category, author, and the media link-href.
Title is unique in our db, so include a date.
```bash
cd submit-ce/testdata/1/src

export MYDATE=`date +"%Y-%m-%d %H:%M:%S"`
export SWORDMEDIA=`grep edit-media response-media.xml | egrep -o '((\d+))"/>$' | sed 's/"\/>//'`
echo $MYDATE $SWORDMEDIA

cat << EOF > metadata.xml 
<?xml version="1.0" encoding="utf-8"?>
<entry xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom/">
  <title>${MYDATE}: A sword title</title>
  <id>arxiv:local::demo</id>
  <updated>2026-08-03T00:00:00Z</updated>
  <author><name>wearing_1979</name></author>
  <summary>A concise abstract, comfortably longer than twenty characters.</summary>
  <arxiv:primary_category scheme="http://arxiv.org/terms/arXiv/"
                          term="http://arxiv.org/terms/arXiv/test.dis-nn"/>
  <contributor><name>A. Developer</name><email>me@example.org</email></contributor>
  <link href="http://localhost:8001/sword-app/edit/${SWORDMEDIA}" type="application/zip" rel="related"/>
</entry>
EOF
```

Upload metadata.xml:
```bash
curl -si -u $USERPASS \
     -H "Content-Type: application/atom+xml;type=entry" \
     --data-binary @metadata.xml \
     http://localhost:8001/sword-app/test-collection > response-metadata.out

   # 202 Accepted
```

Get the sword id:
```bash
export SWORDMETADATA=$(sed -n 's|.*info:arxiv/app/\([0-9]*\).*|\1|p' response-metadata.out | head -1)
echo $SWORDMETADATA
```

Check status:
```bash
curl -s http://localhost:8001/resolve/app/$SWORDMETADATA
   # This is public, no auth needed.
   # Status is 'incomplete' until compile runs.

# Verify no-auth is in prod now:
curl -s https://arxiv.org/resolve/app/26080048
   # ...
   # </autotex_log_b64><status>user deleted</status>

# Can't check status by media sword ids:
curl -s http://localhost:8001/resolve/app/$SWORDMEDIA
  <error>identifier does not correspond to a SWORD wrapper, it may belong to a media deposit</error>
```

Utility to read the stored metadata entry:
```bash
# Both endpoints return the same response as the metadata.xml upload:
curl -su $USERPASS http://localhost:8001/sword-app/getid/app/$SWORDMETADATA
curl -su $USERPASS http://localhost:8001/sword-app/edit/$SWORDMETADATA.atom
```

So far, your sword submission is 3 files and 2 database rows:
```bash
gcloud storage ls gs://arxiv-submit-dev/brianm/sword-deposits/2609
  # gs://arxiv-submit-dev/brianm/sword-deposits/2609/26090001.atom
  # gs://arxiv-submit-dev/brianm/sword-deposits/2609/26090001.zip
  # gs://arxiv-submit-dev/brianm/sword-deposits/2609/26090002.atom

sqlite3 ../../../legacy.db "
  select sword_id, paper_id from arXiv_tracking 
   order by sword_id desc limit 3"
   # 26090002|submit/1

sqlite3 ../../../legacy.db "
  select submission_id, status, proxy, submitter_email, title
    from arXiv_submissions order by submission_id desc limit 3"
   # 1|0|indirect_1913|me@example.org|2026-09-09 13:00:47: A sword title
```

If there are issues, this may help with debugging:
```bash
grep -o '<arxiv:errorcode>[0-9]*' metadata.xml response-metadata.out
grep -o '<summary>[^<]*' metadata.xml response-metadata.out
```

## Compiling a deposit

So far:
- A media zip and metadata xml have been uploaded.
- A submission row has been created with status 0/working.

But there are no submission files:
```bash
gcloud storage ls -l -R gs://arxiv-submit-dev/brianm/1/
```

Open an additional terminal, and run one compile, which will make three calls to tex2pdf:
```bash
uv run python local_sword_worker.py --once --limit 1
  # GET https://tex2pdf-api-default-874717964009.us-central1.run.app "HTTP/1.1 403 Forbidden"
  # built tarball for submission 1 (files_added=2,
  # wrote brianm/1/1.tar.gz
  # /preflight?source=
  # /directives?source=
  # /convert?source=
  # submit_ce.sword.worker_loop: submission 1: 
  #   preflight, source_format=tex, directives, preview, source_processed, finalized
```

The submission should be compiled:
```
gcloud storage ls -l -R gs://arxiv-submit-dev/brianm/1/
gs://arxiv-submit-dev/brianm/1/:
     86315  2026-09-09T17:40:48Z  gs://arxiv-submit-dev/brianm/1/1.pdf
      1008  2026-09-09T17:40:42Z  gs://arxiv-submit-dev/brianm/1/directives.json
     18294  2026-09-09T17:40:48Z  gs://arxiv-submit-dev/brianm/1/gcp_compile.log
       351  2026-09-09T17:40:40Z  gs://arxiv-submit-dev/brianm/1/gcp_preflight.json
     96955  2026-09-09T17:40:47Z  gs://arxiv-submit-dev/brianm/1/outcome.tgz
       109  2026-09-09T17:40:41Z  gs://arxiv-submit-dev/brianm/1/user_decisions.json

gs://arxiv-submit-dev/brianm/1/src/:
       348  2026-09-09T17:40:43Z  gs://arxiv-submit-dev/brianm/1/src/00README.json
      1492  2026-09-09T17:04:47Z  gs://arxiv-submit-dev/brianm/1/src/main-test1.tex
```

The zzrm was rewritten. 
```bash
jq . 00README.json
gcloud storage cat gs://arxiv-submit-dev/brianm/1/src/00README.json | jq
```

TODO: 1. check that it converts. 2. check that .xxx works.

Status moves from incomplete -> submitted, and status 0 -> 1:
```bash
curl -s http://localhost:8001/resolve/app/$SWORDMETADATA | grep status
  # <status>submitted</status>

sqlite3 ../../../legacy.db "
  select submission_id, status, proxy, submitter_email, title
    from arXiv_submissions order by submission_id desc limit 3"
  # 1|1|indirect_1913|me@example.org|2026-09-09 13:00:47: A sword title
```

In CE, submit events are logged
```
sqlite3 ../../../legacy.db "select submission_id,event_type,created from submit_ce_event where submission_id=1"
1|CreateSubmission|2026-09-09 17:04:46.083516
1|SetProxyInformation|2026-09-09 17:04:46.117203
1|ConfirmPolicy|2026-09-09 17:04:46.122109
1|SetLicense|2026-09-09 17:04:46.123684
1|SetTitle|2026-09-09 17:04:46.124505
1|SetAbstract|2026-09-09 17:04:46.133862
1|SetAuthors|2026-09-09 17:04:46.182840
1|SetPrimaryClassification|2026-09-09 17:04:46.184174
1|UploadArchive|2026-09-09 17:04:46.185361
1|StartPreflight|2026-09-09 17:40:28.348036
1|SetSourceFormat|2026-09-09 17:40:40.480898
1|SetDirectivesAndCleanup|2026-09-09 17:40:40.959077
1|StartDirectives|2026-09-09 17:40:42.396440
1|StoreZzrm|2026-09-09 17:40:43.220307
1|StartCompileSource|2026-09-09 17:40:44.033760
1|ConfirmSourceProcessed|2026-09-09 17:40:48.851821
1|FinalizeSubmission|2026-09-09 17:40:48.861362
1|EmailSubmitterFinalizeMsg|2026-09-09 17:40:48.865629
1|EmailModeratorsFinalizeMsg|2026-09-09 17:40:48.866748
```


## Replacements

Announce a submission:
```bash
sqlite3 ../../../legacy.db "
insert into arXiv_documents (paper_id, title, submitter_email, submitter_id, dated)
values ('2609.00001', 'A sword title', 'me@example.org', 0, strftime('%s','now'));

# todo: see whether needs metadata row.

update arXiv_submissions
   set status=7, doc_paper_id='2609.00001',
       document_id=(select document_id FROM arXiv_documents where paper_id='2609.00001')
 where submission_id=1;

insert into arXiv_paper_owners(document_id, user_id, date, added_by, remote_addr, valid, flag_author, flag_auto)
values ((select document_id from arXiv_documents where paper_id='2609.00001'),
       0, strftime('%s','now'), 0, '127.0.0.1', 1, 1, 0);

# announcement date history, and used in edit url:
update arXiv_tracking set paper_id='2609.00001' where sword_id=26090002;
"

sqlite3 ../../../legacy.db "
  select document_id, submission_id, status, sword_id, doc_paper_id
    from arXiv_submissions order by submission_id desc limit 3;
  select document_id, paper_id, submitter_id, title
    from arXiv_documents order by document_id desc limit 3;
  select document_id, user_id
    from arXiv_paper_owners order by document_id desc limit 3;
  select * from arXiv_tracking where sword_id=26090002;
"
```

