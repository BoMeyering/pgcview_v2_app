import csv
import json
import shutil
import zipfile
from io import BytesIO
from pathlib import Path
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.db.models import Count, Q
from django.http import Http404, HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.text import slugify
from django.views.decorators.http import require_GET, require_POST

from .forms import JobConfigureForm, JobSubmitForm
from .models import Job, JobImage
from .overlay import CLASS_COLORS_HEX, build_overlay_png
from .runpod_client import RunPodError, run_full_pipeline, wait_for_ready
from .utils import download_drive_image, get_google_access_token

THUMBNAIL_MAX_DIM = 320
MODAL_MAX_DIM = 1600
OVERLAY_CACHE_CONTROL = "private, max-age=86400, immutable"


def _parse_ids_param(request):
    """Returns a list of ints from a comma-separated ?ids= param, or None if absent/invalid."""
    raw = request.GET.get("ids")
    if not raw:
        return None
    try:
        return [int(x) for x in raw.split(",") if x]
    except ValueError:
        return None


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
    overlay_images = [
        {
            "id": img.pk,
            "name": img.original_filename,
            "url": reverse("jobs:image_overlay", args=[img.pk]),
            "class_proportions": (img.result or {}).get("segmentation", {}).get("class_proportions", {}),
        }
        for img in job.images.filter(status=JobImage.Status.COMPLETED)
    ]
    all_image_ids = list(job.images.values_list("pk", flat=True))
    return render(request, "jobs/detail.html", {
        "job": job,
        "overlay_images": overlay_images,
        "all_image_ids": all_image_ids,
        "class_colors": CLASS_COLORS_HEX,
    })


@login_required
def job_detections_csv(request, pk):
    job = get_object_or_404(Job, pk=pk, user=request.user)
    class_names = list(CLASS_COLORS_HEX.keys())

    images = job.images.all()
    ids = _parse_ids_param(request)
    if ids is not None:
        images = images.filter(pk__in=ids)

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{slugify(job.name)}-detections.csv"'

    writer = csv.writer(response)
    writer.writerow(["image_name", "roi_type", "markers_detected", "markers_imputed"] + class_names)

    for img in images:
        result = img.result or {}
        detection = result.get("detection") or {}
        proportions = result.get("segmentation", {}).get("class_proportions", {})
        writer.writerow([
            img.original_filename,
            detection.get("region_type", ""),
            detection.get("num_detections", ""),
            detection.get("num_inferred", ""),
        ] + [proportions.get(name, "") for name in class_names])

    return response


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

            # Set here (not inside the generator below) so SessionMiddleware saves it —
            # once streaming starts, the response has already left process_response.
            messages.success(request, f'Job "{job.name}" submitted with {job.image_count} image(s).')

            def event_stream():
                job.status = Job.Status.PROCESSING
                job.save(update_fields=["status", "updated_at"])

                images = list(job.images.all())
                any_succeeded = False
                for i, img in enumerate(images, start=1):
                    yield f"event: progress\ndata: {json.dumps({'current': i, 'total': len(images), 'filename': img.original_filename})}\n\n"

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
                        try:
                            thumb_bytes = build_overlay_png(img, max_dim=THUMBNAIL_MAX_DIM)
                            img.overlay_thumbnail.save(f"{img.pk}.png", ContentFile(thumb_bytes), save=False)
                        except Exception:
                            pass  # Thumbnail is a nice-to-have; the detail page falls back to on-demand rendering.
                    except RunPodError as e:
                        img.result = {"error": str(e)}
                        img.status = JobImage.Status.FAILED
                    img.save(update_fields=["status", "result", "overlay_thumbnail"])

                job.status = Job.Status.COMPLETED if any_succeeded else Job.Status.FAILED
                job.save(update_fields=["status", "updated_at"])

                yield f"event: done\ndata: {json.dumps({'redirect': reverse('jobs:detail', args=[job.pk])})}\n\n"

            response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
            response["Cache-Control"] = "no-cache"
            response["X-Accel-Buffering"] = "no"
            return response

    return render(request, "jobs/configure.html", {"form": form, "job": job})


@login_required
def job_image_overlay(request, pk):
    img = get_object_or_404(JobImage, pk=pk, job__user=request.user)
    if img.status != JobImage.Status.COMPLETED or not img.result:
        raise Http404
    response = HttpResponse(build_overlay_png(img, max_dim=MODAL_MAX_DIM), content_type="image/png")
    response["Cache-Control"] = OVERLAY_CACHE_CONTROL
    return response


@login_required
def job_images_zip(request, pk):
    """Zips the full-resolution overlay images for the given (or all) completed images."""
    job = get_object_or_404(Job, pk=pk, user=request.user)
    images = job.images.filter(status=JobImage.Status.COMPLETED)
    ids = _parse_ids_param(request)
    if ids is not None:
        images = images.filter(pk__in=ids)

    buf = BytesIO()
    used_names = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for img in images:
            if not img.result:
                continue
            try:
                png_bytes = build_overlay_png(img)
            except Exception:
                continue
            stem = Path(img.original_filename).stem or f"image_{img.pk}"
            name, n = f"{stem}_overlay.png", 1
            while name in used_names:
                name = f"{stem}_overlay_{n}.png"
                n += 1
            used_names.add(name)
            zf.writestr(name, png_bytes)

    if not used_names:
        raise Http404

    response = HttpResponse(buf.getvalue(), content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="{slugify(job.name)}-overlays.zip"'
    return response


@login_required
def job_image_overlay_thumb(request, pk):
    """Fallback for images completed before overlay_thumbnail existed. New images get their
    thumbnail pre-made in job_configure and are served straight from storage instead of hitting this."""
    img = get_object_or_404(JobImage, pk=pk, job__user=request.user)
    if img.status != JobImage.Status.COMPLETED or not img.result:
        raise Http404
    response = HttpResponse(build_overlay_png(img, max_dim=THUMBNAIL_MAX_DIM), content_type="image/png")
    response["Cache-Control"] = OVERLAY_CACHE_CONTROL
    return response


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
