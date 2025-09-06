from rest_framework.permissions import BasePermission


class CanViewProfileDetail(BasePermission):
    """Permission to view profile details"""

    def has_object_permission(self, request, view, obj):

        return obj.can_view_details(request.user)
