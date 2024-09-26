# AuthorshipProxy

Asserts that the sender of this request is authorized to deposit the submitted items by the author of the items.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**i_am_authorized_to_proxy** | **bool** |  | 
**proxy** | **str** |  | 

## Example

```python
from openapi_submit_client.models.authorship_proxy import AuthorshipProxy

# TODO update the JSON string below
json = "{}"
# create an instance of AuthorshipProxy from a JSON string
authorship_proxy_instance = AuthorshipProxy.from_json(json)
# print the JSON string representation of the object
print(AuthorshipProxy.to_json())

# convert the object into a dict
authorship_proxy_dict = authorship_proxy_instance.to_dict()
# create an instance of AuthorshipProxy from a dict
authorship_proxy_from_dict = AuthorshipProxy.from_dict(authorship_proxy_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


