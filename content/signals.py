from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db.models import F
from content.models import Post


@receiver(post_save, sender=Post)
def update_posts_count(sender, instance, created, **kwargs):
    if created:
        instance.author.posts_count = F("posts_count") + 1
        instance.author.save()
