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
OPTIONAL_COLUMNS = [
    "Identifier",
    "Employee Name",
    "Employee Classification",
    "Service Code",
    "Service Description",
    "Earnings Code",
    "Pay Units",
    "Travel Miles",
    "Week",
]

HEADER_ALIASES = {
    "Identifier": {"identifier", "employee id", "staff id", "clinician id"},
    "Employee Name": {
        "employee name",
        "employee",
        "employee_name",
        "resource",
        "resource name",
        "clinician name",
        "caregiver",
        "caregiver name",
    },
    "First Name": {"first name", "firstname", "first", "given name", "f name", "fname"},
    "Last Name": {"last name", "lastname", "last", "surname", "family name", "l name", "lname"},
    "Service Date": {
        "service date",
        "date of service",
        "dos",
        "date",
        "svc date",
        "visit date",
        "appointment date",
        "date of svc",
    },
    "Actual Time In": {
        "actual time in",
        "actual in",
        "time in",
        "start time",
        "clock in",
        "in time",
        "clock-in",
        "time-in",
    },
    "Actual Time Out": {
        "actual time out",
        "actual out",
        "time out",
        "end time",
        "clock out",
        "out time",
        "clock-out",
        "time-out",
    },
    "Service Code": {"service code", "svc code"},
    "Service Description": {"service description", "service desc", "description", "service"},
    "Earnings Code": {"earnings code", "earning code"},
    "Pay Units": {"pay units", "units"},
    "Travel Miles": {"travel miles", "miles", "mileage", "travel mileage"},
    "Employee Classification": {
        "employee classification",
        "staff classification",
        "employment type",
        "employee type",
        "worker type",
        "job classification",
        "payroll classification",
        "classification",
    },
    "Week": {"week", "payroll week", "week ending", "week range"},
}
CLASSIFICATION_SHEET_NAME = "Staff Classification Summary"
_IV_SERVICE_RE = re.compile(r"\biv\b", re.IGNORECASE)
CLASSIFICATION_BUCKETS_ORDER: tuple[str, ...] = (
    "Contractors",
    "Field Staff - Part Time",
    "Field Staff - Full Time",
    "Unclassified",
)
ADDED_HOURS_CODES = {"PATPC", "TRAVL"}
_EMPLOYEE_LABEL_ID = re.compile(r"^(.*) \(([^)]+)\)$")


def _split_employee_label(label: str) -> tuple[str, str]:
    m = _EMPLOYEE_LABEL_ID.match(str(label).strip())
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return str(label).strip(), ""


def _first_non_empty_in_group(values: pd.Series) -> str:
    for v in values:
        s = str(v).strip()
        if s and s.lower() != "nan":
            return s
    return ""


def _sunday_week_column_label(service_date) -> pd.Series:
    """Label each row with the Sunday date (YYYY-MM-DD) that starts its work week (Sun–Sat)."""
    ts = pd.to_datetime(service_date).dt.normalize()
    # pandas: Monday=0 … Sunday=6. Days to subtract to reach the Sunday that begins this week.
    offset = (ts.dt.weekday + 1) % 7
    week_start = ts - pd.to_timedelta(offset, unit="D")
    return week_start.dt.strftime("%Y-%m-%d")


def _parse_sunday_week_column(label: str) -> tuple[int, int, int]:
    """Sort key for week columns stored as Sunday dates YYYY-MM-DD."""
    try:
        d = pd.Timestamp(str(label).strip())
        return (int(d.year), int(d.month), int(d.day))
    except Exception:
        return (0, 0, 0)


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [str(col).strip().lstrip("\ufeff") for col in df.columns]
    return df


def _sanitize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text).strip().lower())


def _normalize_employee_classification(raw: object) -> str:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return "Unclassified"
    text = str(raw).strip()
    if not text or text.lower() == "nan":
        return "Unclassified"
    for ch in ("\u2013", "\u2014", "\u2212"):
        text = text.replace(ch, "-")
    s = _sanitize(text)
    if "contract" in s or "1099" in s or "independent contractor" in s:
        return "Contractors"
    if "field staff" in s:
        if "part" in s:
            return "Field Staff - Part Time"
        if "full" in s:
            return "Field Staff - Full Time"
    if "part" in s and "time" in s:
        return "Field Staff - Part Time"
    if "full" in s and "time" in s:
        return "Field Staff - Full Time"
    return "Unclassified"


def _is_iv_visit_service(service_display: str, service_code: str = "") -> bool:
    desc = str(service_display or "").strip()
    code = str(service_code or "").strip().upper()
    if code == "IV":
        return True
    if not desc or desc.lower() in {"nan", "(no service)"}:
        return False
    return bool(_IV_SERVICE_RE.search(desc))


def _classification_mode_for_series(values: pd.Series) -> str:
    series = pd.Series(values).dropna()
    if series.empty:
        return "Unclassified"
    vc = series.value_counts()
    max_ct = int(vc.max())
    top = vc[vc == max_ct]
    if len(top) > 1:
        return "Unclassified"
    return str(top.index[0])


