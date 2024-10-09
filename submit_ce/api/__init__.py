from typing import Annotated

from arxiv.taxonomy.definitions import CATEGORIES, CATEGORIES_ACTIVE
from pydantic import AfterValidator

def is_active_category(cat: str) -> bool:
    if cat not in CATEGORIES_ACTIVE:
        if cat not in CATEGORIES:
            raise ValueError("Invalid category specified")
        else:
            raise ValueError("No longer active category specified")

def is_category(cat: str) -> bool:
    if cat not in CATEGORIES:
        raise ValueError("Invalid category specified")

# BDC: I was thinking of doing a validator on the type but this conflincted with some
# test code that expected to get an InvalidEvent exception. It seems wrong to set this to raise
# that since it might be used outside of an Event
#ActiveCategory = Annotated[str, AfterValidator(is_active_category)]
ActiveCategory = str
"""Type for an active category."""

#Category = Annotated[str, AfterValidator(is_category)]
Category = str
"""Type for a category active or inactive."""