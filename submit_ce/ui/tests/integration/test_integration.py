"""Tests of all steps in the submission UI happy path.

This differs from the test_workflow in that this tests the submission system as
an integrated whole from the outside via HTTP requests. This contacts a
submission system at a URL via HTTP. test_workflow.py creates the flask app and
interacts with that.

WARNING: This test is written in a very stateful manner. So the tests must be
run in order.
"""

import os
import pytest
import unittest
from pathlib import Path
import time

from requests_toolbelt.multipart.encoder import MultipartEncoder

from http import HTTPStatus as status
from submit_ce.ui.conftest import mocked_compile_service
from submit_ce.ui.tests.csrf_util import parse_csrf_token


@pytest.fixture
def client(request, app, authorized_client):
    mocked_compile_service(app)
    request.cls.client = authorized_client
    yield authorized_client


@pytest.mark.usefixtures("client")
class TestSubmissionIntegration(unittest.TestCase):
    """Tests submission system."""
    @classmethod
    def setUp(cls):
        cls.url = '/'
        
        cls.page_test_names = [
            "home_page",
            "create_submission",
            "verify_user_page",
            "policy_page",
            "license_page",
            "classification_page",
            "upload_page",
            "review_files",
            "process_page",
            "metadata_page",
            #"optional_metadata_page",
            "final_preview_page",
            "confirmation"
        ]

        cls.next_page = None
        cls.process_page_timeout = 10 # sec


    def check_response(self, res):
        self.assertEqual(res.status_code, status.SEE_OTHER, f"Should get SEE_OTHER but was {res.status_code}")
        self.assertIn('Location', res.headers)
        self.next_page = res.headers['Location']

    def home_page(self):
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers['content-type'],
                         'text/html; charset=utf-8')
        self.csrf = parse_csrf_token(res)
        self.assertIn('Welcome', res.text)

    def create_submission(self):
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, 200)
        self.assertIn('Welcome', res.text)

        res = self.client.post(self.url + "/",
                            data={'new': 'new', 'csrf_token': parse_csrf_token(res)})
        self.assertTrue(status.SEE_OTHER, f"Should get SEE_OTHER but was {res.status_code}")
        
        self.check_response(res)

    def verify_user_page(self):
        self.assertIn('verify_user', self.next_page,
                      "next page should be to verify_user")

        res = self.client.get(self.next_page)
        self.assertEqual(res.status_code, 200)
        self.assertIn('I confirm that my contact information is correct', res.text)

        # here we're reusing next_page, that's not great maybe find it in the html
        res = self.client.post(self.next_page, data={'verify_user': 'true',
                                                  'action': 'next',
                                                  'csrf_token': parse_csrf_token(res)})
        self.check_response(res)

    def policy_page(self):
        self.assertIn('policy', self.next_page, "URL should be to policy")
        res = self.client.get(self.next_page)
        self.assertEqual(res.status_code, 200)
        self.assertIn('Read and accept the Submission Agreement before proceeding', res.text)
        res = self.client.post(self.next_page,
                            data={'policy': 'y',
                                  'action': 'next',
                                  'policy_id': 3,
                                  'csrf_token': parse_csrf_token(res)})
        self.check_response(res)

    def license_page(self):
        self.assertIn('license', self.next_page, "next page should be to license")
        res = self.client.get(self.next_page)
        self.assertEqual(res.status_code, 200)
        self.assertIn('Select a License', res.text)
        res = self.client.post(self.next_page,
                            data={'license': 'http://arxiv.org/licenses/nonexclusive-distrib/1.0/',
                                  'action': 'next',
                                  'csrf_token': parse_csrf_token(res)})
        self.check_response(res)

    def classification_page(self):
        self.assertIn('classification', self.next_page, "URL should be to classification")
        res = self.client.get(self.next_page)
        self.assertEqual(res.status_code, 200)
        self.assertIn('Suggest Category', res.text)
        res = self.client.post(self.next_page,
                            data={'primary': 'astro-ph.GA',
                                  'action': 'next',
                                  'csrf_token': parse_csrf_token(res)})
        self.check_response(res)

        
    def upload_page(self):
        self.assertIn('upload', self.next_page, "URL should be to upload files")
        res = self.client.get(self.next_page)
        self.assertEqual(res.status_code, 200)
        self.assertIn('Upload Files', res.text)

        upload_path = Path(os.path.abspath(__file__)).parent / 'upload2.tar.gz'
        with open(upload_path, 'rb') as upload_file:
            multipart = MultipartEncoder(fields={
                'file': ('upload2.tar.gz', upload_file, 'application/gzip'),
                'csrf_token' : parse_csrf_token(res),
            })

            res = self.client.post(self.next_page,
                                    data=multipart,
                                    headers={'Content-Type': multipart.content_type})

        self.assertEqual(res.status_code, 200)
        self.assertIn('Upload successful', res.text, "upload should succeed")

        res = self.client.post(self.next_page, # should still be file upload page
                            data={'action':'next', 'csrf_token': parse_csrf_token(res)})
        self.check_response(res)

    def review_files(self):
        # TODO test more review_files when it is written
        self.assertIn('review_files', self.next_page)
        res = self.client.get(self.next_page)
        self.assertEqual(res.status_code, 200)
        self.assertIn('Review Files', res.text)
        res = self.client.post(self.next_page,
                               data={'action':'next', 'csrf_token': parse_csrf_token(res)})
        self.check_response(res)

    def process_page(self):
        self.assertIn('process', self.next_page, "URL should be to process step")
        res = self.client.get(self.next_page)
        self.assertEqual(res.status_code, 200)
        self.assertIn('Process Files', res.text)

        #request TeX processing
        res = self.client.post(self.next_page, data={'csrf_token': parse_csrf_token(res)})
        self.assertEqual(res.status_code, 200)

        #wait for TeX processing
        success, start = False, time.time()
        while not success and not time.time() > start + self.process_page_timeout:
            res = self.client.get(self.next_page)
            success = 'processing successful' in res.text.lower()
            if success or time.time() - start > self.process_page_timeout:
                break
            time.sleep(1)

        self.assertTrue(success,
                        'Failed to process and get tex compiler summary after'
                        f'aprox {self.process_page_timeout} sec.')

        res = self.client.post(self.next_page, # should still be process page
                            data={'action':'next', 'csrf_token': parse_csrf_token(res)})
        self.check_response(res)
        
    def metadata_page(self):
        self.assertIn('metadata', self.next_page, 'URL should be for metadata page')
        self.assertNotIn('optional', self.next_page,'URL should NOT be for optional metadata')

        res = self.client.get(self.next_page)
        self.assertEqual(res.status_code, 200)
        self.assertIn('Edit Metadata', res.text)

        res = self.client.post(self.next_page,
                            data= {
                                'csrf_token': parse_csrf_token(res),
                                'title': 'Test title',
                                'authors_display': 'Some authors or other',
                                'abstract': 'THis is the abstract and we know that it needs to be at least some number of characters.',
                                'comments': 'comments are optional.',
                                'action': 'next',
                            })
        self.check_response(res)
                            

    # def optional_metadata_page(self):
    #     self.assertIn('optional', self.next_page, 'URL should be for metadata page')

    #     res = self.client.get(self.next_page)
    #     self.assertEqual(res.status_code, 200)
    #     self.assertIn('Optional Metadata', res.text)

    #     res = self.client.post(self.next_page,
    #                         data = {
    #                             'csrf_token': parse_csrf_token(res),
    #                             'doi': '10.1016/S0550-3213(01)00405-9',
    #                             'journal_ref': 'Nucl.Phys.Proc.Suppl. 109 (2002) 3-9',
    #                             'report_num': 'SU-4240-720; LAUR-01-2140',
    #                             'acm_class': 'f.2.2',
    #                             'msc_class': '14j650',
    #                             'action': 'next'})
    #     self.check_response(res)


    def final_preview_page(self):
        self.assertIn('final_preview', self.next_page, 'URL should be for final preview page')

        res = self.client.get(self.next_page)
        self.assertEqual(res.status_code, 200)
        self.assertIn('Confirm and Submit', res.text)

        res = self.client.post(self.next_page,
                            data= {
                                'csrf_token': parse_csrf_token(res),
                                'proceed': 'y',
                                'action': 'next',
                            })
        self.check_response(res)

        
    def confirmation(self):
        self.assertIn('confirm', self.next_page, 'URL should be for confirmation page')

        res = self.client.get(self.next_page)
        self.assertEqual(res.status_code, 200)
        self.assertIn('success', res.text)


    @pytest.mark.skip(reason="process_page mock compilation not working with NullFileStore")
    def test_submission_system_basic(self):
        """Create, upload files, process TeX and submit_ce a submission."""
        for page_test in [getattr(self, methname) for methname in self.page_test_names]:
            page_test()


if __name__ == '__main__':
    unittest.main()
