from django import forms


class MultiFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class TimesheetUploadForm(forms.Form):
    file = forms.FileField(
        label="Timesheet File(s)",
        help_text="Upload one or more .xlsx, .xls, or .csv files with healthcare visit rows.",
        widget=MultiFileInput(attrs={"multiple": True}),
    )