def _build_classification_frame(df: pd.DataFrame) -> pd.DataFrame:
    call_mask = (
        df["Service Code"].isin(ADDED_HOURS_CODES)
        | df["Earnings Code"].isin(ADDED_HOURS_CODES)
        | df["Service Description"].str.contains("patient phone call", regex=False)
        | df["Service Description"].str.contains("over 30 minute travel time", regex=False)
    )
    svc_desc = df["Service Description"].fillna("").astype(str).str.strip()
    svc_code = df["Service Code"].fillna("").astype(str).str.strip()
    display = svc_desc.where(svc_desc.ne("") & svc_desc.str.lower().ne("nan"), "")
    empty_disp = display.eq("") | display.str.lower().eq("nan")
    display = display.mask(empty_disp, svc_code)
    empty_disp2 = display.eq("") | display.str.lower().eq("nan")
    display = display.mask(empty_disp2, "(no service)")

    row_cls = (
        df["Employee Classification"].fillna("").astype(str).str.strip().replace({"nan": ""}).map(_normalize_employee_classification)
    )
    tmp = df[["Source File", "Employee Label"]].copy()
    tmp["_row_bucket"] = row_cls
    employee_bucket = tmp.groupby(["Source File", "Employee Label"], sort=False)["_row_bucket"].transform(
        _classification_mode_for_series
    )

    row_hours = pd.Series(0.0, index=df.index, dtype="float64")
    row_hours.loc[call_mask] = df.loc[call_mask, "Pay Units"].fillna(0).astype(float)
    non_call = ~call_mask
    tin = df["Time In DT"]
    tout = df["Time Out DT"]
    valid = non_call & tin.notna() & tout.notna()
    tout_adj = tout.copy()
    late = valid & (tout < tin)
    tout_adj.loc[late] = tout_adj.loc[late] + pd.Timedelta(days=1)
    span_hours = (tout_adj - tin).dt.total_seconds() / 3600.0
    row_hours.loc[valid] = span_hours.loc[valid].fillna(0.0).astype(float)

    svc_dates = pd.to_datetime(df["Service Date"], errors="coerce")
    week_from_date = _sunday_week_column_label(svc_dates)
    if "Week" in df.columns:
        week_raw = df["Week"].fillna("").astype(str).str.strip().replace({"nan": "", "NaT": "", "<NA>": ""})
        week_label = week_raw.where(week_raw.ne(""), week_from_date)
    else:
        week_label = week_from_date

    return pd.DataFrame(
        {
            "source_file": df["Source File"].astype(str),
            "employee_label": df["Employee Label"].astype(str),
            "employee_bucket": employee_bucket.astype(str),
            "service_display": display.astype(str),
            "service_code": svc_code.astype(str),
            "week_label": week_label.astype(str),
            "row_hours": row_hours.astype(float),
            "travel_miles": pd.to_numeric(df["Travel Miles"], errors="coerce").fillna(0.0).astype(float),
        }
    )


def _write_employee_service_tally_block(
    sheet,
    sub: pd.DataFrame,
    r: int,
    *,
    subsection_fmt,
    header_fmt,
    text_fmt,
    num_fmt,
    include_hours: bool = True,
    include_miles: bool = True,
) -> int:
    """Per-employee service lines (one row per visit reason); optional hours and miles."""
    r += 1
    sheet.write(r, 0, "Service line count by employee", subsection_fmt)
    r += 1
    sheet.write(r, 0, "Source File", header_fmt)
    sheet.write(r, 1, "Employee", header_fmt)
    sheet.write(r, 2, "Service", header_fmt)
    sheet.write(r, 3, "Line count", header_fmt)
    col = 4
    if include_hours:
        sheet.write(r, col, "Total hours", header_fmt)
        col += 1
    if include_miles:
        sheet.write(r, col, "Miles", header_fmt)
    r += 1
    if sub.empty:
        sheet.write(r, 0, "(no rows in this classification)", text_fmt)
        return r + 1
    by_emp = (
        sub.groupby(["source_file", "employee_label", "service_display"], sort=False)
        .agg(
            line_count=("service_display", "size"),
            total_hours=("row_hours", "sum"),
            miles=("travel_miles", "sum"),
        )
        .reset_index()
    )
    by_emp = by_emp.sort_values(["source_file", "employee_label", "service_display"], kind="stable")
    for _, er in by_emp.iterrows():
        sheet.write_string(r, 0, str(er["source_file"]), text_fmt)
        sheet.write_string(r, 1, str(er["employee_label"]), text_fmt)
        sheet.write_string(r, 2, str(er["service_display"]), text_fmt)
        sheet.write_number(r, 3, int(er["line_count"]), num_fmt)
        c = 4
        if include_hours:
            sheet.write_number(r, c, round(float(er["total_hours"]), 2), num_fmt)
            c += 1
        if include_miles:
            sheet.write_number(r, c, round(float(er["miles"]), 2), num_fmt)
        r += 1
    return r


