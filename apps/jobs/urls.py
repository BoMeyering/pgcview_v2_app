from django.urls import path
from . import views

app_name = "jobs"

urlpatterns = [
    path("dashboard/", views.dashboard, name="dashboard"),
    path("jobs/submit/", views.job_submit, name="submit"),
    path("jobs/<uuid:pk>/configure/", views.job_configure, name="configure"),
    path("jobs/<uuid:pk>/warmup/", views.job_warmup, name="warmup"),
    path("jobs/history/", views.job_history, name="history"),
    path("jobs/<uuid:pk>/", views.job_detail, name="detail"),
    path("jobs/<uuid:pk>/stop/", views.stop_job, name="stop"),
    path("jobs/<uuid:pk>/delete/", views.delete_job, name="delete"),
    path("api/google-token/", views.google_token_api, name="google_token_api"),
]
