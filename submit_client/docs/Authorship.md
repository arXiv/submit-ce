# Authorship


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**i_am_author** | **bool** |  | 
**i_am_authorized_to_proxy** | **bool** |  | 
**proxy** | **str** |  | 

## Example

```python
from openapi_client.models.authorship import Authorship

# TODO update the JSON string below
json = "{}"
# create an instance of Authorship from a JSON string
authorship_instance = Authorship.from_json(json)
# print the JSON string representation of the object
print(Authorship.to_json())

# convert the object into a dict
authorship_dict = authorship_instance.to_dict()
# create an instance of Authorship from a dict
authorship_from_dict = Authorship.from_dict(authorship_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


