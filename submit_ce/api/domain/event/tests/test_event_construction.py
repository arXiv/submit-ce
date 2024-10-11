"""Test that all event classes are well-formed."""
import inspect
import json
from unittest import TestCase

from hypothesis import given, settings
from hypothesis_jsonschema import from_schema
from pydantic import PydanticInvalidForJsonSchema

from ..base import Event


class TestNamed(TestCase):
    """Verify that all event classes are named."""

    def test_has_name(self):
        """All event classes must have a ``NAME`` attribute."""
        for klass in Event.__subclasses__():
            self.assertTrue(hasattr(klass, 'NAME'),
                            f'{klass.__name__} is missing attribute NAME')

    def test_has_named(self):
        """All event classes must have a ``NAMED`` attribute."""
        for klass in Event.__subclasses__():
            self.assertTrue(hasattr(klass, 'NAMED'),
                            f'{klass.__name__} is missing attribute NAMED')


class TestHasProjection(TestCase):
    """Verify that all event classes have a projection method."""

    def test_has_projection(self):
        """Each event class must have an instance method ``project()``."""
        for klass in Event.__subclasses__():
            self.assertTrue(hasattr(klass, 'project'),
                            f'{klass.__name__} is missing project() method')
            self.assertTrue(inspect.isfunction(klass.project),
                            f'{klass.__name__} is missing project() method')


class TestHasValidation(TestCase):
    """Verify that all event classes have a projection method."""

    def test_has_validate(self):
        """Each event class must have an instance method ``validate()``."""
        for klass in Event.__subclasses__():
            self.assertTrue(hasattr(klass, 'validate'),
                            f'{klass.__name__} is missing validate() method')
            self.assertTrue(inspect.isfunction(klass.validate),
                            f'{klass.__name__} is missing validate() method')

class TestCanRoundtrip(TestCase):
    """Verify that all event classes can round trip."""
    def test_round_trip(self):
        """Verify that all event classes can be converted to JSON and back."""

        for klass in Event.__subclasses__():
            try:
                schema = klass.model_json_schema()
            except PydanticInvalidForJsonSchema as e:
                self.fail(f"Cannot generate json schema for {klass} due to " + str(e))

            @given(from_schema(schema))
            @settings(max_examples=3)
            def do_round_trip(klass, first_dict):
                first_instance = klass.model_validate_json(json.dumps(first_dict))
                json_str = first_instance.model_dump_json()
                second_instance = klass.model_validate_json(json_str)
                self.assertEqual(first_instance, second_instance)

            do_round_trip(klass)