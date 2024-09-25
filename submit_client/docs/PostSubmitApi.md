# openapi_client.PostSubmitApi

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**mark_deposited_post_v1_submission_submission_id_mark_deposited_post**](PostSubmitApi.md#mark_deposited_post_v1_submission_submission_id_mark_deposited_post) | **POST** /v1/submission/{submission_id}/markDeposited | Mark Deposited Post
[**mark_processing_for_deposit_post_v1_submission_submission_id_mark_processing_for_deposit_post**](PostSubmitApi.md#mark_processing_for_deposit_post_v1_submission_submission_id_mark_processing_for_deposit_post) | **POST** /v1/submission/{submission_id}/markProcessingForDeposit |  Mark Processing For Deposit Post
[**unmark_processing_for_deposit_post_v1_submission_submission_id_unmark_processing_for_deposit_post**](PostSubmitApi.md#unmark_processing_for_deposit_post_v1_submission_submission_id_unmark_processing_for_deposit_post) | **POST** /v1/submission/{submission_id}/unmarkProcessingForDeposit | Unmark Processing For Deposit Post


# **mark_deposited_post_v1_submission_submission_id_mark_deposited_post**
> object mark_deposited_post_v1_submission_submission_id_mark_deposited_post(submission_id)

Mark Deposited Post

Mark that the submission has been successfully deposited into the arxiv corpus.

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
    api_instance = openapi_client.PostSubmitApi(api_client)
    submission_id = 'submission_id_example' # str | Id of the submission to get.

    try:
        # Mark Deposited Post
        api_response = api_instance.mark_deposited_post_v1_submission_submission_id_mark_deposited_post(submission_id)
        print("The response of PostSubmitApi->mark_deposited_post_v1_submission_submission_id_mark_deposited_post:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling PostSubmitApi->mark_deposited_post_v1_submission_submission_id_mark_deposited_post: %s\n" % e)
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
**200** | Deposited has been recorded. |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **mark_processing_for_deposit_post_v1_submission_submission_id_mark_processing_for_deposit_post**
> object mark_processing_for_deposit_post_v1_submission_submission_id_mark_processing_for_deposit_post(submission_id)

 Mark Processing For Deposit Post

Mark that the submission is being processed for deposit.

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
    api_instance = openapi_client.PostSubmitApi(api_client)
    submission_id = 'submission_id_example' # str | Id of the submission to get.

    try:
        #  Mark Processing For Deposit Post
        api_response = api_instance.mark_processing_for_deposit_post_v1_submission_submission_id_mark_processing_for_deposit_post(submission_id)
        print("The response of PostSubmitApi->mark_processing_for_deposit_post_v1_submission_submission_id_mark_processing_for_deposit_post:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling PostSubmitApi->mark_processing_for_deposit_post_v1_submission_submission_id_mark_processing_for_deposit_post: %s\n" % e)
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
**200** | The submission has been marked as in processing for deposit. |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **unmark_processing_for_deposit_post_v1_submission_submission_id_unmark_processing_for_deposit_post**
> object unmark_processing_for_deposit_post_v1_submission_submission_id_unmark_processing_for_deposit_post(submission_id)

Unmark Processing For Deposit Post

Indicate that an external system in no longer working on depositing this submission.  This just indicates that the submission is no longer in processing state. This does not indicate that it  was successfully deposited.

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
    api_instance = openapi_client.PostSubmitApi(api_client)
    submission_id = 'submission_id_example' # str | Id of the submission to get.

    try:
        # Unmark Processing For Deposit Post
        api_response = api_instance.unmark_processing_for_deposit_post_v1_submission_submission_id_unmark_processing_for_deposit_post(submission_id)
        print("The response of PostSubmitApi->unmark_processing_for_deposit_post_v1_submission_submission_id_unmark_processing_for_deposit_post:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling PostSubmitApi->unmark_processing_for_deposit_post_v1_submission_submission_id_unmark_processing_for_deposit_post: %s\n" % e)
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
**200** | The submission has been marked as no longer in processing for deposit. |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

