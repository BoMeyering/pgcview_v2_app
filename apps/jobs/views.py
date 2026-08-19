import json
import shutil
from pathlib import Path
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from .forms import JobConfigureForm, JobSubmitForm
from .models import Job, JobImage
from .runpod_client import RunPodError, run_full_pipeline, wait_for_ready
from .utils import download_drive_image, get_google_access_token


@login_required
def dashboard(request):
    jobs = Job.objects.filter(user=request.user)
    stats = jobs.aggregate(
        total=Count("id"),
        pending=Count("id", filter=Q(status__in=["pending", "queued"])),
        processing=Count("id", filter=Q(status="processing")),
        completed=Count("id", filter=Q(status="completed")),
        failed=Count("id", filter=Q(status="failed")),
    )
    recent_jobs = jobs[:10]
    return render(request, "jobs/dashboard.html", {
        "stats": stats,
        "recent_jobs": recent_jobs,
    })


@login_required
def job_history(request):
    jobs = Job.objects.filter(user=request.user)
    status_filter = request.GET.get("status", "")
    if status_filter:
        jobs = jobs.filter(status=status_filter)
    return render(request, "jobs/history.html", {
        "jobs": jobs,
        "status_filter": status_filter,
        "status_choices": Job.Status.choices,
    })


@login_required
def job_detail(request, pk):
    job = get_object_or_404(Job, pk=pk, user=request.user)
    return render(request, "jobs/detail.html", {"job": job})


@login_required
def job_submit(request):
    form = JobSubmitForm()
    google_token = get_google_access_token(request.user)
    if request.method == "POST":
        form = JobSubmitForm(request.POST)
        source = request.POST.get("source", "local")
        if form.is_valid():
            job = form.save(commit=False)
            job.user = request.user
            job.source = source
            job.save()

            if source == "local":
                files = request.FILES.getlist("images")
                if not files:
                    job.delete()
                    form.add_error(None, "Please select at least one image file.")
                    return render(request, "jobs/submit.html", {
                        "form": form,
                        "google_token": google_token,
                        "google_api_key": settings.GOOGLE_API_KEY,
                    })
                for f in files:
                    JobImage.objects.create(
                        job=job,
                        image=f,
                        original_filename=f.name,
                    )

            elif source == "google_drive":
                raw = request.POST.get("drive_files", "[]")
                drive_files = json.loads(raw)
                if not drive_files:
                    job.delete()
                    form.add_error(None, "Please select at least one file from Google Drive.")
                    return render(request, "jobs/submit.html", {
                        "form": form,
                        "google_token": google_token,
                        "google_api_key": settings.GOOGLE_API_KEY,
                    })
                for file_info in drive_files:
                    img = JobImage.objects.create(
                        job=job,
                        original_filename=file_info.get("name", "unknown"),
                        drive_file_id=file_info.get("id", ""),
                        drive_thumbnail_url=file_info.get("thumbnailLink", ""),
                    )
                    download_drive_image(img, request.user)

            job.status = Job.Status.QUEUED
            job.save(update_fields=["status", "updated_at"])

            messages.success(request, f'{job.image_count} image(s) uploaded. Configure the job to start processing.')
            return redirect("jobs:configure", pk=job.pk)

    return render(request, "jobs/submit.html", {
        "form": form,
        "google_token": google_token,
        "google_api_key": settings.GOOGLE_API_KEY,
    })


@login_required
def job_configure(request, pk):
    job = get_object_or_404(Job, pk=pk, user=request.user)
    if job.status != Job.Status.QUEUED:
        return redirect("jobs:detail", pk=job.pk)

    form = JobConfigureForm(instance=job)
    if request.method == "POST":
        form = JobConfigureForm(request.POST, instance=job)
        if form.is_valid():
            job = form.save()

            if not wait_for_ready(timeout=120):
                job.status = Job.Status.FAILED
                job.save(update_fields=["status", "updated_at"])
                messages.error(request, "The inference endpoint did not become available in time. Please try again.")
                return redirect("jobs:detail", pk=job.pk)

            job.status = Job.Status.PROCESSING
            job.save(update_fields=["status", "updated_at"])

            any_succeeded = False
            for img in job.images.all():
                img.status = JobImage.Status.PROCESSING
                img.save(update_fields=["status"])
                try:
                    img.image.open("rb")
                    image_bytes = img.image.read()
                    img.image.close()
                    img.result = run_full_pipeline(
                        image_bytes,
                        img_name=img.original_filename,
                        conf=job.conf,
                        marker_type=job.marker_type,
                    )
                    img.status = JobImage.Status.COMPLETED
                    any_succeeded = True
                except RunPodError as e:
                    img.result = {"error": str(e)}
                    img.status = JobImage.Status.FAILED
                img.save(update_fields=["status", "result"])

            job.status = Job.Status.COMPLETED if any_succeeded else Job.Status.FAILED
            job.save(update_fields=["status", "updated_at"])

            messages.success(request, f'Job "{job.name}" submitted with {job.image_count} image(s).')
            return redirect("jobs:detail", pk=job.pk)

    return render(request, "jobs/configure.html", {"form": form, "job": job})


@login_required
@require_POST
def job_warmup(request, pk):
    """Polls the inference endpoint's /ping until it's warm, for the Configure page's status pill."""
    get_object_or_404(Job, pk=pk, user=request.user)
    ready = wait_for_ready(timeout=120)
    return JsonResponse({"ready": ready})


@login_required
@require_POST
def stop_job(request, pk):
    job = get_object_or_404(Job, pk=pk, user=request.user)
    if job.is_stoppable:
        job.status = Job.Status.CANCELLED
        job.save(update_fields=["status", "updated_at"])
        messages.success(request, f'Job "{job.name}" has been stopped.')
    else:
        messages.warning(
            request,
            f'"{job.name}" is already {job.get_status_display().lower()} and cannot be stopped.',
        )
    return redirect(request.POST.get("next") or "jobs:dashboard")


@login_required
@require_POST
def delete_job(request, pk):
    job = get_object_or_404(Job, pk=pk, user=request.user)
    job_name = job.name
    job_dir = Path(settings.MEDIA_ROOT) / "tmp" / str(job.pk)
    if job_dir.exists():
        shutil.rmtree(job_dir)
    job.delete()
    messages.success(request, f'Job "{job_name}" has been permanently deleted.')
    return redirect("jobs:history")


@login_required
@require_GET
def google_token_api(request):
    """Returns the user's current Google OAuth access token for the Drive Picker."""
    token = get_google_access_token(request.user)
    return JsonResponse({
        "token": token,
        "api_key": settings.GOOGLE_API_KEY,
    })
