import pandas as pd
from django.contrib import messages
from django.core.files.base import ContentFile
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt

from .forms import TimesheetUploadForm
from .models import ProcessedTimesheet
from .services import process_timesheet


@require_http_methods(["GET", "POST"])
def upload_timesheet(request):
    form = TimesheetUploadForm(request.POST or None, request.FILES or None)
    preview_rows = []
    summary = None
    processed_id = request.GET.get("processed_id")
    processed = None

    if request.method == "POST" and form.is_valid():
        uploaded_file = form.cleaned_data["file"]

        # Remove any old ProcessedTimesheet with the same file name (avoid caching issues)
        ProcessedTimesheet.objects.filter(source_file=f"uploads/{uploaded_file.name}").delete()

        record = ProcessedTimesheet.objects.create(
            source_file=uploaded_file,
            status=ProcessedTimesheet.Status.FAILED,
        )
        try:
            try:
                uploaded_file.seek(0)
            except Exception:
                pass
            output_df, output_stream = process_timesheet(uploaded_file, filename=uploaded_file.name)
            record.output_file.save(
                f"timesheet_{record.id}.xlsx",
                ContentFile(output_stream.getvalue()),
                save=False,
            )
            record.status = ProcessedTimesheet.Status.SUCCESS
            record.error_message = ""
            record.save()
            return redirect(f"/?processed_id={record.id}")
        except ValueError as exc:
            record.error_message = str(exc)
            record.save()
            messages.error(request, str(exc))
        except Exception:
            record.error_message = "Unexpected error while processing file."
            record.save()
            messages.error(request, "Unexpected error while processing file.")

    if processed_id:
        processed = get_object_or_404(ProcessedTimesheet, pk=processed_id)
        if processed.status == ProcessedTimesheet.Status.SUCCESS and processed.output_file:
            with processed.output_file.open("rb") as result_file:
                output_df = pd.read_excel(result_file)
            preview_df = output_df.rename(
                columns={
                    "Service Date": "service_date",
                    "Earliest Actual Time In": "earliest_time_in",
                    "Latest Actual Time Out": "latest_time_out",
                    "Call Hours Added": "call_hours_added",
                    "Total Hours Worked": "total_hours_worked",
                    "Employee": "employee",
                }
            )
            preview_rows = preview_df.to_dict(orient="records")
            summary = {
                "employees": int(output_df["Employee"].nunique()),
                "days": int(len(output_df)),
                "hours": round(float(output_df["Total Hours Worked"].sum()), 2),
            }
        elif processed.error_message:
            messages.error(request, processed.error_message)

    context = {
        "form": form,
        "preview_rows": preview_rows,
        "summary": summary,
        "processed": processed,
    }
    return render(request, "timesheets/upload.html", context)


def download_processed_file(request, pk):
    record = get_object_or_404(ProcessedTimesheet, pk=pk)
    if record.status != ProcessedTimesheet.Status.SUCCESS or not record.output_file:
        raise Http404("Processed output not found.")

    return FileResponse(
        record.output_file.open("rb"),
        as_attachment=True,
        filename=f"formatted_timesheet_{record.id}.xlsx",
    )


@require_http_methods(["GET"])
def react_app(request):
    return render(request, "timesheets/react_app.html")


@csrf_exempt
@require_http_methods(["POST"])
def process_timesheet_api(request):
    uploaded = request.FILES.get("file")
    if not uploaded:
        return JsonResponse({"ok": False, "error": "Please upload a file."}, status=400)

    record = ProcessedTimesheet.objects.create(
        source_file=uploaded,
        status=ProcessedTimesheet.Status.FAILED,
    )
    try:
        try:
            uploaded.seek(0)
        except Exception:
            pass
        output_df, output_stream = process_timesheet(uploaded, filename=uploaded.name)
        record.output_file.save(
            f"timesheet_{record.id}.xlsx",
            ContentFile(output_stream.getvalue()),
            save=False,
        )
        record.status = ProcessedTimesheet.Status.SUCCESS
        record.error_message = ""
        record.save()

        preview_df = output_df.rename(
            columns={
                "Service Date": "service_date",
                "Earliest Actual Time In": "earliest_time_in",
                "Latest Actual Time Out": "latest_time_out",
                "Call Hours Added": "call_hours_added",
                "Total Hours Worked": "total_hours_worked",
                "Employee": "employee",
            }
        )
        payload = {
            "ok": True,
            "summary": {
                "employees": int(output_df["Employee"].nunique()),
                "days": int(len(output_df)),
                "hours": round(float(output_df["Total Hours Worked"].sum()), 2),
            },
            "preview_rows": preview_df.to_dict(orient="records"),
            "download_url": f"/download/{record.id}/",
        }
        return JsonResponse(payload)
    except ValueError as exc:
        record.error_message = str(exc)
        record.save()
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    except Exception:
        record.error_message = "Unexpected error while processing file."
        record.save()
        return JsonResponse(
            {"ok": False, "error": "Unexpected error while processing file."},
            status=500,
        )
