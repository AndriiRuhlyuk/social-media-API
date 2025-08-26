from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken, TokenError

from user.serializers import UserSerializer, LogoutSerializer


class CreateUserView(generics.CreateAPIView):
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
