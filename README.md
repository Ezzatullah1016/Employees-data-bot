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

```powershell
.\.venv\Scripts\python manage.py migrate
.\.venv\Scripts\python manage.py runserver
```

Open [http://127.0.0.1:2000](http://127.0.0.1:2000).
