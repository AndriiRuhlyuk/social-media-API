from celery import shared_task
from rest_framework_simplejwt.token_blacklist.models import (
    OutstandingToken,
)
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)


@shared_task
def flush_expired_tokens():
    """
    Periodically deletes expired tokens from OutstandingToken.
    Related BlacklistedToken entries are automatically deleted via CASCADE.
    Runs daily to optimize database size and performance.
    """
    try:
        current_time = timezone.now()
        deleted_count, _ = OutstandingToken.objects.filter(
            expires_at__lt=current_time
        ).delete()
        logger.info(
            f"Deleted {deleted_count} expired outstanding tokens (CASCADE deleted related blacklisted tokens)"
        )
        return deleted_count
    except Exception as e:
        logger.error(f"Failed to flush expired tokens: {str(e)}")
        return 0
