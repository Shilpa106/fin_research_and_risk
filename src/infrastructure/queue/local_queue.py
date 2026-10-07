import asyncio
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any

from ...interfaces.queue import MessageQueue, QueueMessage

logger = logging.getLogger(__name__)


class LocalQueueService(MessageQueue):
    """
    In-memory asynchronous queue service supporting DLQ and visibility timeouts.
    Enables local testing, offline workflows, and containerized development without AWS SQS.
    """

    def __init__(self, default_visibility_timeout: int = 30, max_retries: int = 3):
        self.default_visibility_timeout = default_visibility_timeout
        self.max_retries = max_retries
        self._queues: dict[str, list[dict[str, Any]]] = {}
        self._in_flight: dict[str, dict[str, Any]] = {}
        self._dead_letter_queues: dict[str, list[dict[str, Any]]] = {}
        self._lock = asyncio.Lock()

    def _ensure_queue(self, queue_name: str) -> None:
        if queue_name not in self._queues:
            self._queues[queue_name] = []
        if queue_name not in self._dead_letter_queues:
            self._dead_letter_queues[queue_name] = []

    async def publish(
        self,
        queue_name: str,
        payload: dict[str, Any],
        message_attributes: dict[str, Any] | None = None,
        delay_seconds: int = 0,
    ) -> str:
        """Publishes a new message into the target in-memory queue."""
        async with self._lock:
            self._ensure_queue(queue_name)
            msg_id = str(uuid.uuid4())
            deliver_at = datetime.utcnow() + timedelta(seconds=delay_seconds)

            entry = {
                "id": msg_id,
                "payload": payload,
                "attributes": message_attributes or {},
                "retry_count": 0,
                "created_at": datetime.utcnow(),
                "deliver_at": deliver_at,
            }
            self._queues[queue_name].append(entry)
            logger.debug(f"[LocalQueue] Published message {msg_id} to queue '{queue_name}'")
            return msg_id

    async def consume(
        self,
        queue_name: str,
        batch_size: int = 10,
        visibility_timeout: int = 30,
    ) -> list[QueueMessage]:
        """Polls ready messages from the queue and marks them in-flight."""
        async with self._lock:
            self._ensure_queue(queue_name)
            now = datetime.utcnow()

            # First, check for expired in-flight messages that should be reclaimed
            expired_receipts = [
                receipt
                for receipt, item in self._in_flight.items()
                if item["queue_name"] == queue_name and item["visible_after"] <= now
            ]
            for receipt in expired_receipts:
                reclaimed = self._in_flight.pop(receipt)
                item_data = reclaimed["item"]
                item_data["retry_count"] += 1
                if item_data["retry_count"] > self.max_retries:
                    # Move to dead letter queue
                    self._dead_letter_queues[queue_name].append({
                        **item_data,
                        "failure_reason": f"Exhausted visibility retries ({self.max_retries})",
                        "dead_lettered_at": now,
                    })
                    logger.warning(f"[LocalQueue] Message {item_data['id']} exceeded retries -> DLQ")
                else:
                    item_data["deliver_at"] = now
                    self._queues[queue_name].append(item_data)

            # Consume ready messages
            ready_messages: list[QueueMessage] = []
            remaining_queue: list[dict[str, Any]] = []

            for item in self._queues[queue_name]:
                if len(ready_messages) < batch_size and item["deliver_at"] <= now:
                    receipt_handle = f"receipt_{uuid.uuid4().hex}"
                    self._in_flight[receipt_handle] = {
                        "queue_name": queue_name,
                        "item": item,
                        "visible_after": now + timedelta(seconds=visibility_timeout),
                    }
                    ready_messages.append(
                        QueueMessage(
                            id=item["id"],
                            payload=item["payload"],
                            attributes=item["attributes"],
                            receipt_handle=receipt_handle,
                            retry_count=item["retry_count"],
                            timestamp=item["created_at"],
                        )
                    )
                else:
                    remaining_queue.append(item)

            self._queues[queue_name] = remaining_queue
            return ready_messages

    async def ack(self, queue_name: str, receipt_handle: str) -> None:
        """Removes the message from in-flight storage upon successful completion."""
        async with self._lock:
            if receipt_handle in self._in_flight:
                msg_id = self._in_flight[receipt_handle]["item"]["id"]
                del self._in_flight[receipt_handle]
                logger.debug(f"[LocalQueue] ACK message {msg_id} on '{queue_name}'")

    async def nack(
        self,
        queue_name: str,
        receipt_handle: str,
        requeue: bool = True,
        backoff_seconds: int = 0,
    ) -> None:
        """Negative acknowledgment; requeues or drops message."""
        async with self._lock:
            self._ensure_queue(queue_name)
            if receipt_handle not in self._in_flight:
                return

            item_info = self._in_flight.pop(receipt_handle)
            item = item_info["item"]
            item["retry_count"] += 1

            if not requeue or item["retry_count"] > self.max_retries:
                # Dead letter
                self._dead_letter_queues[queue_name].append({
                    **item,
                    "failure_reason": f"NACKed (requeue={requeue}, retries={item['retry_count']})",
                    "dead_lettered_at": datetime.utcnow(),
                })
                logger.warning(f"[LocalQueue] Message {item['id']} NACKed -> routed to DLQ")
            else:
                item["deliver_at"] = datetime.utcnow() + timedelta(seconds=backoff_seconds)
                self._queues[queue_name].append(item)
                logger.debug(f"[LocalQueue] Requeued message {item['id']} with {backoff_seconds}s backoff")

    async def send_to_dead_letter(
        self,
        queue_name: str,
        message: QueueMessage,
        reason: str,
    ) -> None:
        """Manually moves a message to DLQ."""
        async with self._lock:
            self._ensure_queue(queue_name)
            if message.receipt_handle in self._in_flight:
                del self._in_flight[message.receipt_handle]

            self._dead_letter_queues[queue_name].append({
                "id": message.id,
                "payload": message.payload,
                "attributes": message.attributes,
                "retry_count": message.retry_count,
                "failure_reason": reason,
                "dead_lettered_at": datetime.utcnow(),
            })
            logger.warning(f"[LocalQueue] Message {message.id} sent directly to DLQ: {reason}")

    async def get_queue_depth(self, queue_name: str) -> int:
        """Returns count of active pending messages."""
        async with self._lock:
            self._ensure_queue(queue_name)
            return len(self._queues[queue_name])

    async def get_dlq_depth(self, queue_name: str) -> int:
        """Returns count of dead-lettered messages."""
        async with self._lock:
            self._ensure_queue(queue_name)
            return len(self._dead_letter_queues[queue_name])
