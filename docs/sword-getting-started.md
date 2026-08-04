# File: sword-getting-started

Quick developer onboarding.

First start the local ui and sword apps. See the main readme, for details like adding your username for the dev submit bucket prefix path.

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

Update user_id 0 for access to use sword:
```bash
sqlite3 legacy.db "
  update arXiv_demographics set 
         flag_xml=1, flag_proxy=1,
         flag_group_cs=1, flag_group_physics=1, flag_group_test=1
   where user_id=0"
```

Create a password:
```
uv run python << EOF
MYP = 'swordlocal'
from arxiv.auth.legacy.passwords import hash_password
print(f'hashed password: {hash_password(MYP)}')
  # ynKO5GAmBdLQQA+gs9RFiUeqG0MJMYPi
EOF
```

Add a password for user_id 0:
```bash
sqlite3 legacy.db "
  insert into tapir_users_password values(0,0,'ynKO5GAmBdLQQA+gs9RFiUeqG0MJMYPi') "
```

Manually create a session, to set the license in the ui app:
- http://localhost:8000/debug/login

Set a license:
- http://localhost:8000/sword-license

Check nextid:
```
gcloud storage cat gs://arxiv-submit-dev/brianm/sword-deposits/nextid
  # 3
```

Check sword api:
- http://localhost:8001/status

Get sword options for my account:
```
export USERPASS="wearing_1979:swordlocal"
curl -u $USERPASS http://localhost:8001/sword-app/servicedocument
   # it will list your categories, by collection.
```

Prepare a zip:
```
cd submit-ce/testdata/1/src
zip test-sword.zip main-test1.tex 00README.json
md5sum test-sword.zip | cut -d' ' -f1 | xxd -r -p | base64
  # f9SijKywEzQgHzp8K1axxA==
openssl dgst -md5 -binary test-sword.zip | base64
  # f9SijKywEzQgHzp8K1axxA==
```

Upload zip:
```
curl -su $USERPASS -H "Content-Type: application/zip" \
     -H "Content-MD5: f9SijKywEzQgHzp8K1axxA==" \
     --data-binary @test-sword.zip \
     http://localhost:8001/sword-app/test-collection > media.xml

     # 201 Created
```

Get the media link and sword id:
```
grep edit-media media.xml
  # <link rel="edit-media" 
  #       href="http://localhost:8001/sword-app/edit/26080006"/>
```

Check bucket, id is 26080006:
```
gcloud storage cat gs://arxiv-submit-dev/brianm/sword-deposits/2608/26080006.atom
  # Same as media.xml

gcloud storage cat gs://arxiv-submit-dev/brianm/sword-deposits/nextid
  # 7
```

Build the metadata wrapper. Title is unique in our db. Set primary category, author, and the media link-href:
```
date +"%Y-%m-%d %H:%M:%S"
  # 2026-08-04 14:43:04

cat << EOF > wrapper.xml 
<?xml version="1.0" encoding="utf-8"?>
<entry xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom/">
  <title>2026-08-04 14:43:04: A sword title</title>
  <id>arxiv:local::demo</id>
  <updated>2026-08-03T00:00:00Z</updated>
  <author><name>wearing_1979</name></author>
  <summary>A concise abstract, comfortably longer than twenty characters.</summary>
  <arxiv:primary_category scheme="http://arxiv.org/terms/arXiv/"
                          term="http://arxiv.org/terms/arXiv/test.dis-nn"/>
  <contributor><name>A. Developer</name><email>me@example.org</email></contributor>
  <link href="http://localhost:8001/sword-app/edit/26080003" type="application/zip" rel="related"/>
</entry>
EOF
```

Upload wrapper.xml:
```
curl -si -u $USERPASS \
     -H "Content-Type: application/atom+xml;type=entry" \
     --data-binary @wrapper.xml \
     http://localhost:8001/sword-app/test-collection > wrapper.out

   # 202 Accepted, and a submission now exists
```

Get the sword id:
```
export SWORDID=$(sed -n 's|.*info:arxiv/app/\([0-9]*\).*|\1|p' wrapper.out | head -1)
echo $SWORDID
```

Check status:
```
curl -s http://localhost:8001/resolve/app/$SWORDID
   # no auth needed here. status is 'incomplete' until compile runs.

# In prod, we see it is not auth-protected:
curl -s https://arxiv.org/resolve/app/26080048
   # ...
   # </autotex_log_b64><status>user deleted</status>
```

Re-read the stored entry:
```
curl -su $USERPASS http://localhost:8001/sword-app/getid/app/$SWORDID
curl -su $USERPASS http://localhost:8001/sword-app/edit/$SWORDID.atom
   # Both endpoints give the same document.
   # They are the same as wrapper.out (the output of uploading wrapper.xml)
```

View submissions:
```
sqlite3 legacy.db "
  select sword_id, paper_id from arXiv_tracking 
   order by sword_id desc limit 3"
   # 26080007|submit/27

sqlite3 legacy.db "
  select submission_id, status, proxy, submitter_email, title
    from arXiv_submissions order by submission_id desc limit 3"
   # 27|0|wearing_1979|me@example.org|2026-08-04 14:43:04: A sword title

```

Debugging:
```
grep -o '<arxiv:errorcode>[0-9]*' media.xml wrapper.out
grep -o '<summary>[^<]*' media.xml wrapper.out
```

Replacements of announced papers:
```
curl -su $USERPASS -X PUT -H "Content-Type: application/atom+xml;type=entry" \
     --data-binary @wrapper.xml http://localhost:8001/sword-app/edit/2607.00001
     
   # <summary>No access, not the owner...
```

