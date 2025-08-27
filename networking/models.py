from django.db import models
from django.db.models import Q, F


class Follow(models.Model):
    class FollowStatus(models.TextChoices):
        PENDING = "Pending"
        ACCEPTED = "Accepted"
        REJECTED = "Rejected"

    follower = models.ForeignKey(
        "user.Profile", on_delete=models.CASCADE, related_name="following_links"
    )
    following = models.ForeignKey(
        "user.Profile", on_delete=models.CASCADE, related_name="follower_links"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=10, choices=FollowStatus.choices, default=FollowStatus.ACCEPTED
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["follower", "following"], name="unique_follow_profile"
            ),
            models.CheckConstraint(
                check=~Q(follower=F("following")), name="no_self_follow_profile"
            ),
        ]
        indexes = [
            models.Index(fields=["follower"]),
            models.Index(fields=["following"]),
            models.Index(fields=["status"]),
        ]
