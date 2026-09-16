from functools import partial
import time
from google.cloud import pubsub_v1
from unittest.mock import MagicMock
from concurrent import futures


def test_basic_subscribe(submission_topic, project_id, unique_suffix):
    """Test of a subscription with a single event"""
    mock_fn = MagicMock()

    def subscription_consumer(message):
        mock_fn(message)
        message.ack()

    publisher, topic_path = submission_topic
    subscriber = pubsub_v1.SubscriberClient()
    sub_path = subscriber.subscription_path(project_id, f"sub-{unique_suffix}")

    with subscriber:
        subscriber.create_subscription(request={"name": sub_path, "topic": topic_path})
        sub_future = subscriber.subscribe(sub_path, callback=subscription_consumer)
        pub_future = publisher.publish(topic_path, b"test message")
        futures.wait([pub_future], timeout=1)
        time.sleep(0.1)
        sub_future.cancel()  # shut down subscription listener
        assert mock_fn.call_count == 1


def test_multi_subscribe(submission_topic, project_id, unique_suffix):
    """Test of several subscribers to same publish topic"""
    n = 10
    mock_fns = [MagicMock() for _ in range(0, n)]

    def consumer(mock_fn, message):
        mock_fn(message)
        message.ack()

    publisher, topic_path = submission_topic
    subscriber = pubsub_v1.SubscriberClient()
    sub_paths = [subscriber.subscription_path(project_id, f"sub-{unique_suffix}-{i}") for i in range(0, n)]
    with subscriber:
        [subscriber.create_subscription(request={"name": sub_path, "topic": topic_path})
         for sub_path in sub_paths]  # make n subscription topics
        # subscribe to those n topics with consume functions
        sub_futures = [subscriber.subscribe(sub_path, callback=partial(consumer, mock_fn))
                       for sub_path, mock_fn in zip(sub_paths, mock_fns)]

        pub_future = publisher.publish(topic_path, b"test message")
        futures.wait([pub_future])
        time.sleep(0.1)
        [sub_fut.cancel() for sub_fut in sub_futures]
        assert all([mock_fn.call_count == 1 for mock_fn in mock_fns])
