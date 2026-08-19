from django.utils import timezone
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    def save_user(self, request, sociallogin, form=None):
        user = super().save_user(request, sociallogin, form)
        # New users start unapproved; admins grant access.
        user.is_approved = False
        user.approval_requested_at = timezone.now()
        user.save(update_fields=["is_approved", "approval_requested_at"])
        return user
