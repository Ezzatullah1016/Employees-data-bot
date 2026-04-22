from django import forms


class TimesheetUploadForm(forms.Form):
    file = forms.FileField(
        label="Timesheet File",
        help_text="Upload .xlsx, .xls, or .csv with healthcare visit rows.",
    )

    def clean_file(self):
        uploaded = self.cleaned_data["file"]
        allowed = (".xlsx", ".xls", ".csv")
        if not uploaded.name.lower().endswith(allowed):
            raise forms.ValidationError("Please upload a valid file (.xlsx, .xls, or .csv).")
        return uploaded
