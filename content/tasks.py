from celery import shared_task
from django.utils import timezone
from django.db import transaction
from content.models import Post


@shared_task(bind=True, max_retries=5)
def publish_post(self, post_id: int):
    """Idempotent task to publish a post"""
    try:
        with transaction.atomic():
            post = Post.objects.select_for_update().get(id=post_id)

            if post.status != Post.PostStatus.SCHEDULED:
                return

            if not post.scheduled_at or post.scheduled_at > timezone.now():
                return

            post.status = Post.PostStatus.PUBLISHED
            post.published_at = timezone.now()
            post.scheduled_at = None
            post.scheduled_task_id = None
            post.save()
    except Post.DoesNotExist:
        return
