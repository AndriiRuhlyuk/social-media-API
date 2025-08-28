from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.reverse import reverse
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken, TokenError
from user.permissions import IsAdminOrOwner

from user.models import Profile
from user.serializers import UserSerializer, LogoutSerializer, ProfileSerializer


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def user_api_root(request, format=None):
    return Response(
        {
            "register": reverse("user:create", request=request),
            "token_obtain_pair": reverse("user:token_obtain_pair", request=request),
            "token_refresh": reverse("user:token_refresh", request=request),
            "token_verify": reverse("user:token_verify", request=request),
            "me": reverse("user:manage", request=request),
            "logout": reverse("user:logout", request=request),
            "profile_me": reverse("user:manage_profile", request=request),
        }
    )


class CreateUserView(generics.CreateAPIView):
    permission_classes = (AllowAny,)
    serializer_class = UserSerializer


class ManageUserView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer
    authentication_classes = (JWTAuthentication,)
    permission_classes = (IsAuthenticated,)

    def get_object(self):
        return self.request.user


class LogoutUserView(generics.GenericAPIView):
    """
    Logs out the user by blacklisting the provided refresh token.
    If 'all' is true, blacklists all refresh tokens for the user.
    Requires authentication.
    """

    authentication_classes = (JWTAuthentication,)
    permission_classes = (IsAuthenticated,)
    serializer_class = LogoutSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        refresh = serializer.validated_data["refresh"]
        all_tokens = serializer.validated_data["all_tokens"]

        if all_tokens:
            tokens = OutstandingToken.objects.filter(user=self.request.user)
            if not tokens.exists():
                return Response(
                    {"detail": "No active tokens found for this user"},
                    status=status.HTTP_204_NO_CONTENT,
                )
            for token in tokens:
                try:
                    RefreshToken(token.token).blacklist()
                except TokenError:
                    pass
        else:
            try:
                RefreshToken(refresh).blacklist()
            except TokenError:
                return Response(
                    {"detail": "Failed to blacklist refresh token"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        return Response(
            {"detail": "Successfully logged out"}, status=status.HTTP_204_NO_CONTENT
        )


class ManageProfileView(generics.RetrieveUpdateAPIView):
    """
    Retrieve and update authenticated user's profile.
    GET - view own profile
    PUT/PATCH - update own profile
    """

    serializer_class = ProfileSerializer
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get_object(self):
        """Return current user's profile, create if doesn't exist (for migration period)"""
        try:
            return self.request.user.profile
        except Profile.DoesNotExist:

            profile = Profile.objects.create(
                user=self.request.user,
                is_private=False,
                followers_count=0,
                following_count=0,
                posts_count=0,
            )
            return profile

    def retrieve(self, request, *args, **kwargs):
        """Get user's own profile"""
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def update(self, request, *args, **kwargs):
        """Update user's own profile"""
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)

        return Response(serializer.data)

    @action(
        methods=["POST"],
        detail=True,
        url_path="upload-image",
        permission_classes=[IsAdminOrOwner],
    )
    def upload_image(self, request, pk=None):
        """Endpoint for uploading image to the specific profile"""
        profile = self.get_object()
        serializer = self.get_serializer(profile, data=request.data)

        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
