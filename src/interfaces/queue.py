from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable


@dataclass
class QueueMessage:
    """Standardized asynchronous queue message wrapper."""
    id: str
    payload: dict[str, Any]
    receipt_handle: str
    attributes: dict[str, Any] = field(default_factory=dict)
    retry_count: int = 0
    timestamp: datetime = field(default_factory=datetime.utcnow)


@runtime_checkable
class MessageQueue(Protocol):
    """
    Interface for enterprise asynchronous message queues.
    Supports in-memory/Redis local queues and AWS SQS / Kafka in production.
    """

    async def publish(
        self,
        queue_name: str,
        payload: dict[str, Any],
        message_attributes: dict[str, Any] | None = None,
        delay_seconds: int = 0,
    ) -> str:
        """
        Publishes a message to the specified queue.
        Returns the unique message identifier.
        """
        ...

    async def consume(
        self,
        queue_name: str,
        batch_size: int = 10,
        visibility_timeout: int = 30,
    ) -> list[QueueMessage]:
        """
        Polls and consumes messages from the queue.
        Retrieved messages are hidden for the visibility_timeout period.
        """
        ...

    async def ack(self, queue_name: str, receipt_handle: str) -> None:
        """Acknowledges successful processing and permanently deletes the message from queue."""
        ...

    async def nack(
        self,
        queue_name: str,
        receipt_handle: str,
        requeue: bool = True,
        backoff_seconds: int = 0,
    ) -> None:
        """Negative acknowledgment; returns message to queue or triggers redelivery."""
        ...

    async def send_to_dead_letter(
        self,
        queue_name: str,
        message: QueueMessage,
        reason: str,
    ) -> None:
        """Explicitly transfers a permanently failed message to the Dead-Letter Queue (DLQ)."""
        ...

    async def get_queue_depth(self, queue_name: str) -> int:
        """Returns approximate number of visible messages waiting in the queue."""
        ...

    async def get_dlq_depth(self, queue_name: str) -> int:
        """Returns number of messages quarantined in the Dead-Letter Queue."""
        ...
