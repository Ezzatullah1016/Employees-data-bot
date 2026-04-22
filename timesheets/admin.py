from django.contrib import admin
from .models import ProcessedTimesheet


@admin.register(ProcessedTimesheet)
class ProcessedTimesheetAdmin(admin.ModelAdmin):
    list_display = ("id", "source_file", "status", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("source_file", "error_message")
