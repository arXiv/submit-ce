# coding: utf-8

# flake8: noqa

"""
    arXiv submit

    API to submit papers to arXiv.

    The version of the OpenAPI document: 0.1
    Generated by OpenAPI Generator (https://openapi-generator.tech)

    Do not edit the class manually.
"""  # noqa: E501


__version__ = "1.0.0"

# import apis into sdk package
from openapi_submit_client.api.post_submit_api import PostSubmitApi
from openapi_submit_client.api.service_api import ServiceApi
from openapi_submit_client.api.submit_api import SubmitApi

# import ApiClient
from openapi_submit_client.api_response import ApiResponse
from openapi_submit_client.api_client import ApiClient
from openapi_submit_client.configuration import Configuration
from openapi_submit_client.exceptions import OpenApiException
from openapi_submit_client.exceptions import ApiTypeError
from openapi_submit_client.exceptions import ApiValueError
from openapi_submit_client.exceptions import ApiKeyError
from openapi_submit_client.exceptions import ApiAttributeError
from openapi_submit_client.exceptions import ApiException

# import domain into sdk package
from openapi_submit_client.models.agreed_to_policy import AgreedToPolicy
from openapi_submit_client.models.authorship import Authorship
from openapi_submit_client.models.authorship_direct import AuthorshipDirect
from openapi_submit_client.models.authorship_proxy import AuthorshipProxy
from openapi_submit_client.models.category_change_result import CategoryChangeResult
from openapi_submit_client.models.http_validation_error import HTTPValidationError
from openapi_submit_client.models.set_categories import SetCategories
from openapi_submit_client.models.set_license import SetLicense
from openapi_submit_client.models.set_metadata import SetMetadata
from openapi_submit_client.models.started import Started
from openapi_submit_client.models.started_alter_exising import StartedAlterExising
from openapi_submit_client.models.started_new import StartedNew
from openapi_submit_client.models.validation_error import ValidationError
from openapi_submit_client.models.validation_error_loc_inner import ValidationErrorLocInner
