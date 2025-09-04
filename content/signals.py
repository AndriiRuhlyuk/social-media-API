from django.db.models.signals import pre_save, post_save, post_delete
from django.dispatch import receiver
from django.db.models import F
from content.models import Post
from content.scheduling import revoke_task
from user.models import Profile


@receiver(pre_save, sender=Post)
def check_status_change(sender, instance, **kwargs):
    """Save  previous post-status before post save."""
    if instance.id:
        old_post = Post.objects.get(id=instance.id)
        instance._old_status = old_post.status
    else:
        instance._old_status = None


@receiver(post_save, sender=Post)
def update_posts_count(sender, instance, created, **kwargs):
    """
    Update counter PUBLISHED posts in user profile or update post.

    Args:
        sender: Model Post.
        instance: Post instance.
        created: if Post was created.
        **kwargs: additional kwargs.
    """
    profile = Profile.objects.filter(id=instance.author_id).first()
    if profile:
        old_status = getattr(instance, "_old_status", None)
        if created and instance.status == Post.PostStatus.PUBLISHED:
            profile.posts_count = F("posts_count") + 1
            profile.save(update_fields=["posts_count"])
        elif old_status != instance.status:
            profile.posts_count = instance.author.posts.filter(
                status=Post.PostStatus.PUBLISHED
            ).count()
            profile.save(update_fields=["posts_count"])


@receiver(post_delete, sender=Post)
def decrease_posts_count(sender, instance, **kwargs):
    """
    Update counter PUBLISHED posts in user profile when post delete.

    Args:
        sender: Model Post.
        instance: Post instance.
        **kwargs: additional kwargs.
    """
    if instance.status == Post.PostStatus.PUBLISHED:
        Profile.objects.filter(id=instance.author_id).update(
            posts_count=F("posts_count") - 1
        )


@receiver(post_delete, sender=Post)
def revoke_scheduled_task(sender, instance, **kwargs):
    """Cancel scheduled Celery task when user delete SCHEDULED post."""
    if instance.status == Post.PostStatus.SCHEDULED and instance.scheduled_task_id:
        if not kwargs.get("cascade_from_profile", False):
            revoke_task(instance.scheduled_task_id)


@receiver(post_delete, sender=Profile)
def revoke_scheduled_tasks_for_profile(sender, instance, **kwargs):
    """
    Cancel all SCHEDULED posts for profile, when profile will delete.
    """
    scheduled_posts = Post.objects.filter(
        author=instance,
        status=Post.PostStatus.SCHEDULED,
        scheduled_task_id__isnull=False,
    )
    for post in scheduled_posts:
        revoke_task(post.scheduled_task_id)
        post_delete.send(sender=Post, instance=post, cascade_from_profile=True)
