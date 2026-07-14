import time
from unittest.mock import MagicMock
import inspect

import pytest
from google.cloud import pubsub_v1
from polyfactory.factories.pydantic_factory import ModelFactory
from pydantic import TypeAdapter

from submit_ce.domain.event.base import EventList
from .. import PubsubEventSubmitImplementation, Event


@pytest.fixture
def event_factory():
    class EventFactory(ModelFactory[Event]): ...
    return EventFactory


def test_pubsub_impl(submission_topic, project_id, event_factory):
    """Test PubSubEventSubmitImplementation."""
    mock_fn = MagicMock()
    mock_api = MagicMock()

    def subscription_consumer(message):
        mock_fn(message)
        message.ack()

    publisher, topic_path = submission_topic
    ps_impl = PubsubEventSubmitImplementation(publisher, topic_path, mock_api)

    with pubsub_v1.SubscriberClient() as subscriber:
        sub_path = subscriber.subscription_path(project_id, "fake-arxiv-sub")
        subscriber.create_subscription(request={"name": sub_path, "topic": topic_path})
        sub_future = subscriber.subscribe(sub_path, callback=subscription_consumer)

        for ii in range(10):
            event = event_factory.build()
            ps_impl.save(event, event.submission_id)
            time.sleep(0.07)
            assert mock_fn.call_count == ii+1  # subscription consumer was called
            msg = mock_fn.call_args_list[ii][0][0]
            assert msg and msg.data
            events_from_msg = TypeAdapter(EventList).validate_json(msg.data.decode("utf-8"))
            assert events_from_msg
            assert events_from_msg[0] == event
            assert mock_api.save.call_count == ii+1  # inner api was called

        sub_future.cancel()  # shut down subscription listener



def test_call_to_inner(submission_topic, project_id):
    """Test that PubSubEventSubmitImplementation calls inner instance."""
    mock_api = MagicMock()

    def subscription_consumer(message):
        message.ack()

    publisher, topic_path = submission_topic
    ps_impl = PubsubEventSubmitImplementation(publisher, topic_path, mock_api)

    with pubsub_v1.SubscriberClient() as subscriber:
        sub_path = subscriber.subscription_path(project_id, "fake-arxiv-sub")
        subscriber.create_subscription(request={"name": sub_path, "topic": topic_path})
        sub_future = subscriber.subscribe(sub_path, callback=subscription_consumer)

        methods = inspect.getmembers(PubsubEventSubmitImplementation, predicate=inspect.isfunction)
        for name, method in methods:
            if name in [ "__init__", "save", "serialize_msg"] or \
               PubsubEventSubmitImplementation.__name__ not in method.__str__():
                continue

            sig = inspect.signature(method)
            call_args = []
            call_kwargs = {}
            for pname, param in sig.parameters.items():
                if pname == "self":
                    continue
                if param.kind in (inspect.Parameter.VAR_POSITIONAL,
                                  inspect.Parameter.VAR_KEYWORD):
                    continue
                if param.kind == inspect.Parameter.KEYWORD_ONLY:
                    call_kwargs[pname] = MagicMock()
                else:
                    call_args.append(MagicMock())
            method(ps_impl, *call_args, **call_kwargs)
            time.sleep(0.07)
            mock_method = getattr(mock_api, name)
            assert mock_method and mock_method.call_count == 1

        assert len(mock_api.method_calls) > 0
        sub_future.cancel()  # shut down subscription listener
