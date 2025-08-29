from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.db.models import F
from content.models import Post
from user.models import Profile


@receiver(post_save, sender=Post)
def update_posts_count(sender, instance, created, **kwargs):
    if created:
        Profile.objects.filter(id=instance.author_id).update(
            posts_count=F("posts_count") + 1
        )


@receiver(post_delete, sender=Post)
def decrease_posts_count(sender, instance, **kwargs):
    Profile.objects.filter(id=instance.author_id).update(
        posts_count=F("posts_count") - 1
    )
