from rest_framework.permissions import BasePermission


class CanViewProfileDetail(BasePermission):
    def has_object_permission(self, request, view, obj):

        return obj.can_view_details(request.user)
