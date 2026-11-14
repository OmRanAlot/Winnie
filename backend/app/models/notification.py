# Notification + NotificationSubscription.
# Notification: recipient, kind (task_done, due_soon, overdue, blocked, reassignment,
#   email_reminder, question_routed), payload, channel (imessage | discord | web), sent/acked times.
# Subscription: who cares about what (e.g. sponsorship tasks -> President, VP, Industry Partnership Chair #2).

from dataclasses import dataclass

from pyparsing import Optional


@dataclass
class Notification:
    recipient: str  # e.g., email or user ID
    kind: str  # e.g., task_done, due_soon, overdue, blocked, reassignment, email_reminder, question_routed
    payload: dict  # additional data relevant to the notification
    channel: str  # e.g., imessage, discord, web
    sent_time: Optional[str] = None  # ISO format datetime string
    asked_time: Optional[str] = None  # ISO format datetime string

    def __post_init__(self):
        if not self.recipient:
            raise ValueError("Notification recipient cannot be empty.")
        if not self.kind:
            raise ValueError("Notification kind cannot be empty.")
        if not self.channel:
            raise ValueError("Notification channel cannot be empty.")


@dataclass
class NotificationSubscription:
    subscriber: str  # e.g., email or user ID
    # e.g., task_done, due_soon, overdue, blocked, reassignment, email_reminder, question_routed
    kind: str
    def __post_init__(self):
        if not self.subscriber:
            raise ValueError("NotificationSubscription subscriber cannot be empty.")
        if not self.kind:
            raise ValueError("NotificationSubscription kind cannot be empty.")