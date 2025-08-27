from django.shortcuts import render
from rest_framework import viewsets, permissions, response, status, decorators
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from django.db.models import Exists, OuterRef, Value, CharField, Case, When

from networking.models import Follow
from networking.permissions import CanViewProfileDetail
from networking.serializers import (
    ProfileListSerializer,
    ProfileDetailSerializer,
    PrivateProfileSerializer,
    FollowRequestSerializer,
    EmptySerializer,
)
from user.models import Profile


class PublicProfileViewSet(viewsets.ReadOnlyModelViewSet):
    """
    - GET /profiles/       -> list (without my profile)
    - GET /profiles/{id}/  -> full profile info (if not is_privet), or partially
    - POST /profiles/{id}/follow/
    - POST /profiles/{id}/unfollow/
    """

    queryset = Profile.objects.select_related("user")
    serializer_class = ProfileListSerializer
    permission_classes = (permissions.IsAuthenticatedOrReadOnly,)

    def get_queryset(self):
        queryset = super().get_queryset().select_related("user")
        user = getattr(self.request, "user", None)
        if user and user.is_authenticated:
            queryset = queryset.exclude(user_id=user.id)
        me_profile = getattr(user, "profile", None)

        if me_profile:
            accepted_queryset = Follow.objects.filter(
                follower_id=me_profile.id,
                following_id=OuterRef("pk"),
                status=Follow.FollowStatus.ACCEPTED,
            )
            pending_queryset = Follow.objects.filter(
                follower_id=me_profile.id,
                following_id=OuterRef("pk"),
                status=Follow.FollowStatus.PENDING,
            )
            rejected_queryset = Follow.objects.filter(
                follower_id=me_profile.id,
                following_id=OuterRef("pk"),
                status=Follow.FollowStatus.REJECTED,
            )

            queryset = queryset.annotate(
                is_follow_accepted=Exists(accepted_queryset),
                is_follow_pending=Exists(pending_queryset),
                is_follow_rejected=Exists(rejected_queryset),
            ).annotate(
                follow_status=Case(
                    When(
                        is_follow_accepted=True,
                        then=Value(Follow.FollowStatus.ACCEPTED),
                    ),
                    When(
                        is_follow_pending=True, then=Value(Follow.FollowStatus.PENDING)
                    ),
                    When(
                        is_follow_rejected=True,
                        then=Value(Follow.FollowStatus.REJECTED),
                    ),
                    default=Value(None),
                    output_field=CharField(),
                )
            )

        return queryset

    def retrieve(self, request, *args, **kwargs):
        inst = self.get_object()

        can_view_full = CanViewProfileDetail().has_object_permission(
            request, self, inst
        )
        if can_view_full:
            serializer = ProfileDetailSerializer(
                inst, context=self.get_serializer_context()
            )
        else:
            serializer = PrivateProfileSerializer(
                inst, context=self.get_serializer_context()
            )
        return response.Response(serializer.data)

    def get_serializer_class(self):
        if self.action in [
            "follow",
            "unfollow",
            "accept_request",
            "reject_request",
            "my_pending_requests",
        ]:
            return EmptySerializer
        return ProfileListSerializer

    @decorators.action(
        detail=True, methods=["post"], permission_classes=[permissions.IsAuthenticated]
    )
    def follow(self, request, pk=None):
        """Follow request"""
        me = request.user.profile
        target = self.get_object()
        if me.pk == target.pk:
            return response.Response(
                {"detail": "Cannot follow yourself."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        desired_status = (
            Follow.FollowStatus.PENDING
            if target.is_private
            else Follow.FollowStatus.ACCEPTED
        )

        obj, created = Follow.objects.get_or_create(
            follower=me, following=target, defaults={"status": desired_status}
        )
        if (
            not created
            and target.is_private
            and obj.status != Follow.FollowStatus.ACCEPTED
        ):
            obj.status = Follow.FollowStatus.PENDING
            obj.save(update_fields=["status"])

        if obj.status == Follow.FollowStatus.PENDING:
            code = status.HTTP_202_ACCEPTED
            msg = "Request to following was sent (Pending)."
        else:
            code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
            msg = "Get Follow (Accepted)."

        return Response({"detail": msg, "status": obj.status}, status=code)

    @decorators.action(
        detail=True, methods=["post"], permission_classes=[permissions.IsAuthenticated]
    )
    def unfollow(self, request, pk=None):
        """Unfollow request"""
        me = request.user.profile
        target = self.get_object()
        if me.pk == target.pk:
            return response.Response(
                {"detail": "Cannot unfollow yourself."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        deleted, _ = Follow.objects.filter(follower=me, following=target).delete()
        return response.Response(
            {"detail": "Unfollow." if deleted else "Follow not exist."}
        )

    @decorators.action(
        detail=False,
        methods=["get"],
        permission_classes=[permissions.IsAuthenticated],
        url_path="my/pending-requests",
    )
    def my_pending_requests(self, request):
        """List of requests to follow, that wait my decision."""
        me = request.user.profile
        qs = (
            Follow.objects.select_related("follower__user")
            .filter(following=me, status=Follow.FollowStatus.PENDING)
            .order_by("-created_at")
        )
        ser = FollowRequestSerializer(
            qs, many=True, context=self.get_serializer_context()
        )
        return response.Response(ser.data)

    @decorators.action(
        detail=False,
        methods=["post"],
        permission_classes=[permissions.IsAuthenticated],
        url_path=r"requests/(?P<follower_id>\d+)/accept",
    )
    def accept_request(self, request, follower_id: str = None):
        """Accept request to follow from follower_id to my profile."""
        me = request.user.profile
        obj = (
            Follow.objects.select_related("follower__user")
            .filter(
                follower_id=follower_id,
                following=me,
                status=Follow.FollowStatus.PENDING,
            )
            .first()
        )
        if not obj:
            raise NotFound("Request not found or it not in status Pending.")

        obj.status = Follow.FollowStatus.ACCEPTED
        obj.save(update_fields=["status"])
        return response.Response(
            {
                "detail": "Request accepted (Accepted).",
                "follower_id": obj.follower_id,
                "status": obj.status,
            }
        )

    @decorators.action(
        detail=False,
        methods=["post"],
        permission_classes=[permissions.IsAuthenticated],
        url_path=r"requests/(?P<follower_id>\d+)/reject",
    )
    def reject_request(self, request, follower_id: str = None):
        """Reject request to follow from follower_id to my profile."""
        me = request.user.profile
        obj = (
            Follow.objects.select_related("follower__user")
            .filter(
                follower_id=follower_id,
                following=me,
                status=Follow.FollowStatus.PENDING,
            )
            .first()
        )
        if not obj:
            raise NotFound("Request not found or it not in status Pending.")

        obj.status = Follow.FollowStatus.REJECTED
        obj.save(update_fields=["status"])
        return response.Response(
            {
                "detail": "Request rejected (Rejected).",
                "follower_id": obj.follower_id,
                "status": obj.status,
            }
        )
