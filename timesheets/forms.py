from django import forms


class MultiFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class TimesheetUploadForm(forms.Form):
    file = forms.FileField(
        label="Timesheet File(s)",
        help_text=(
            "Upload one or more .xlsx, .xls, or .csv files with healthcare visit rows. "
            "Optional column for the Staff Classification Summary sheet: Employee Classification "
            "(aliases: Employment Type, Staff Classification, Classification, Worker Type, etc.) with values such as "
            "Contractor, Field Staff - Part Time, or Field Staff - Full Time. "
            "Excel reports with title rows (e.g. Associate Productivity) are supported: the bot scans the first rows for "
            "the real header and accepts Associate Name (Last, First), Actual In/Out, and Service."
        ),
        widget=MultiFileInput(attrs={"multiple": True}),
    )
