from django.urls import path
from . import views

app_name = "accounts"

urlpatterns = [
    path("pending/", views.pending_approval, name="pending_approval"),
]
