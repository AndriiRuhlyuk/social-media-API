from celery import shared_task
from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework_simplejwt.token_blacklist.models import (
    OutstandingToken,
)
from django.utils import timezone
import logging

from user.models import Profile

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def flush_expired_tokens(self):
    """
    Periodically deletes expired tokens from OutstandingToken in batches.
    Related BlacklistedToken entries are automatically deleted via CASCADE.
    Runs daily to optimize database size and performance.
    """
    try:

        current_time = timezone.now()
        batch_size = 1000
        total_deleted = 0

        while True:
            with transaction.atomic():
                expired_ids = list(
                    OutstandingToken.objects.filter(
                        expires_at__lt=current_time
                    ).values_list("id", flat=True)[:batch_size]
                )

                if not expired_ids:
                    break

                deleted_count, _ = OutstandingToken.objects.filter(
                    id__in=expired_ids
                ).delete()

                total_deleted += deleted_count
                logger.info(f"Deleted {deleted_count} tokens in batch")

                if len(expired_ids) < batch_size:
                    break

        logger.info(f"Total deleted {total_deleted} expired tokens")
        return total_deleted

    except Exception as e:
        logger.error(f"Failed to flush expired tokens: {str(e)}")
        self.retry(exc=e, countdown=5)
        return 0


@shared_task(bind=True)
def create_user_profile_task(self, user_id):
    """
    Asynchronously creates a Profile for a newly created User.
    Args:
        user_id: The ID of the User for whom to create a Profile.
    """
    User = get_user_model()
    try:
        with transaction.atomic():
            user = User.objects.get(id=user_id)
            profile, created = Profile.objects.get_or_create(
                user=user,
                defaults={
                    "is_private": False,
                    "followers_count": 0,
                    "following_count": 0,
                    "posts_count": 0,
                },
            )

            if created:
                logger.info(f"Created profile for user {user.email} (ID: {user_id})")
            else:
                logger.info(
                    f"Profile already exists for user {user.email} (ID: {user_id})"
                )

            return created

    except User.DoesNotExist:
        logger.error(f"User with ID {user_id} not found")
        return False
    except Exception as e:
        logger.error(f"Failed to create profile for user ID {user_id}: {str(e)}")
        self.retry(exc=e, countdown=5)
        return False
