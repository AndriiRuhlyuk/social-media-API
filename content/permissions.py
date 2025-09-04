from rest_framework.permissions import BasePermission, SAFE_METHODS

from content.models import Post
from networking.models import Follow


class CanViewPostDetail(BasePermission):
    """Permission to view post detail and comment post"""

    def has_object_permission(self, request, view, obj):
        if not request.user.is_authenticated:
            return False

        if obj.author == request.user.profile:
            return True

        if request.method in SAFE_METHODS or request.method == "POST":
            return (
                obj.status == Post.PostStatus.PUBLISHED
                and Follow.objects.filter(
                    follower=request.user.profile,
                    following=obj.author,
                    status=Follow.FollowStatus.ACCEPTED,
                ).exists()
            )

        return False


class IsCommentAuthorOrReadOnly(BasePermission):
    def has_object_permission(self, request, view, obj):
        return request.method in SAFE_METHODS or obj.author == request.user.profile
