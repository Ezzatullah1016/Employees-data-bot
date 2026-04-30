# Django Healthcare Timesheet Bot

This app uploads healthcare visit sheets (CSV/Excel), groups rows by employee and service date, and exports a clean daily timesheet report.

## Features

- Upload `.csv`, `.xlsx`, or `.xls` files
- Required input columns:
  - `First Name`
  - `Last Name`
  - `Service Date`
  - `Actual Time In`
  - `Actual Time Out`
- Optional: any of `Employee`, `Employee Name`, `employee_name`, etc. (see `HEADER_ALIASES` in `timesheets/services.py`) — if present, that text is used as `employee_name` on the **Employee Hours Summary** sheet instead of rebuilding `Last, First` from the name fields. **Weekly and total hours are always computed from your visit times and dates**, not taken from sample or placeholder data.
- **Employee Hours Summary** week columns use a **Sunday–Saturday** work week. Each column header is the **Sunday date** that starts that week (`YYYY-MM-DD`), e.g. work on Mon 4/20/2026 through Sat 4/25/2026 rolls into the week labeled **2026-04-19**; Mon 4/27/2026 falls in the next week (**2026-04-26**).
- Uses `pandas` to:
  - clean null/missing values
  - parse AM/PM time values
  - group by employee + day
  - compute earliest in, latest out, and total daily hours
- Sorts by employee then service date
- React.js frontend for bot-like experience
- Download formatted Excel output
- Handles invalid files and missing columns with user-friendly errors

## Setup

```powershell
py -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install django pandas openpyxl xlsxwriter
```

## Run

Django’s default port is **8000**. This project is meant to use **2000** so the URL matches the docs.

```powershell
.\.venv\Scripts\python manage.py migrate
.\.venv\Scripts\python manage.py runserver 127.0.0.1:2000
```

Or restart cleanly (frees **2000** and **8000**, then starts on **2000**):

```powershell
.\run-dev.ps1
```

Open [http://127.0.0.1:2000/](http://127.0.0.1:2000/). If the UI looks outdated, use a hard refresh (Ctrl+F5) or a private window.
