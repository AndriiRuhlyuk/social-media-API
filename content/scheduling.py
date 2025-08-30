# content/scheduling.py
from celery import current_app
from celery.result import AsyncResult
from django.utils import timezone

from .models import Post
from .tasks import publish_post


def revoke_task(task_id: str) -> None:
    if not task_id:
        return
    try:

        current_app.control.revoke(task_id, terminate=False)
        AsyncResult(task_id).revoke(terminate=False)
    except Exception:
        pass


def schedule_publish(post: Post) -> str | None:
    """Create new ETA-task and return it ID or None."""
    if not post.scheduled_at or post.scheduled_at <= timezone.now():
        return None
    result = publish_post.apply_async((post.id,), eta=post.scheduled_at)
    return result.id


def reschedule_publish(post: Post) -> None:
    """Cancel old task and create new one, by update scheduled_task_id."""
    revoke_task(post.scheduled_task_id)
    task_id = schedule_publish(post)
    Post.objects.filter(pk=post.pk).update(scheduled_task_id=task_id)
