import json
import logging
from typing import Any

from ...interfaces.queue import MessageQueue, QueueMessage
from .local_queue import LocalQueueService

logger = logging.getLogger(__name__)


class SQSQueueService(MessageQueue):
    """
    Production AWS SQS implementation with native Dead Letter Queue redrive support.
    Falls back gracefully to LocalQueueService if boto3 or AWS credentials are not configured.
    """

    def __init__(
        self,
        region_name: str = "us-east-1",
        endpoint_url: str | None = None,
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
    ):
        self.region_name = region_name
        self.endpoint_url = endpoint_url
        self._sqs_client = None
        self._fallback_local = LocalQueueService()
        self._queue_urls: dict[str, str] = {}

        try:
            import boto3

            if aws_access_key_id and aws_secret_access_key:
                self._sqs_client = boto3.client(
                    "sqs",
                    region_name=self.region_name,
                    endpoint_url=self.endpoint_url,
                    aws_access_key_id=aws_access_key_id,
                    aws_secret_access_key=aws_secret_access_key,
                )
            else:
                self._sqs_client = boto3.client("sqs", region_name=self.region_name, endpoint_url=self.endpoint_url)
            logger.info(f"Initialized AWS SQS client in region '{region_name}'")
        except Exception as e:
            logger.warning(f"Failed to initialize AWS SQS client ({e}); using LocalQueueService fallback")
            self._sqs_client = None

    def _get_queue_url(self, queue_name: str) -> str:
        if queue_name in self._queue_urls:
            return self._queue_urls[queue_name]
        if not self._sqs_client:
            return ""

        try:
            res = self._sqs_client.get_queue_url(QueueName=queue_name)
            url = res["QueueUrl"]
            self._queue_urls[queue_name] = url
            return url
        except Exception as e:
            logger.error(f"Failed to get SQS QueueUrl for '{queue_name}': {e}")
            return ""

    async def publish(
        self,
        queue_name: str,
        payload: dict[str, Any],
        message_attributes: dict[str, Any] | None = None,
        delay_seconds: int = 0,
    ) -> str:
        if not self._sqs_client:
            return await self._fallback_local.publish(queue_name, payload, message_attributes, delay_seconds)

        queue_url = self._get_queue_url(queue_name)
        if not queue_url:
            return await self._fallback_local.publish(queue_name, payload, message_attributes, delay_seconds)

        try:
            body = json.dumps(payload)
            res = self._sqs_client.send_message(
                QueueUrl=queue_url,
                MessageBody=body,
                DelaySeconds=min(delay_seconds, 900),
            )
            return res.get("MessageId", "")
        except Exception as e:
            logger.warning(f"SQS publish failed ({e}); falling back to local queue")
            return await self._fallback_local.publish(queue_name, payload, message_attributes, delay_seconds)

    async def consume(
        self,
        queue_name: str,
        batch_size: int = 10,
        visibility_timeout: int = 30,
    ) -> list[QueueMessage]:
        if not self._sqs_client:
            return await self._fallback_local.consume(queue_name, batch_size, visibility_timeout)

        queue_url = self._get_queue_url(queue_name)
        if not queue_url:
            return await self._fallback_local.consume(queue_name, batch_size, visibility_timeout)

        try:
            res = self._sqs_client.receive_message(
                QueueUrl=queue_url,
                MaxNumberOfMessages=min(batch_size, 10),
                VisibilityTimeout=visibility_timeout,
                AttributeNames=["ApproximateReceiveCount"],
            )
            messages = []
            for item in res.get("Messages", []):
                payload = json.loads(item.get("Body", "{}"))
                retry_count = int(item.get("Attributes", {}).get("ApproximateReceiveCount", 1)) - 1
                messages.append(
                    QueueMessage(
                        id=item.get("MessageId", ""),
                        payload=payload,
                        receipt_handle=item.get("ReceiptHandle", ""),
                        retry_count=retry_count,
                    )
                )
            return messages
        except Exception as e:
            logger.warning(f"SQS consume failed ({e}); using local queue fallback")
            return await self._fallback_local.consume(queue_name, batch_size, visibility_timeout)

    async def ack(self, queue_name: str, receipt_handle: str) -> None:
        if not self._sqs_client:
            return await self._fallback_local.ack(queue_name, receipt_handle)

        queue_url = self._get_queue_url(queue_name)
        if not queue_url:
            return await self._fallback_local.ack(queue_name, receipt_handle)

        try:
            self._sqs_client.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
        except Exception as e:
            logger.warning(f"SQS delete_message error: {e}")

    async def nack(
        self,
        queue_name: str,
        receipt_handle: str,
        requeue: bool = True,
        backoff_seconds: int = 0,
    ) -> None:
        if not self._sqs_client:
            return await self._fallback_local.nack(queue_name, receipt_handle, requeue, backoff_seconds)

        queue_url = self._get_queue_url(queue_name)
        if not queue_url:
            return await self._fallback_local.nack(queue_name, receipt_handle, requeue, backoff_seconds)

        try:
            if requeue:
                self._sqs_client.change_message_visibility(
                    QueueUrl=queue_url,
                    ReceiptHandle=receipt_handle,
                    VisibilityTimeout=backoff_seconds,
                )
            else:
                self._sqs_client.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
        except Exception as e:
            logger.warning(f"SQS nack error: {e}")

    async def send_to_dead_letter(
        self,
        queue_name: str,
        message: QueueMessage,
        reason: str,
    ) -> None:
        # In production SQS, redrive policy automatically shifts to DLQ on maxReceiveCount.
        # Alternatively, publish directly to DLQ.
        dlq_name = f"{queue_name}-dlq"
        await self.publish(dlq_name, {**message.payload, "dlq_reason": reason})
        await self.ack(queue_name, message.receipt_handle)

    async def get_queue_depth(self, queue_name: str) -> int:
        if not self._sqs_client:
            return await self._fallback_local.get_queue_depth(queue_name)

        queue_url = self._get_queue_url(queue_name)
        if not queue_url:
            return await self._fallback_local.get_queue_depth(queue_name)

        try:
            attrs = self._sqs_client.get_queue_attributes(
                QueueUrl=queue_url,
                AttributeNames=["ApproximateNumberOfMessages"],
            )
            return int(attrs.get("Attributes", {}).get("ApproximateNumberOfMessages", 0))
        except Exception:
            return await self._fallback_local.get_queue_depth(queue_name)

    async def get_dlq_depth(self, queue_name: str) -> int:
        return await self.get_queue_depth(f"{queue_name}-dlq")
