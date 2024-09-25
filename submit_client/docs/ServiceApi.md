# openapi_client.ServiceApi

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**get_service_status_v1_status_get**](ServiceApi.md#get_service_status_v1_status_get) | **GET** /v1/status | Get Service Status


# **get_service_status_v1_status_get**
> str get_service_status_v1_status_get()

Get Service Status

Get information about the current status of file management service.

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
    api_instance = openapi_client.ServiceApi(api_client)

    try:
        # Get Service Status
        api_response = api_instance.get_service_status_v1_status_get()
        print("The response of ServiceApi->get_service_status_v1_status_get:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ServiceApi->get_service_status_v1_status_get: %s\n" % e)
```



### Parameters

This endpoint does not need any parameter.

### Return type

**str**

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | system is working correctly |  -  |
**500** | system is not working correctly |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

