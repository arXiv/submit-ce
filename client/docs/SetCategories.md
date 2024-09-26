# SetCategories


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**primary_category** | **str** |  | 
**secondary_categories** | **List[str]** |  | 

## Example

```python
from openapi_submit_client.models.set_categories import SetCategories

# TODO update the JSON string below
json = "{}"
# create an instance of SetCategories from a JSON string
set_categories_instance = SetCategories.from_json(json)
# print the JSON string representation of the object
print(SetCategories.to_json())

# convert the object into a dict
set_categories_dict = set_categories_instance.to_dict()
# create an instance of SetCategories from a dict
set_categories_from_dict = SetCategories.from_dict(set_categories_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


