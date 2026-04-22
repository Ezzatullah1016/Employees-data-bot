from __future__ import annotations

from io import BytesIO
from pathlib import Path
import re

import pandas as pd

REQUIRED_COLUMNS = [
    "First Name",
    "Last Name",
    "Service Date",
    "Actual Time In",
    "Actual Time Out",
]
OPTIONAL_COLUMNS = ["Identifier", "Service Code", "Service Description", "Earnings Code", "Pay Units"]

HEADER_ALIASES = {
    "Identifier": {"identifier", "employee id", "staff id", "clinician id"},
    "First Name": {"first name", "firstname", "first"},
    "Last Name": {"last name", "lastname", "last"},
    "Service Date": {"service date", "date of service", "dos", "date"},
    "Actual Time In": {"actual time in", "time in", "start time", "clock in", "in time"},
    "Actual Time Out": {"actual time out", "time out", "end time", "clock out", "out time"},
    "Service Code": {"service code", "svc code"},
    "Service Description": {"service description", "service desc", "description"},
    "Earnings Code": {"earnings code", "earning code"},
    "Pay Units": {"pay units", "units"},
}
CALL_PAY_CODES = {"PATPC"}


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [str(col).strip() for col in df.columns]
    return df


def _sanitize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text).strip().lower())


def _canonicalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    mapping = {}
    for col in df.columns:
        normalized = _sanitize(col)
        for canonical, aliases in HEADER_ALIASES.items():
            if normalized in aliases:
                mapping[col] = canonical
                break
    renamed = df.rename(columns=mapping)
    missing = [col for col in REQUIRED_COLUMNS if col not in renamed.columns]
    if missing:
        raise ValueError(
            "Missing required columns: First Name, Last Name, Service Date, Actual Time In, Actual Time Out"
        )
    return renamed


def _read_source_file(file_obj, filename: str) -> pd.DataFrame:
    extension = Path(filename).suffix.lower()
    if extension == ".csv":
        return pd.read_csv(file_obj, sep=None, engine="python", dtype_backend="numpy_nullable")
    if extension in {".xlsx", ".xls"}:
        return pd.read_excel(file_obj, dtype_backend="numpy_nullable")
    raise ValueError("Unsupported file format. Please upload .xlsx, .xls, or .csv.")


def _parse_time_column(series: pd.Series) -> pd.Series:
    values = series.copy()
    numeric = pd.to_numeric(values, errors="coerce")
    numeric_mask = numeric.notna()
    if numeric_mask.any():
        converted = pd.to_timedelta(numeric.loc[numeric_mask], unit="D")
        values.loc[numeric_mask] = (pd.Timestamp("1970-01-01") + converted).dt.strftime("%I:%M %p")

    values = values.astype(str).str.strip()
    values = values.where(values.ne(""), None)
    parsed = pd.to_datetime(values, format="%I:%M %p", errors="coerce")
    fallback_mask = parsed.isna() & values.notna()
    if fallback_mask.any():
        parsed.loc[fallback_mask] = pd.to_datetime(
            values.loc[fallback_mask], format="%H:%M", errors="coerce"
        )
    second_fallback = parsed.isna() & values.notna()
    if second_fallback.any():
        parsed.loc[second_fallback] = pd.to_datetime(values.loc[second_fallback], errors="coerce")
    return parsed.dt.time


