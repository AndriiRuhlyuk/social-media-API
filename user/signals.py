from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db import transaction
from user.models import User
from user.tasks import create_user_profile_task


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        transaction.on_commit(lambda: create_user_profile_task.delay(instance.id))
