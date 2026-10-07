from functools import lru_cache

from ...config import get_settings
from ...interfaces.queue import MessageQueue, QueueMessage
from .local_queue import LocalQueueService
from .sqs_queue import SQSQueueService


@lru_cache
def get_message_queue() -> MessageQueue:
    """Factory providing message queue implementation based on environment settings."""
    settings = get_settings()
    if settings.app_env in ("production", "staging") and getattr(settings, "aws_sqs_queue_url", None):
        return SQSQueueService(region_name=settings.aws_region)
    return LocalQueueService()


__all__ = ["MessageQueue", "QueueMessage", "LocalQueueService", "SQSQueueService", "get_message_queue"]