def process_timesheet(file_obj, filename: str | None = None) -> tuple[pd.DataFrame, BytesIO]:
    source_name = filename or getattr(file_obj, "name", "")
    try:
        raw = _read_source_file(file_obj, source_name)
    except Exception as exc:  # pragma: no cover - broad guard for bad files
        raise ValueError(
            "Could not read the file. Please upload a valid .xlsx, .xls, or .csv."
        ) from exc

    raw = _canonicalize_columns(_normalize_columns(raw))
    selected_columns = [*REQUIRED_COLUMNS, *[c for c in OPTIONAL_COLUMNS if c in raw.columns]]
    df = raw[selected_columns].copy()
    df["First Name"] = df["First Name"].astype(str).str.strip()
    df["Last Name"] = df["Last Name"].astype(str).str.strip()
    df["Service Date"] = pd.to_datetime(df["Service Date"], errors="coerce", dayfirst=False).dt.date
    df["Actual Time In"] = _parse_time_column(df["Actual Time In"])
    df["Actual Time Out"] = _parse_time_column(df["Actual Time Out"])

    df = df.replace({"First Name": {"nan": None}, "Last Name": {"nan": None}})
    df = df.dropna(subset=["First Name", "Last Name", "Service Date"])

    if df.empty:
        raise ValueError("No valid rows found after cleaning. Check missing dates or times.")

    if "Identifier" in df.columns:
        df["Identifier"] = df["Identifier"].astype(str).str.strip()
        df["Identifier"] = df["Identifier"].replace({"nan": ""})
    else:
        df["Identifier"] = ""

    if "Service Code" in df.columns:
        df["Service Code"] = df["Service Code"].astype(str).str.strip().str.upper()
        df["Service Code"] = df["Service Code"].replace({"NAN": ""})
    else:
        df["Service Code"] = ""

    if "Earnings Code" in df.columns:
        df["Earnings Code"] = df["Earnings Code"].astype(str).str.strip().str.upper()
        df["Earnings Code"] = df["Earnings Code"].replace({"NAN": ""})
    else:
        df["Earnings Code"] = ""

    if "Service Description" in df.columns:
        df["Service Description"] = df["Service Description"].astype(str).str.strip().str.lower()
        df["Service Description"] = df["Service Description"].replace({"nan": ""})
    else:
        df["Service Description"] = ""

    if "Pay Units" in df.columns:
        df["Pay Units"] = pd.to_numeric(df["Pay Units"], errors="coerce")
    else:
        df["Pay Units"] = pd.NA

    df["Employee"] = df["Last Name"] + ", " + df["First Name"]
    df["Employee Label"] = df["Employee"]
    identifier_mask = df["Identifier"].ne("")
    df.loc[identifier_mask, "Employee Label"] = (
        df.loc[identifier_mask, "Employee"] + " (" + df.loc[identifier_mask, "Identifier"] + ")"
    )

    call_mask = (
        df["Service Code"].isin(CALL_PAY_CODES)
        | df["Earnings Code"].isin(CALL_PAY_CODES)
        | df["Service Description"].str.contains("patient phone call", regex=False)
    )
    df["Call Hours Added"] = 0.0
    df.loc[call_mask, "Call Hours Added"] = (df.loc[call_mask, "Pay Units"].fillna(0) * 1.0).astype(float)

    df["Time In DT"] = pd.to_datetime(
        df["Service Date"].astype(str) + " " + df["Actual Time In"].astype(str),
        errors="coerce",
    )
    df["Time Out DT"] = pd.to_datetime(
        df["Service Date"].astype(str) + " " + df["Actual Time Out"].astype(str),
        errors="coerce",
    )
    call_hours = (
        df.groupby(["Employee", "Identifier", "Employee Label", "Service Date"], as_index=False)
        .agg(Call_Hours_Added=("Call Hours Added", "sum"))
    )

    visit_df = df.loc[~call_mask].copy()
    visit_df = visit_df.dropna(subset=["Time In DT", "Time Out DT"])

    overnight_mask = visit_df["Time Out DT"] < visit_df["Time In DT"]
    visit_df.loc[overnight_mask, "Time Out DT"] = visit_df.loc[overnight_mask, "Time Out DT"] + pd.Timedelta(
        days=1
    )

    visit_grouped = (
        visit_df.groupby(["Employee", "Identifier", "Employee Label", "Service Date"], as_index=False)
        .agg(Earliest_Time_In=("Time In DT", "min"), Latest_Time_Out=("Time Out DT", "max"))
    )
    grouped = visit_grouped.merge(
        call_hours,
        on=["Employee", "Identifier", "Employee Label", "Service Date"],
        how="outer",
    )
    grouped["Call_Hours_Added"] = grouped["Call_Hours_Added"].fillna(0.0)
    grouped["Visit Span Hours"] = (
        grouped["Latest_Time_Out"] - grouped["Earliest_Time_In"]
    ).dt.total_seconds() / 3600
    grouped["Visit Span Hours"] = grouped["Visit Span Hours"].fillna(0.0)
    grouped["Total Hours Worked"] = grouped["Visit Span Hours"] + grouped["Call_Hours_Added"]
    grouped = grouped.sort_values(["Employee", "Service Date"])


    # Calculate total number of weeks per employee
    grouped["Year"] = pd.to_datetime(grouped["Service Date"]).dt.isocalendar().year
    grouped["Week"] = pd.to_datetime(grouped["Service Date"]).dt.isocalendar().week
    week_rows = grouped[["Employee", "Year", "Week"]].drop_duplicates()
    employee_weeks = week_rows.groupby("Employee").size().to_dict()

    # Map employee to total weeks for column
    grouped["Total Weeks"] = grouped["Employee"].map(employee_weeks)
    output = pd.DataFrame(
        {
            "Employee": grouped["Employee Label"],
            "Service Date": pd.to_datetime(grouped["Service Date"]).dt.strftime("%m/%d/%Y"),
            "Earliest Actual Time In": grouped["Earliest_Time_In"].dt.strftime("%I:%M %p").fillna(""),
            "Latest Actual Time Out": grouped["Latest_Time_Out"].dt.strftime("%I:%M %p").fillna(""),
            "Call Hours Added": grouped["Call_Hours_Added"].round(2),
            "Total Hours Worked": grouped["Total Hours Worked"].round(2),
            "Total Weeks": grouped["Total Weeks"],
        }
    )

    summary = {
        "Employees": int(grouped["Employee"].nunique()),
        "Employee-Day Records": int(len(output)),
        "Total Hours": round(float(output["Total Hours Worked"].sum()), 2),
        "Employee Weeks": employee_weeks,
    }

    # Build a printable report with per-employee totals and a final grand total row.
    report_rows: list[dict[str, str | float]] = []
    for employee_key, employee_group in grouped.groupby("Employee", sort=False):
        employee_label = employee_group["Employee Label"].iloc[0]
        total_weeks = employee_weeks.get(employee_key, 0)
        for _, row in employee_group.iterrows():
            report_rows.append(
                {
                    "Employee": employee_label,
                    "Service Date": pd.to_datetime(row["Service Date"]).strftime("%m/%d/%Y"),
                    "Earliest Actual Time In": (
                        row["Earliest_Time_In"].strftime("%I:%M %p")
                        if pd.notna(row["Earliest_Time_In"])
                        else ""
                    ),
                    "Latest Actual Time Out": (
                        row["Latest_Time_Out"].strftime("%I:%M %p")
                        if pd.notna(row["Latest_Time_Out"])
                        else ""
                    ),
                    "Call Hours Added": round(float(row["Call_Hours_Added"]), 2),
                    "Total Hours Worked": round(float(row["Total Hours Worked"]), 2),
                    "Total Weeks": total_weeks,
                }
            )
        report_rows.append(
            {
                "Employee": f"Grand Total ({employee_label})",
                "Service Date": "",
                "Earliest Actual Time In": "",
                "Latest Actual Time Out": "",
                "Call Hours Added": round(
                    float(grouped.loc[grouped["Employee"] == employee_key, "Call_Hours_Added"].sum()),
                    2,
                ),
                "Total Hours Worked": round(
                    float(grouped.loc[grouped["Employee"] == employee_key, "Total Hours Worked"].sum()),
                    2,
                ),
                "Total Weeks": total_weeks,
            }
        )

    report_rows.append(
        {
            "Employee": "OVERALL GRAND TOTAL",
            "Service Date": "",
            "Earliest Actual Time In": "",
            "Latest Actual Time Out": "",
            "Call Hours Added": round(float(grouped["Call_Hours_Added"].sum()), 2),
            "Total Hours Worked": summary["Total Hours"],
            "Total Weeks": "",
        }
    )
    formatted_output = pd.DataFrame(report_rows)

    excel_stream = BytesIO()
    with pd.ExcelWriter(excel_stream, engine="xlsxwriter") as writer:
        formatted_output.to_excel(writer, index=False, sheet_name="Timesheet")
        sheet = writer.sheets["Timesheet"]
        book = writer.book

        header_fmt = book.add_format(
            {"bold": True, "font_color": "white", "bg_color": "#1F4E78", "align": "center", "border": 1}
        )
        data_fmt = book.add_format({"border": 1})
        total_row_fmt = book.add_format({"bold": True, "bg_color": "#E2F0D9", "border": 1})
        grand_total_fmt = book.add_format({"bold": True, "bg_color": "#FFE699", "border": 1})
        hours_fmt = book.add_format({"border": 1, "num_format": "0.00"})
        total_hours_fmt = book.add_format({"bold": True, "bg_color": "#E2F0D9", "border": 1, "num_format": "0.00"})
        grand_hours_fmt = book.add_format({"bold": True, "bg_color": "#FFE699", "border": 1, "num_format": "0.00"})

        for col_idx, column_name in enumerate(formatted_output.columns):
            sheet.write(0, col_idx, column_name, header_fmt)

        for row_idx, row in enumerate(report_rows, start=1):
            is_overall_total = row["Employee"] == "OVERALL GRAND TOTAL"
            is_employee_total = str(row["Employee"]).startswith("Grand Total (")
            base_fmt = grand_total_fmt if is_overall_total else total_row_fmt if is_employee_total else data_fmt
            hour_cell_fmt = grand_hours_fmt if is_overall_total else total_hours_fmt if is_employee_total else hours_fmt

            sheet.write(row_idx, 0, row["Employee"], base_fmt)
            sheet.write(row_idx, 1, row["Service Date"], base_fmt)
            sheet.write(row_idx, 2, row["Earliest Actual Time In"], base_fmt)
            sheet.write(row_idx, 3, row["Latest Actual Time Out"], base_fmt)
            sheet.write_number(row_idx, 4, float(row["Call Hours Added"]), hour_cell_fmt)
            sheet.write_number(row_idx, 5, float(row["Total Hours Worked"]), hour_cell_fmt)

        sheet.set_column("A:A", 34)
        sheet.set_column("B:D", 20)
        sheet.set_column("E:F", 20)
        sheet.freeze_panes(1, 0)
        sheet.autofilter(0, 0, len(report_rows), len(formatted_output.columns) - 1)

        summary_sheet = writer.book.add_worksheet("Summary")
        summary_header_fmt = writer.book.add_format({"bold": True, "bg_color": "#E8EEF9", "border": 1})
        label_fmt = writer.book.add_format({"bold": True, "border": 1})
        value_fmt = writer.book.add_format({"border": 1})
        summary_hours_fmt = writer.book.add_format({"border": 1, "num_format": "0.00"})

        summary_sheet.write("A1", "Metric", summary_header_fmt)
        summary_sheet.write("B1", "Value", header_fmt)
        summary_sheet.write("A2", "Employees", label_fmt)
        summary_sheet.write_number("B2", summary["Employees"], value_fmt)
        summary_sheet.write("A3", "Employee-Day Records", label_fmt)
        summary_sheet.write_number("B3", summary["Employee-Day Records"], value_fmt)
        summary_sheet.write("A4", "Total Hours", label_fmt)
        summary_sheet.write_number("B4", summary["Total Hours"], summary_hours_fmt)

        summary_sheet.set_column("A:A", 24)
        summary_sheet.set_column("B:B", 16)

        # Add a dedicated 'Employee Weeks' tab
        weeks_sheet = writer.book.add_worksheet("Employee Weeks")
        weeks_header_fmt = writer.book.add_format({"bold": True, "bg_color": "#1F4E78", "font_color": "white", "align": "center", "border": 1})
        weeks_label_fmt = writer.book.add_format({"border": 1})
        weeks_value_fmt = writer.book.add_format({"border": 1, "num_format": "0"})

        weeks_sheet.write(0, 0, "Employee", weeks_header_fmt)
        weeks_sheet.write(0, 1, "Total Weeks", weeks_header_fmt)
        for idx, (emp, weeks) in enumerate(summary["Employee Weeks"].items(), start=1):
            weeks_sheet.write(idx, 0, emp, weeks_label_fmt)
            weeks_sheet.write_number(idx, 1, weeks, weeks_value_fmt)
        weeks_sheet.set_column("A:A", 34)
        weeks_sheet.set_column("B:B", 16)
    excel_stream.seek(0)

    return output, excel_stream
