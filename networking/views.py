from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse
from rest_framework import filters
from django.db.models import Q
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets, permissions, response, status, decorators
from rest_framework.exceptions import NotFound
from rest_framework.pagination import PageNumberPagination
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


class PublicProfilePagination(PageNumberPagination):
    page_size = 10
    max_page_size = 100


class PublicProfileViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API for managing user profiles.
    - GET /profiles/       -> List all profiles (excludes current user's profile)
    - GET /profiles/{id}/  -> Retrieve full profile info (if not private) or partial info
    - POST /profiles/{id}/follow/ -> Send a follow request
    - POST /profiles/{id}/unfollow/ -> Unfollow a user
    - GET /profiles/my/followers/ -> List all users following the current user
    - GET /profiles/my/following/ -> List all users the current user is following
    - GET /profiles/my/pending-requests/ -> List pending follow requests
    - POST /profiles/requests/{follower_id}/accept/ -> Accept a follow request
    - POST /profiles/requests/{follower_id}/reject/ -> Reject a follow request
    """

    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["gender", "is_private", "location"]
    pagination_class = PublicProfilePagination
    search_fields = ["first_name", "last_name", "^user__email"]
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

        search_query = self.request.query_params.get("search")
        if search_query:
            queryset = queryset.filter(
                Q(user__email__icontains=search_query)
                | Q(first_name__icontains=search_query)
                | Q(last_name__icontains=search_query)
            )

        location_query = self.request.query_params.get("location")
        if location_query:
            queryset = queryset.filter(Q(location__icontains=location_query))

        return queryset

    @extend_schema(
        description="Retrieve a profile. Returns full details if public or accessible, otherwise partial details.",
        responses={
            200: OpenApiResponse(
                ProfileDetailSerializer, description="Full profile details"
            ),
            403: OpenApiResponse(
                PrivateProfileSerializer,
                description="Partial profile details for private profile",
            ),
        },
    )
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

    @extend_schema(
        description="Send a follow request to a user. Returns 202 if pending, 201 if created, or 200 if already accepted.",
        responses={
            201: OpenApiResponse(
                description="Follow request accepted",
                examples={
                    "application/json": {
                        "detail": "Get Follow (Accepted).",
                        "status": "Accepted",
                    }
                },
            ),
            202: OpenApiResponse(
                description="Follow request pending",
                examples={
                    "application/json": {
                        "detail": "Request to following was sent (Pending).",
                        "status": "Pending",
                    }
                },
            ),
            400: OpenApiResponse(
                description="Cannot follow yourself",
                examples={"application/json": {"detail": "Cannot follow yourself."}},
            ),
        },
    )
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

    @extend_schema(
        description="Unfollow a user.",
        responses={
            200: OpenApiResponse(
                description="Unfollowed or follow does not exist",
                examples={"application/json": {"detail": "Unfollow."}},
            ),
            400: OpenApiResponse(
                description="Cannot unfollow yourself",
                examples={"application/json": {"detail": "Cannot unfollow yourself."}},
            ),
        },
    )
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
        queryset = (
            Follow.objects.select_related("follower__user")
            .filter(following=me, status=Follow.FollowStatus.PENDING)
            .order_by("-created_at")
        )
        serializer = FollowRequestSerializer(
            queryset, many=True, context=self.get_serializer_context()
        )
        return response.Response(serializer.data)

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

    @decorators.action(
        detail=False,
        methods=["get"],
        permission_classes=[permissions.IsAuthenticated],
        url_path="my/following",
    )
    def my_following(self, request):
        """A list of all users the user is following."""
        me = request.user.profile
        queryset = self.get_queryset().filter(
            pk__in=Follow.objects.filter(
                follower=me, status=Follow.FollowStatus.ACCEPTED
            ).values_list("following_id", flat=True)
        )

        serializer = ProfileListSerializer(
            queryset,
            many=True,
            context=self.get_serializer_context(),
        )
        return response.Response(serializer.data)

    @decorators.action(
        detail=False,
        methods=["get"],
        permission_classes=[permissions.IsAuthenticated],
        url_path="my/followers",
    )
    def my_followers(self, request):
        """List of all users who are following user."""
        me = request.user.profile
        queryset = self.get_queryset().filter(
            pk__in=Follow.objects.filter(
                following=me, status=Follow.FollowStatus.ACCEPTED
            ).values_list("follower_id", flat=True)
        )

        serializer = ProfileListSerializer(
            queryset, many=True, context=self.get_serializer_context()
        )
        return Response(serializer.data)

    @extend_schema(
        description="List all profiles excluding the current user's profile. "
        "Supports filtering by gender, is_private, location, "
        "and search by first_name, last_name, or email.",
        parameters=[
            OpenApiParameter(
                name="gender",
                description="Filter by gender (Male, Female, Other)",
                type=str,
                enum=["Male", "Female", "Other"],
            ),
            OpenApiParameter(
                name="is_private", description="Filter by privacy status", type=bool
            ),
            OpenApiParameter(
                name="location",
                description="Filter by location (partial match)",
                type=str,
            ),
            OpenApiParameter(
                name="search",
                description="Search by first_name, last_name, or email (starts with)",
                type=str,
            ),
            OpenApiParameter(
                name="page", description="Page number for pagination", type=int
            ),
            OpenApiParameter(
                name="page_size", description="Number of results per page", type=int
            ),
        ],
        responses={200: ProfileListSerializer(many=True)},
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)
