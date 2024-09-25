# openapi_client.SubmitApi

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**accept_policy_post_v1_submission_submission_id_accept_policy_post**](SubmitApi.md#accept_policy_post_v1_submission_submission_id_accept_policy_post) | **POST** /v1/submission/{submission_id}/acceptPolicy | Accept Policy Post
[**assert_authorship_post_v1_submission_submission_id_assert_authorship_post**](SubmitApi.md#assert_authorship_post_v1_submission_submission_id_assert_authorship_post) | **POST** /v1/submission/{submission_id}/assertAuthorship | Assert Authorship Post
[**file_post_v1_submission_submission_id_files_post**](SubmitApi.md#file_post_v1_submission_submission_id_files_post) | **POST** /v1/submission/{submission_id}/files | File Post
[**get_submission_v1_submission_submission_id_get**](SubmitApi.md#get_submission_v1_submission_submission_id_get) | **GET** /v1/submission/{submission_id} | Get Submission
[**set_categories_post_v1_submission_submission_id_set_categories_post**](SubmitApi.md#set_categories_post_v1_submission_submission_id_set_categories_post) | **POST** /v1/submission/{submission_id}/setCategories | Set Categories Post
[**set_license_post_v1_submission_submission_id_set_license_post**](SubmitApi.md#set_license_post_v1_submission_submission_id_set_license_post) | **POST** /v1/submission/{submission_id}/setLicense | Set License Post
[**set_metadata_post_v1_submission_submission_id_set_metadata_post**](SubmitApi.md#set_metadata_post_v1_submission_submission_id_set_metadata_post) | **POST** /v1/submission/{submission_id}/setMetadata | Set Metadata Post
[**start_v1_start_post**](SubmitApi.md#start_v1_start_post) | **POST** /v1/start | Start


# **accept_policy_post_v1_submission_submission_id_accept_policy_post**
> object accept_policy_post_v1_submission_submission_id_accept_policy_post(submission_id, agreed_to_policy=agreed_to_policy)

Accept Policy Post

Agree to an arXiv policy to initiate a new item submission or  a change to an existing item.

### Example


```python
import openapi_client
from openapi_client.models.agreed_to_policy import AgreedToPolicy
from openapi_client.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = openapi_client.Configuration(
    host = "http://localhost"
)


# Enter a context with an instance of the API client
with openapi_client.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = openapi_client.SubmitApi(api_client)
    submission_id = 'submission_id_example' # str | Id of the submission to get.
    agreed_to_policy = openapi_client.AgreedToPolicy() # AgreedToPolicy |  (optional)

    try:
        # Accept Policy Post
        api_response = api_instance.accept_policy_post_v1_submission_submission_id_accept_policy_post(submission_id, agreed_to_policy=agreed_to_policy)
        print("The response of SubmitApi->accept_policy_post_v1_submission_submission_id_accept_policy_post:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling SubmitApi->accept_policy_post_v1_submission_submission_id_accept_policy_post: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **submission_id** | **str**| Id of the submission to get. | 
 **agreed_to_policy** | [**AgreedToPolicy**](AgreedToPolicy.md)|  | [optional] 

### Return type

**object**

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | The has been accepted. |  -  |
**400** | There was an problem when processing the agreement. It was not accepted. |  -  |
**401** | Unauthorized. Missing valid authentication information. The agreement was not accepted. |  -  |
**403** | Forbidden. User or client is not authorized to upload. The agreement was not accepted. |  -  |
**500** | Error. There was a problem. The agreement was not accepted. |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **assert_authorship_post_v1_submission_submission_id_assert_authorship_post**
> str assert_authorship_post_v1_submission_submission_id_assert_authorship_post(submission_id, authorship=authorship)

Assert Authorship Post

### Example


```python
import openapi_client
from openapi_client.models.authorship import Authorship
from openapi_client.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = openapi_client.Configuration(
    host = "http://localhost"
)


# Enter a context with an instance of the API client
with openapi_client.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = openapi_client.SubmitApi(api_client)
    submission_id = 'submission_id_example' # str | Id of the submission to assert authorship for.
    authorship = openapi_client.Authorship() # Authorship |  (optional)

    try:
        # Assert Authorship Post
        api_response = api_instance.assert_authorship_post_v1_submission_submission_id_assert_authorship_post(submission_id, authorship=authorship)
        print("The response of SubmitApi->assert_authorship_post_v1_submission_submission_id_assert_authorship_post:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling SubmitApi->assert_authorship_post_v1_submission_submission_id_assert_authorship_post: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **submission_id** | **str**| Id of the submission to assert authorship for. | 
 **authorship** | [**Authorship**](Authorship.md)|  | [optional] 

### Return type

**str**

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **file_post_v1_submission_submission_id_files_post**
> str file_post_v1_submission_submission_id_files_post(submission_id, upload_file)

File Post

Upload a file to a submission.  The file can be a single file, a zip, or a tar.gz. Zip and tar.gz files will be unpacked.

### Example


```python
import openapi_client
from openapi_client.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = openapi_client.Configuration(
    host = "http://localhost"
)


# Enter a context with an instance of the API client
with openapi_client.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = openapi_client.SubmitApi(api_client)
    submission_id = 'submission_id_example' # str | Id of the submission to add the upload to.
    upload_file = None # bytearray | 

    try:
        # File Post
        api_response = api_instance.file_post_v1_submission_submission_id_files_post(submission_id, upload_file)
        print("The response of SubmitApi->file_post_v1_submission_submission_id_files_post:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling SubmitApi->file_post_v1_submission_submission_id_files_post: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **submission_id** | **str**| Id of the submission to add the upload to. | 
 **upload_file** | **bytearray**|  | 

### Return type

**str**

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: multipart/form-data
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **get_submission_v1_submission_submission_id_get**
> object get_submission_v1_submission_submission_id_get(submission_id)

Get Submission

Get information about a submission.

### Example


```python
import openapi_client
from openapi_client.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = openapi_client.Configuration(
    host = "http://localhost"
)


# Enter a context with an instance of the API client
with openapi_client.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = openapi_client.SubmitApi(api_client)
    submission_id = 'submission_id_example' # str | Id of the submission to get.

    try:
        # Get Submission
        api_response = api_instance.get_submission_v1_submission_submission_id_get(submission_id)
        print("The response of SubmitApi->get_submission_v1_submission_submission_id_get:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling SubmitApi->get_submission_v1_submission_submission_id_get: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **submission_id** | **str**| Id of the submission to get. | 

### Return type

**object**

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | The submission data. |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **set_categories_post_v1_submission_submission_id_set_categories_post**
> CategoryChangeResult set_categories_post_v1_submission_submission_id_set_categories_post(submission_id, set_categories)

Set Categories Post

Set the categories for a submission.  The categories will replace any categories already set on the submission.

### Example


```python
import openapi_client
from openapi_client.models.category_change_result import CategoryChangeResult
from openapi_client.models.set_categories import SetCategories
from openapi_client.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = openapi_client.Configuration(
    host = "http://localhost"
)


# Enter a context with an instance of the API client
with openapi_client.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = openapi_client.SubmitApi(api_client)
    submission_id = 'submission_id_example' # str | Id of the submission to set the categories for.
    set_categories = openapi_client.SetCategories() # SetCategories | 

    try:
        # Set Categories Post
        api_response = api_instance.set_categories_post_v1_submission_submission_id_set_categories_post(submission_id, set_categories)
        print("The response of SubmitApi->set_categories_post_v1_submission_submission_id_set_categories_post:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling SubmitApi->set_categories_post_v1_submission_submission_id_set_categories_post: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **submission_id** | **str**| Id of the submission to set the categories for. | 
 **set_categories** | [**SetCategories**](SetCategories.md)|  | 

### Return type

[**CategoryChangeResult**](CategoryChangeResult.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **set_license_post_v1_submission_submission_id_set_license_post**
> object set_license_post_v1_submission_submission_id_set_license_post(submission_id, set_license=set_license)

Set License Post

Set a license for a files of a submission.

### Example


```python
import openapi_client
from openapi_client.models.set_license import SetLicense
from openapi_client.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = openapi_client.Configuration(
    host = "http://localhost"
)


# Enter a context with an instance of the API client
with openapi_client.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = openapi_client.SubmitApi(api_client)
    submission_id = 'submission_id_example' # str | Id of the submission to set the license for.
    set_license = openapi_client.SetLicense() # SetLicense |  (optional)

    try:
        # Set License Post
        api_response = api_instance.set_license_post_v1_submission_submission_id_set_license_post(submission_id, set_license=set_license)
        print("The response of SubmitApi->set_license_post_v1_submission_submission_id_set_license_post:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling SubmitApi->set_license_post_v1_submission_submission_id_set_license_post: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **submission_id** | **str**| Id of the submission to set the license for. | 
 **set_license** | [**SetLicense**](SetLicense.md)|  | [optional] 

### Return type

**object**

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **set_metadata_post_v1_submission_submission_id_set_metadata_post**
> str set_metadata_post_v1_submission_submission_id_set_metadata_post(submission_id, set_metadata)

Set Metadata Post

### Example


```python
import openapi_client
from openapi_client.models.set_metadata import SetMetadata
from openapi_client.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = openapi_client.Configuration(
    host = "http://localhost"
)


# Enter a context with an instance of the API client
with openapi_client.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = openapi_client.SubmitApi(api_client)
    submission_id = 'submission_id_example' # str | Id of the submission to set the metadata for.
    set_metadata = openapi_client.SetMetadata() # SetMetadata | 

    try:
        # Set Metadata Post
        api_response = api_instance.set_metadata_post_v1_submission_submission_id_set_metadata_post(submission_id, set_metadata)
        print("The response of SubmitApi->set_metadata_post_v1_submission_submission_id_set_metadata_post:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling SubmitApi->set_metadata_post_v1_submission_submission_id_set_metadata_post: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **submission_id** | **str**| Id of the submission to set the metadata for. | 
 **set_metadata** | [**SetMetadata**](SetMetadata.md)|  | 

### Return type

**str**

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **start_v1_start_post**
> str start_v1_start_post(started)

Start

Start a submission and get a submission ID.  TODO Maybe the start needs to include accepting an agreement?  TODO How to better indicate that the body is a string that is the submission id? Links?

### Example


```python
import openapi_client
from openapi_client.models.started import Started
from openapi_client.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = openapi_client.Configuration(
    host = "http://localhost"
)


# Enter a context with an instance of the API client
with openapi_client.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = openapi_client.SubmitApi(api_client)
    started = openapi_client.Started() # Started | 

    try:
        # Start
        api_response = api_instance.start_v1_start_post(started)
        print("The response of SubmitApi->start_v1_start_post:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling SubmitApi->start_v1_start_post: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **started** | [**Started**](Started.md)|  | 

### Return type

**str**

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: text/plain, application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successfully started a submission. |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

