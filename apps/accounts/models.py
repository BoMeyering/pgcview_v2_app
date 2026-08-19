from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    is_approved = models.BooleanField(
        default=False,
        help_text="Account must be approved by an admin before the user can access the application.",
    )
    approval_requested_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-date_joined"]
        verbose_name = "User"
        verbose_name_plural = "Users"

    def __str__(self):
        return self.email or self.username

    @property
    def full_name(self):
        return self.get_full_name() or self.email or self.username

    @property
    def google_picture(self):
        try:
            return self.socialaccount_set.get(provider="google").extra_data.get("picture", "")
        except Exception:
            return ""
