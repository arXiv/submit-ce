"""Test that all event classes are well-formed."""
import inspect

from polyfactory.factories.pydantic_factory import ModelFactory

# from hypothesis import given, settings
# from hypothesis_jsonschema import from_schema
from pydantic import PydanticInvalidForJsonSchema

from ..base import Event


def test_has_name():
    """All event classes must have a ``NAME`` attribute."""
    for klass in Event.__subclasses__():
        assert hasattr(klass, 'NAME')


def test_has_named():
    """All event classes must have a ``NAMED`` attribute."""
    for klass in Event.__subclasses__():
        assert hasattr(klass, 'NAMED')


def test_has_projection():
    """Each event class must have an instance method ``project()``."""
    for klass in Event.__subclasses__():
        assert hasattr(klass, 'project') and inspect.isfunction(klass.project)


def test_has_validate():
    """Each event class must have an instance method ``validate()``."""
    for klass in Event.__subclasses__():
        hasattr(klass, 'validate') and inspect.isfunction(klass.validate)

def test_round_trip():
    """Verify that all event classes can be converted to JSON and back."""
    for klass in Event.__subclasses__():
        try:
            schema = klass.model_json_schema()
        except PydanticInvalidForJsonSchema as e:
            assert 0, f"Cannot generate json schema for {klass} due to " + str(e)

        class EventFactory(ModelFactory[klass]):
            pass

        for _ in range(10):
            first_json_str = EventFactory.build().model_dump_json()
            assert first_json_str == klass.model_validate_json(first_json_str).model_dump_json()
