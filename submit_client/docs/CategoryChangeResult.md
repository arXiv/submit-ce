# CategoryChangeResult


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**new_primary** | **str** |  | [optional] 
**old_primary** | **str** |  | [optional] 
**new_secondaries** | **List[str]** |  | [optional] 
**old_secondaries** | **List[str]** |  | [optional] 

## Example

```python
from openapi_client.models.category_change_result import CategoryChangeResult

# TODO update the JSON string below
json = "{}"
# create an instance of CategoryChangeResult from a JSON string
category_change_result_instance = CategoryChangeResult.from_json(json)
# print the JSON string representation of the object
print(CategoryChangeResult.to_json())

# convert the object into a dict
category_change_result_dict = category_change_result_instance.to_dict()
# create an instance of CategoryChangeResult from a dict
category_change_result_from_dict = CategoryChangeResult.from_dict(category_change_result_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


