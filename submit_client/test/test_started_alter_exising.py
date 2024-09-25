# coding: utf-8

"""
    arXiv submit

    API to submit papers to arXiv.

    The version of the OpenAPI document: 0.1
    Generated by OpenAPI Generator (https://openapi-generator.tech)

    Do not edit the class manually.
"""  # noqa: E501


import unittest

from openapi_client.models.started_alter_exising import StartedAlterExising

class TestStartedAlterExising(unittest.TestCase):
    """StartedAlterExising unit test stubs"""

    def setUp(self):
        pass

    def tearDown(self):
        pass

    def make_instance(self, include_optional) -> StartedAlterExising:
        """Test StartedAlterExising
            include_optional is a boolean, when False only required
            params are included, when True both required and
            optional params are included """
        # uncomment below to create an instance of `StartedAlterExising`
        """
        model = StartedAlterExising()
        if include_optional:
            return StartedAlterExising(
                submission_type = 'replacement',
                paperid = ''
            )
        else:
            return StartedAlterExising(
                submission_type = 'replacement',
                paperid = '',
        )
        """

    def testStartedAlterExising(self):
        """Test StartedAlterExising"""
        # inst_req_only = self.make_instance(include_optional=False)
        # inst_req_and_optional = self.make_instance(include_optional=True)

if __name__ == '__main__':
    unittest.main()
