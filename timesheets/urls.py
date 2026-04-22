from django.urls import path

from .views import download_processed_file, process_timesheet_api, react_app, upload_timesheet

urlpatterns = [
    path("", react_app, name="react_app"),
    path("web/", upload_timesheet, name="upload_timesheet"),
    path("api/process/", process_timesheet_api, name="process_timesheet_api"),
    path("download/<int:pk>/", download_processed_file, name="download_processed_file"),
]
