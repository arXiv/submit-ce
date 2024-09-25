# SetMetadata


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**title** | **str** |  | [optional] 
**authors** | **str** |  | [optional] 
**comments** | **str** |  | [optional] 
**abstract** | **str** |  | [optional] 
**report_num** | **int** |  | [optional] 
**msc_class** | **str** |  | [optional] 
**acm_class** | **str** |  | [optional] 
**journal_ref** | **str** |  | [optional] 
**doi** | **str** |  | [optional] 

## Example

```python
from openapi_client.models.set_metadata import SetMetadata

# TODO update the JSON string below
json = "{}"
# create an instance of SetMetadata from a JSON string
set_metadata_instance = SetMetadata.from_json(json)
# print the JSON string representation of the object
print(SetMetadata.to_json())

# convert the object into a dict
set_metadata_dict = set_metadata_instance.to_dict()
# create an instance of SetMetadata from a dict
set_metadata_from_dict = SetMetadata.from_dict(set_metadata_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


