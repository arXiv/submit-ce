"""Read QA submission-snapshot messages from the local Pub/Sub emulator."""
import json
import os

os.environ.setdefault('GCLOUD_PROJECT', 'arxiv-development')
os.environ.setdefault('PUBSUB_EMULATOR_HOST', 'localhost:8085')

from google.api_core.exceptions import AlreadyExists
from google.cloud import pubsub_v1

from submit_ce.ui.config import settings

PROJECT = os.environ['GCLOUD_PROJECT']
TOPIC = settings.QA_PUBSUB_TOPIC
SUBSCRIPTION = pubsub_v1.SubscriberClient.subscription_path(PROJECT, 'local-qa-subscriber')


def ensure_topic_and_subscription(subscriber):
    """Create the topic and our subscription on the emulator (idempotent)."""
    try:
        pubsub_v1.PublisherClient().create_topic(request={'name': TOPIC})
    except AlreadyExists:
        pass
    try:
        subscriber.create_subscription(request={'name': SUBSCRIPTION, 'topic': TOPIC})
    except AlreadyExists:
        pass


def on_message(message):
    """Print one QA metadata message, then ack it."""
    try:
        data = json.loads(message.data.decode('utf-8'))
    except Exception:  # noqa: BLE001 - just show whatever arrived
        print(f"\n=== non-JSON message ===\n{message.data!r}")
        message.ack()
        return
    sub = data.get('arXiv_submissions', {})
    print(f"\n=== QA message: submission {sub.get('submission_id')} "
          f"(schema {data.get('version')}) ===")
    print(json.dumps(data, indent=2))
    message.ack()


def main():
    emulator = os.environ.get('PUBSUB_EMULATOR_HOST')
    with pubsub_v1.SubscriberClient() as subscriber:
        ensure_topic_and_subscription(subscriber)
        print(f"INFO: emulator      {emulator}")
        print(f"INFO: topic         {TOPIC}")
        print(f"INFO: subscription  {SUBSCRIPTION}")
        print(f"INFO: waiting for QA messages... Ctrl-C to stop.")
        future = subscriber.subscribe(SUBSCRIPTION, callback=on_message)
        try:
            future.result()
        except KeyboardInterrupt:
            future.cancel()
            future.result()
            print("\nINFO: stopped.")


if __name__ == '__main__':
    main()
