# AuthorshipDirect

Asserts the sender of this request is the author of the submitted items.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**i_am_author** | **bool** |  | 

## Example

```python
from openapi_client.models.authorship_direct import AuthorshipDirect

# TODO update the JSON string below
json = "{}"
# create an instance of AuthorshipDirect from a JSON string
authorship_direct_instance = AuthorshipDirect.from_json(json)
# print the JSON string representation of the object
print(AuthorshipDirect.to_json())

# convert the object into a dict
authorship_direct_dict = authorship_direct_instance.to_dict()
# create an instance of AuthorshipDirect from a dict
authorship_direct_from_dict = AuthorshipDirect.from_dict(authorship_direct_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