def _write_ft_iv_visits_by_week_block(
    sheet,
    sub: pd.DataFrame,
    r: int,
    *,
    subsection_fmt,
    header_fmt,
    text_fmt,
    num_fmt,
) -> int:
    """Full-time staff with IV visit reason, grouped by week; hours are IV lines only."""
    r += 1
    sheet.write(r, 0, "IV visits by week (full-time staff)", subsection_fmt)
    r += 1
    sheet.write(r, 0, "Source File", header_fmt)
    sheet.write(r, 1, "Employee", header_fmt)
    sheet.write(r, 2, "Week", header_fmt)
    sheet.write(r, 3, "IV line count", header_fmt)
    sheet.write(r, 4, "Total IV hours", header_fmt)
    r += 1
    iv_mask = sub["service_display"].map(lambda s: _is_iv_visit_service(str(s)))
    if "service_code" in sub.columns:
        iv_mask = iv_mask | sub["service_code"].fillna("").astype(str).str.strip().str.upper().eq("IV")
    iv_sub = sub.loc[iv_mask].copy()
    if iv_sub.empty:
        sheet.write(r, 0, "(no IV visit rows for full-time staff)", text_fmt)
        return r + 1
    by_week = (
        iv_sub.groupby(["source_file", "employee_label", "week_label"], sort=False)
        .agg(
            line_count=("service_display", "size"),
            total_iv_hours=("row_hours", "sum"),
        )
        .reset_index()
    )
    by_week = by_week.sort_values(["source_file", "employee_label", "week_label"], kind="stable")
    for _, er in by_week.iterrows():
        sheet.write_string(r, 0, str(er["source_file"]), text_fmt)
        sheet.write_string(r, 1, str(er["employee_label"]), text_fmt)
        sheet.write_string(r, 2, str(er["week_label"]), text_fmt)
        sheet.write_number(r, 3, int(er["line_count"]), num_fmt)
        sheet.write_number(r, 4, round(float(er["total_iv_hours"]), 2), num_fmt)
        r += 1
    return r


def _write_classification_summary_sheet(
    book,
    sheet,
    class_df: pd.DataFrame,
    *,
    section_title_fmt,
    subsection_fmt,
    header_fmt,
    text_fmt,
    num_fmt,
) -> None:
    r = 0
    for bucket in CLASSIFICATION_BUCKETS_ORDER:
        sub = class_df.loc[class_df["employee_bucket"] == bucket].copy()
        sheet.merge_range(r, 0, r, 4, bucket, section_title_fmt)
        r += 1

        if bucket in ("Contractors", "Field Staff - Part Time"):
            r = _write_employee_service_tally_block(
                sheet,
                sub,
                r,
                subsection_fmt=subsection_fmt,
                header_fmt=header_fmt,
                text_fmt=text_fmt,
                num_fmt=num_fmt,
                include_hours=True,
                include_miles=True,
            )
            if not sub.empty and float(sub["travel_miles"].sum()) > 0:
                r += 1
                sheet.write(r, 0, "Total miles (section)", subsection_fmt)
                sheet.write_number(r, 1, round(float(sub["travel_miles"].sum()), 2), num_fmt)
                r += 1

        elif bucket == "Field Staff - Full Time":
            r = _write_ft_iv_visits_by_week_block(
                sheet,
                sub,
                r,
                subsection_fmt=subsection_fmt,
                header_fmt=header_fmt,
                text_fmt=text_fmt,
                num_fmt=num_fmt,
            )

        else:
            r = _write_employee_service_tally_block(
                sheet,
                sub,
                r,
                subsection_fmt=subsection_fmt,
                header_fmt=header_fmt,
                text_fmt=text_fmt,
                num_fmt=num_fmt,
                include_hours=True,
                include_miles=False,
            )

        r += 2

    sheet.set_column(0, 0, 36)
    sheet.set_column(1, 1, 40)
    sheet.set_column(2, 2, 28)
    sheet.set_column(3, 3, 14)
    sheet.set_column(4, 4, 14)


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
        seen = [str(c) for c in renamed.columns[:35]]
        suffix = " …" if len(renamed.columns) > 35 else ""
        raise ValueError(
            "Could not find these required columns: "
            + ", ".join(missing)
            + ". Columns detected in the file: "
            + ", ".join(seen)
            + suffix
            + ". Save as CSV UTF-8 or Excel with a header row that includes first/last name, service date, and clock in/out."
        )
    return renamed


_EXCEL_HEADER_PROBE_MAX = 30


