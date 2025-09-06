from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver
from django.db.models import F
from django.db.models.functions import Greatest
from .models import Follow
from user.models import Profile


@receiver(pre_save, sender=Follow)
def _stash_old_status(sender, instance: Follow, **kwargs):
    """Saved old status"""
    if instance.pk:
        try:
            old = sender.objects.only("status").get(pk=instance.pk).status
        except sender.DoesNotExist:
            old = None
    else:
        old = None
    instance._old_status = old


@receiver(post_save, sender=Follow)
def _update_counters_on_save(sender, instance: Follow, created, **kwargs):
    """
    Count following and followers for user
    """
    old = getattr(instance, "_old_status", None)
    new = instance.status

    if created and new == Follow.FollowStatus.ACCEPTED:
        Profile.objects.filter(pk=instance.follower_id).update(
            following_count=F("following_count") + 1
        )
        Profile.objects.filter(pk=instance.following_id).update(
            followers_count=F("followers_count") + 1
        )
        return

    if (
        not created
        and old != Follow.FollowStatus.ACCEPTED
        and new == Follow.FollowStatus.ACCEPTED
    ):
        Profile.objects.filter(pk=instance.follower_id).update(
            following_count=F("following_count") + 1
        )
        Profile.objects.filter(pk=instance.following_id).update(
            followers_count=F("followers_count") + 1
        )
        return

    if (
        not created
        and old == Follow.FollowStatus.ACCEPTED
        and new != Follow.FollowStatus.ACCEPTED
    ):
        Profile.objects.filter(pk=instance.follower_id).update(
            following_count=Greatest(F("following_count") - 1, 0)
        )
        Profile.objects.filter(pk=instance.following_id).update(
            followers_count=Greatest(F("followers_count") - 1, 0)
        )


@receiver(post_delete, sender=Follow)
def _update_counters_on_delete(sender, instance: Follow, **kwargs):
    if instance.status == Follow.FollowStatus.ACCEPTED:
        Profile.objects.filter(pk=instance.follower_id).update(
            following_count=Greatest(F("following_count") - 1, 0)
        )
        Profile.objects.filter(pk=instance.following_id).update(
            followers_count=Greatest(F("followers_count") - 1, 0)
        )
