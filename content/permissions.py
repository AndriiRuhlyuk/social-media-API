from rest_framework.permissions import BasePermission, SAFE_METHODS
from networking.models import Follow


class CanViewPostDetail(BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            if request.user.is_authenticated and obj.author == request.user.profile:
                return True
            if request.user.is_authenticated:
                return Follow.objects.filter(
                    follower=request.user.profile,
                    following=obj.author,
                    status=Follow.FollowStatus.ACCEPTED,
                ).exists()
            return False

        return obj.author == request.user.profile