def _preprocess_productivity_style_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Split 'Associate Name' (Last, First) into First/Last when those columns are not both present."""
    out = df.copy()
    key_to_col = {_sanitize(str(c)): str(c) for c in out.columns}
    has_first = "first name" in key_to_col
    has_last = "last name" in key_to_col
    if "associate name" not in key_to_col or (has_first and has_last):
        return out
    acol = key_to_col["associate name"]
    combined = out[acol].fillna("").astype(str).str.strip()
    combined = combined.replace({"nan": "", "NaT": "", "<NA>": ""})
    parts = combined.str.split(",", n=1, expand=True)
    out["Last Name"] = parts[0].fillna("").astype(str).str.strip()
    if parts.shape[1] > 1:
        out["First Name"] = parts[1].fillna("").astype(str).str.strip()
    else:
        out["First Name"] = ""
    out["Employee Name"] = combined
    return out.drop(columns=[acol])


def _probe_excel_header_row(file_obj) -> int:
    """Find 0-based header row for Excel files with leading title rows (e.g. Associate Productivity)."""
    last_err: Exception | None = None
    for header_row in range(_EXCEL_HEADER_PROBE_MAX):
        file_obj.seek(0)
        try:
            df = pd.read_excel(file_obj, header=header_row, dtype_backend="numpy_nullable")
        except Exception as exc:
            last_err = exc
            continue
        if df.empty or df.shape[1] < 3:
            continue
        df = _normalize_columns(df.copy())
        df = _preprocess_productivity_style_columns(df)
        try:
            _canonicalize_columns(df)
        except ValueError as exc:
            last_err = exc
            continue
        return header_row
    base = (
        "Could not find a header row with required timesheet columns in the first "
        f"{_EXCEL_HEADER_PROBE_MAX} rows of the Excel file."
    )
    if last_err:
        raise ValueError(base + " " + str(last_err)) from last_err
    raise ValueError(base)


def _read_excel_file(file_obj) -> pd.DataFrame:
    header_row = _probe_excel_header_row(file_obj)
    file_obj.seek(0)
    return pd.read_excel(file_obj, header=header_row, dtype_backend="numpy_nullable")


def _read_csv_bytes(raw_bytes: bytes) -> pd.DataFrame:
    """Read CSV/TSV bytes with UTF-8 BOM and Windows encodings; retry tab if sniffer yields a single column."""
    last_decode_error: UnicodeDecodeError | None = None
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            header_line = raw_bytes.split(b"\n", 1)[0].decode(encoding, errors="strict")
        except UnicodeDecodeError as exc:
            last_decode_error = exc
            continue
        bio = BytesIO(raw_bytes)
        df = pd.read_csv(bio, sep=None, engine="python", dtype_backend="numpy_nullable", encoding=encoding)
        if len(df.columns) <= 1 and "\t" in header_line and header_line.count("\t") >= 3:
            bio = BytesIO(raw_bytes)
            df = pd.read_csv(bio, sep="\t", dtype_backend="numpy_nullable", encoding=encoding)
        return df
    raise last_decode_error or UnicodeDecodeError("utf-8", b"", 0, 1, "Unable to decode file")


def _read_source_file(file_obj, filename: str) -> pd.DataFrame:
    extension = Path(filename).suffix.lower()
    if extension == ".csv":
        file_obj.seek(0)
        raw_bytes = file_obj.read()
        return _read_csv_bytes(raw_bytes)
    if extension in {".xlsx", ".xls"}:
        file_obj.seek(0)
        return _read_excel_file(file_obj)
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


def _prepare_clean_rows(file_obj, filename: str | None = None) -> pd.DataFrame:
    source_name = filename or getattr(file_obj, "name", "")
    try:
        raw = _read_source_file(file_obj, source_name)
    except Exception as exc:  # pragma: no cover - broad guard for bad files
        raise ValueError(
            "Could not read the file. Please upload a valid .xlsx, .xls, or .csv."
        ) from exc

    raw = _canonicalize_columns(_preprocess_productivity_style_columns(_normalize_columns(raw)))
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

    if "Travel Miles" in df.columns:
        df["Travel Miles"] = pd.to_numeric(df["Travel Miles"], errors="coerce").fillna(0.0)
    else:
        df["Travel Miles"] = 0.0

    if "Employee Name" in df.columns:
        df["Employee Name"] = df["Employee Name"].astype(str).str.strip()
        df["Employee Name"] = df["Employee Name"].replace({"nan": ""})
    else:
        df["Employee Name"] = ""
    if "Employee Classification" in df.columns:
        df["Employee Classification"] = df["Employee Classification"].astype(str).str.strip()
        df["Employee Classification"] = df["Employee Classification"].replace({"nan": ""})
    else:
        df["Employee Classification"] = ""
    if "Week" in df.columns:
        df["Week"] = df["Week"].astype(str).str.strip()
        df["Week"] = df["Week"].replace({"nan": ""})
    df["Source File"] = Path(source_name).name if source_name else "uploaded_file"
    return df


def _build_timesheet_output(df: pd.DataFrame) -> tuple[pd.DataFrame, BytesIO]:
    if df.empty:
        raise ValueError("No valid rows found after cleaning. Check missing dates or times.")

    df["Employee"] = df["Last Name"] + ", " + df["First Name"]
    df["Employee Label"] = df["Employee"]
    identifier_mask = df["Identifier"].ne("")
    df.loc[identifier_mask, "Employee Label"] = (
        df.loc[identifier_mask, "Employee"] + " (" + df.loc[identifier_mask, "Identifier"] + ")"
    )

    call_mask = (
        df["Service Code"].isin(ADDED_HOURS_CODES)
        | df["Earnings Code"].isin(ADDED_HOURS_CODES)
        | df["Service Description"].str.contains("patient phone call", regex=False)
        | df["Service Description"].str.contains("over 30 minute travel time", regex=False)
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
    class_df = _build_classification_frame(df)
    group_keys = ["Source File", "Employee", "Identifier", "Employee Label", "Service Date"]
    call_hours = (
        df.groupby(group_keys, as_index=False)
        .agg(Call_Hours_Added=("Call Hours Added", "sum"))
    )

    visit_df = df.loc[~call_mask].copy()
    visit_df = visit_df.dropna(subset=["Time In DT", "Time Out DT"])

    overnight_mask = visit_df["Time Out DT"] < visit_df["Time In DT"]
    visit_df.loc[overnight_mask, "Time Out DT"] = visit_df.loc[overnight_mask, "Time Out DT"] + pd.Timedelta(
        days=1
    )

    visit_grouped = (
        visit_df.groupby(group_keys, as_index=False)
        .agg(Earliest_Time_In=("Time In DT", "min"), Latest_Time_Out=("Time Out DT", "max"))
    )
    grouped = visit_grouped.merge(
        call_hours,
        on=group_keys,
        how="outer",
    )
    grouped["Call_Hours_Added"] = grouped["Call_Hours_Added"].fillna(0.0)
    miles_by_day = (
        df.groupby(group_keys, as_index=False)
        .agg(Travel_Miles_Total=("Travel Miles", "sum"))
    )
    grouped = grouped.merge(
        miles_by_day,
        on=group_keys,
        how="left",
    )
    grouped["Travel_Miles_Total"] = grouped["Travel_Miles_Total"].fillna(0.0)
    grouped["Visit Span Hours"] = (
        grouped["Latest_Time_Out"] - grouped["Earliest_Time_In"]
    ).dt.total_seconds() / 3600
    grouped["Visit Span Hours"] = grouped["Visit Span Hours"].fillna(0.0)
    grouped["Total Hours Worked"] = grouped["Visit Span Hours"] + grouped["Call_Hours_Added"]
    grouped = grouped.sort_values(["Source File", "Employee", "Service Date"])

    name_lookup = (
        df.groupby(["Source File", "Employee", "Identifier", "Employee Label"], sort=False)["Employee Name"]
        .agg(_first_non_empty_in_group)
        .reset_index(name="Employee_Name_From_File")
    )
    grouped = grouped.merge(
        name_lookup,
        on=["Source File", "Employee", "Identifier", "Employee Label"],
        how="left",
    )
    grouped["Employee_Name_From_File"] = (
        grouped["Employee_Name_From_File"].fillna("").astype(str).str.strip()
    )
    grouped["Employee_Name_From_File"] = grouped["Employee_Name_From_File"].replace({"nan": ""})

    grouped["Week_Column"] = _sunday_week_column_label(grouped["Service Date"])
    weekly_by_label = (
        grouped.groupby(["Source File", "Employee Label", "Week_Column"], sort=False)["Total Hours Worked"]
        .sum()
        .reset_index()
    )
    weekly_by_label["Total Hours Worked"] = (
        pd.to_numeric(weekly_by_label["Total Hours Worked"], errors="coerce").fillna(0.0).astype("float64")
    )
    hours_pivot = weekly_by_label.pivot_table(
        index=["Source File", "Employee Label"],
        columns="Week_Column",
        values="Total Hours Worked",
        aggfunc="sum",
        fill_value=0.0,
    )
    week_columns = sorted(hours_pivot.columns, key=_parse_sunday_week_column)
    hours_pivot = hours_pivot.reindex(columns=week_columns, fill_value=0.0)
    label_order = (
        grouped[["Source File", "Employee Label"]].drop_duplicates().apply(tuple, axis=1).tolist()
    )
    hours_pivot = hours_pivot.reindex(label_order).fillna(0.0)
    hours_per_label = grouped.groupby(["Source File", "Employee Label"], sort=False)["Total Hours Worked"].sum()

    label_meta = grouped.groupby(["Source File", "Employee Label"], sort=False).agg(
        employee_id=("Identifier", "first"),
        name_from_file=("Employee_Name_From_File", "first"),
    )

    employee_hours_rows: list[dict[str, str | float]] = []
    for label_key in label_order:
        if label_key not in hours_pivot.index:
            continue
        source_file, label = label_key
        name_from_file = str(label_meta.at[label_key, "name_from_file"]).strip()
        if name_from_file and name_from_file.lower() != "nan":
            emp_name = name_from_file
        else:
            emp_name, _ = _split_employee_label(label)
        raw_id = label_meta.at[label_key, "employee_id"]
        if raw_id is None or (isinstance(raw_id, float) and pd.isna(raw_id)):
            rid = ""
        else:
            rid = str(raw_id).strip()
        if not rid or rid.lower() == "nan":
            _, emp_id = _split_employee_label(label)
        else:
            emp_id = rid
        if not emp_id or str(emp_id).lower() == "nan":
            emp_id = ""
        row: dict[str, str | float] = {
            "source_file": source_file,
            "employee_name": emp_name,
            "employee_id": emp_id,
        }
        for wc in week_columns:
            row[wc] = round(float(hours_pivot.loc[label_key, wc]), 2)
        row["total_hours"] = round(float(hours_per_label.loc[label_key]), 2)
        employee_hours_rows.append(row)

    weekly_miles_by_label = (
        grouped.groupby(["Source File", "Employee Label", "Week_Column"], sort=False)["Travel_Miles_Total"]
        .sum()
        .reset_index()
    )
    weekly_miles_by_label["Travel_Miles_Total"] = (
        pd.to_numeric(weekly_miles_by_label["Travel_Miles_Total"], errors="coerce").fillna(0.0).astype("float64")
    )
    miles_pivot = weekly_miles_by_label.pivot_table(
        index=["Source File", "Employee Label"],
        columns="Week_Column",
        values="Travel_Miles_Total",
        aggfunc="sum",
        fill_value=0.0,
    )
    miles_pivot = miles_pivot.reindex(columns=week_columns, fill_value=0.0)
    miles_pivot = miles_pivot.reindex(label_order).fillna(0.0)
    miles_per_label = grouped.groupby(["Source File", "Employee Label"], sort=False)["Travel_Miles_Total"].sum()

    travel_miles_rows: list[dict[str, str | float]] = []
    for label_key in label_order:
        if label_key not in miles_pivot.index:
            continue
        source_file, label = label_key
        name_from_file = str(label_meta.at[label_key, "name_from_file"]).strip()
        if name_from_file and name_from_file.lower() != "nan":
            emp_name = name_from_file
        else:
            emp_name, _ = _split_employee_label(label)
        raw_id = label_meta.at[label_key, "employee_id"]
        if raw_id is None or (isinstance(raw_id, float) and pd.isna(raw_id)):
            rid = ""
        else:
            rid = str(raw_id).strip()
        if not rid or rid.lower() == "nan":
            _, emp_id = _split_employee_label(label)
        else:
            emp_id = rid
        if not emp_id or str(emp_id).lower() == "nan":
            emp_id = ""
        tm_row: dict[str, str | float] = {
            "source_file": source_file,
            "employee_name": emp_name,
            "employee_id": emp_id,
        }
        for wc in week_columns:
            tm_row[wc] = round(float(miles_pivot.loc[label_key, wc]), 2)
        tm_row["total_miles"] = round(float(miles_per_label.loc[label_key]), 2)
        travel_miles_rows.append(tm_row)

    travel_miles_df = pd.DataFrame(travel_miles_rows)
    if len(travel_miles_df):
        travel_miles_df["employee_name"] = travel_miles_df["employee_name"].fillna("").astype(str)
        travel_miles_df["employee_id"] = travel_miles_df["employee_id"].fillna("").astype(str)
        travel_miles_df.loc[
            travel_miles_df["employee_id"].str.strip().str.lower().isin(["nan", "none"]),
            "employee_id",
        ] = ""

    employee_hours_df = pd.DataFrame(employee_hours_rows)
    if len(employee_hours_df):
        employee_hours_df["employee_name"] = employee_hours_df["employee_name"].fillna("").astype(str)
        employee_hours_df["employee_id"] = employee_hours_df["employee_id"].fillna("").astype(str)
        employee_hours_df.loc[
            employee_hours_df["employee_id"].str.strip().str.lower().isin(["nan", "none"]),
            "employee_id",
        ] = ""

    detail_hours_raw_total = float(grouped["Total Hours Worked"].sum())
    summary_hours_raw_total = float(hours_per_label.sum()) if len(employee_hours_rows) else 0.0
    detail_hours_total = round(float(grouped["Total Hours Worked"].round(2).sum()), 2)
    summary_hours_total = (
        round(float(employee_hours_df["total_hours"].sum()), 2) if len(employee_hours_df) else 0.0
    )
    # Allow minor floating-point and per-row rounding drift on large exports.
    if employee_hours_rows and abs(summary_hours_raw_total - detail_hours_raw_total) > 0.011:
        raise ValueError(
            "Internal validation failed: employee hours summary does not match timesheet detail totals."
        )

    output = pd.DataFrame(
        {
            "Source File": grouped["Source File"],
            "Employee": grouped["Employee Label"],
            "Service Date": pd.to_datetime(grouped["Service Date"]).dt.strftime("%m/%d/%Y"),
            "Earliest Actual Time In": grouped["Earliest_Time_In"].dt.strftime("%I:%M %p").fillna(""),
            "Latest Actual Time Out": grouped["Latest_Time_Out"].dt.strftime("%I:%M %p").fillna(""),
            "Total Travel Miles": grouped["Travel_Miles_Total"].round(2),
            "Call Hours Added": grouped["Call_Hours_Added"].round(2),
            "Total Hours Worked": grouped["Total Hours Worked"].round(2),
        }
    )

    total_travel_miles = round(float(grouped["Travel_Miles_Total"].sum()), 2)

    summary = {
        "Employees": int(grouped["Employee"].nunique()),
        "Employee-Day Records": int(len(output)),
        "Total Hours": detail_hours_total,
        "Sum Employee Total Hours": summary_hours_total,
        "Total Travel Miles": total_travel_miles,
    }

    # Build a printable report with per-employee totals and a final grand total row.
    report_rows: list[dict[str, str | float]] = []
    file_order = grouped["Source File"].drop_duplicates().tolist()
    for source_file in file_order:
        file_group = grouped.loc[grouped["Source File"] == source_file]
        for employee_key, employee_group in file_group.groupby("Employee", sort=False):
            employee_label = employee_group["Employee Label"].iloc[0]
            for _, row in employee_group.iterrows():
                report_rows.append(
                    {
                        "Source File": source_file,
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
                        "Total Travel Miles": round(float(row["Travel_Miles_Total"]), 2),
                        "Call Hours Added": round(float(row["Call_Hours_Added"]), 2),
                        "Total Hours Worked": round(float(row["Total Hours Worked"]), 2),
                    }
                )
            report_rows.append(
                {
                    "Source File": source_file,
                    "Employee": f"Grand Total ({employee_label})",
                    "Service Date": "",
                    "Earliest Actual Time In": "",
                    "Latest Actual Time Out": "",
                    "Total Travel Miles": round(
                        float(
                            grouped.loc[
                                (grouped["Employee"] == employee_key) & (grouped["Source File"] == source_file),
                                "Travel_Miles_Total",
                            ].sum()
                        ),
                        2,
                    ),
                    "Call Hours Added": round(
                        float(
                            grouped.loc[
                                (grouped["Employee"] == employee_key) & (grouped["Source File"] == source_file),
                                "Call_Hours_Added",
                            ].sum()
                        ),
                        2,
                    ),
                    "Total Hours Worked": round(
                        float(
                            grouped.loc[
                                (grouped["Employee"] == employee_key) & (grouped["Source File"] == source_file),
                                "Total Hours Worked",
                            ].sum()
                        ),
                        2,
                    ),
                }
            )

        report_rows.append(
            {
                "Source File": source_file,
                "Employee": f"File Grand Total ({source_file})",
                "Service Date": "",
                "Earliest Actual Time In": "",
                "Latest Actual Time Out": "",
                "Total Travel Miles": round(float(file_group["Travel_Miles_Total"].sum()), 2),
                "Call Hours Added": round(float(file_group["Call_Hours_Added"].sum()), 2),
                "Total Hours Worked": round(float(file_group["Total Hours Worked"].sum()), 2),
            }
        )

    report_rows.append(
        {
            "Source File": "",
            "Employee": "OVERALL GRAND TOTAL",
            "Service Date": "",
            "Earliest Actual Time In": "",
            "Latest Actual Time Out": "",
            "Total Travel Miles": total_travel_miles,
            "Call Hours Added": round(float(grouped["Call_Hours_Added"].sum()), 2),
            "Total Hours Worked": summary["Total Hours"],
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

        numeric_timesheet_cols = {"Total Travel Miles", "Call Hours Added", "Total Hours Worked"}
        for col_idx, column_name in enumerate(formatted_output.columns):
            sheet.write(0, col_idx, column_name, header_fmt)

        for row_idx, row in enumerate(report_rows, start=1):
            is_overall_total = row["Employee"] == "OVERALL GRAND TOTAL"
            is_employee_total = str(row["Employee"]).startswith("Grand Total (")
            is_file_total = str(row["Employee"]).startswith("File Grand Total (")
            is_any_subtotal = is_employee_total or is_file_total
            base_fmt = grand_total_fmt if is_overall_total else total_row_fmt if is_any_subtotal else data_fmt
            hour_cell_fmt = grand_hours_fmt if is_overall_total else total_hours_fmt if is_any_subtotal else hours_fmt
            for col_idx, column_name in enumerate(formatted_output.columns):
                val = row[column_name]
                if column_name in numeric_timesheet_cols:
                    sheet.write_number(row_idx, col_idx, float(val), hour_cell_fmt)
                else:
                    sheet.write(row_idx, col_idx, val, base_fmt)

        sheet.set_column("A:A", 24)
        sheet.set_column("B:B", 34)
        sheet.set_column("C:E", 20)
        sheet.set_column("F:H", 18)
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
        summary_sheet.write("A5", "Sum of employee total hours", label_fmt)
        summary_sheet.write_number("B5", summary["Sum Employee Total Hours"], summary_hours_fmt)
        summary_sheet.write("A6", "Total travel miles", label_fmt)
        summary_sheet.write_number("B6", summary["Total Travel Miles"], summary_hours_fmt)

        summary_sheet.set_column("A:A", 32)
        summary_sheet.set_column("B:B", 16)

        ehs_name = "Employee Hours Summary"
        ehs_header_fmt = writer.book.add_format(
            {"bold": True, "bg_color": "#1F4E78", "font_color": "white", "align": "center", "border": 1}
        )
        ehs_text_fmt = writer.book.add_format({"border": 1, "num_format": "@"})
        ehs_hours_fmt = writer.book.add_format({"border": 1, "num_format": "0.00"})
        ehs_total_fmt = writer.book.add_format({"bold": True, "border": 1, "num_format": "0.00"})

        ehs_sheet = writer.book.add_worksheet(ehs_name)
        if len(employee_hours_df):
            ehs_cols = list(employee_hours_df.columns)
            for col_idx, column_name in enumerate(ehs_cols):
                ehs_sheet.write(0, col_idx, column_name, ehs_header_fmt)
            for row_idx, (_, erow) in enumerate(employee_hours_df.iterrows(), start=1):
                for col_idx, column_name in enumerate(ehs_cols):
                    val = erow[column_name]
                    is_hours_col = column_name not in ("employee_name", "employee_id")
                    fmt = ehs_total_fmt if column_name == "total_hours" else ehs_hours_fmt if is_hours_col else ehs_text_fmt
                    if column_name in ("employee_name", "employee_id"):
                        text = "" if pd.isna(val) else str(val).strip()
                        if text.lower() == "nan":
                            text = ""
                        ehs_sheet.write_string(row_idx, col_idx, text, ehs_text_fmt)
                    elif isinstance(val, (int, float)) and not isinstance(val, bool) and pd.notna(val):
                        ehs_sheet.write_number(row_idx, col_idx, float(val), fmt)
                    else:
                        ehs_sheet.write(row_idx, col_idx, val if pd.notna(val) else "", fmt)
            ncols = len(ehs_cols)
            ehs_sheet.set_column(0, 2, 28)
            if ncols > 3:
                ehs_sheet.set_column(3, ncols - 2, 14)
            if ncols > 0:
                ehs_sheet.set_column(ncols - 1, ncols - 1, 16)
            ehs_sheet.freeze_panes(1, 0)
            ehs_sheet.autofilter(0, 0, len(employee_hours_df), ncols - 1)
        else:
            ehs_sheet.write(0, 0, "source_file", ehs_header_fmt)
            ehs_sheet.write(0, 1, "employee_name", ehs_header_fmt)
            ehs_sheet.write(0, 2, "employee_id", ehs_header_fmt)
            ehs_sheet.write(0, 3, "total_hours", ehs_header_fmt)

        tms_name = "Travel Miles Summary"
        tms_sheet = writer.book.add_worksheet(tms_name)
        if len(travel_miles_df):
            tms_cols = list(travel_miles_df.columns)
            for col_idx, column_name in enumerate(tms_cols):
                tms_sheet.write(0, col_idx, column_name, ehs_header_fmt)
            for row_idx, (_, trow) in enumerate(travel_miles_df.iterrows(), start=1):
                for col_idx, column_name in enumerate(tms_cols):
                    val = trow[column_name]
                    is_miles_col = column_name not in ("employee_name", "employee_id")
                    fmt = ehs_total_fmt if column_name == "total_miles" else ehs_hours_fmt if is_miles_col else ehs_text_fmt
                    if column_name in ("employee_name", "employee_id"):
                        text = "" if pd.isna(val) else str(val).strip()
                        if text.lower() == "nan":
                            text = ""
                        tms_sheet.write_string(row_idx, col_idx, text, ehs_text_fmt)
                    elif isinstance(val, (int, float)) and not isinstance(val, bool) and pd.notna(val):
                        tms_sheet.write_number(row_idx, col_idx, float(val), fmt)
                    else:
                        tms_sheet.write(row_idx, col_idx, val if pd.notna(val) else "", fmt)
            tms_ncols = len(tms_cols)
            tms_sheet.set_column(0, 2, 28)
            if tms_ncols > 3:
                tms_sheet.set_column(3, tms_ncols - 2, 14)
            if tms_ncols > 0:
                tms_sheet.set_column(tms_ncols - 1, tms_ncols - 1, 16)
            tms_sheet.freeze_panes(1, 0)
            tms_sheet.autofilter(0, 0, len(travel_miles_df), tms_ncols - 1)
        else:
            tms_sheet.write(0, 0, "source_file", ehs_header_fmt)
            tms_sheet.write(0, 1, "employee_name", ehs_header_fmt)
            tms_sheet.write(0, 2, "employee_id", ehs_header_fmt)
            tms_sheet.write(0, 3, "total_miles", ehs_header_fmt)

        section_title_fmt = writer.book.add_format(
            {"bold": True, "font_size": 13, "bg_color": "#D9E2F3", "border": 1, "valign": "vcenter"}
        )
        subsection_fmt = writer.book.add_format({"bold": True, "bg_color": "#E8EEF9", "border": 1})
        clf_sheet = writer.book.add_worksheet(CLASSIFICATION_SHEET_NAME)
        _write_classification_summary_sheet(
            writer.book,
            clf_sheet,
            class_df,
            section_title_fmt=section_title_fmt,
            subsection_fmt=subsection_fmt,
            header_fmt=ehs_header_fmt,
            text_fmt=ehs_text_fmt,
            num_fmt=ehs_hours_fmt,
        )
    excel_stream.seek(0)

    return output, excel_stream


def process_timesheet(file_obj, filename: str | None = None) -> tuple[pd.DataFrame, BytesIO]:
    df = _prepare_clean_rows(file_obj, filename=filename)
    return _build_timesheet_output(df)


def process_timesheets(files: list[tuple[object, str]]) -> tuple[pd.DataFrame, BytesIO]:
    cleaned: list[pd.DataFrame] = []
    for file_obj, filename in files:
        cleaned.append(_prepare_clean_rows(file_obj, filename=filename))
    combined = pd.concat(cleaned, ignore_index=True) if cleaned else pd.DataFrame()
    return _build_timesheet_output(combined)


def filter_timesheet_fact_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Return only data rows from a Timesheet export (exclude embedded total rows)."""
    if df.empty or "Employee" not in df.columns:
        return df
    emp_col = df["Employee"].astype(str)
    mask = ~(
        emp_col.str.contains("Grand Total", case=False, na=False)
        | (emp_col.str.strip() == "OVERALL GRAND TOTAL")
    )
    return df.loc[mask].copy()
