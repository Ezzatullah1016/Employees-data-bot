from django.db import models


class ProcessedTimesheet(models.Model):
    class Status(models.TextChoices):
        SUCCESS = "SUCCESS", "Success"
        FAILED = "FAILED", "Failed"

    source_file = models.FileField(upload_to="uploads/")
    output_file = models.FileField(upload_to="outputs/", blank=True, null=True)
    status = models.CharField(max_length=10, choices=Status.choices)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.source_file.name} - {self.status}"
