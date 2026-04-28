from io import BytesIO

import pandas as pd
from django.test import SimpleTestCase

from .services import filter_timesheet_fact_rows, process_timesheet


class ProcessTimesheetTests(SimpleTestCase):
    def test_groups_by_employee_and_service_date(self):
        source = pd.DataFrame(
            [
                {
                    "First Name": "Jane",
                    "Last Name": "Doe",
                    "Service Date": "2026-01-02",
                    "Actual Time In": "08:15 AM",
                    "Actual Time Out": "09:00 AM",
                },
                {
                    "First Name": "Jane",
                    "Last Name": "Doe",
                    "Service Date": "2026-01-02",
                    "Actual Time In": "11:00 AM",
                    "Actual Time Out": "01:30 PM",
                },
            ]
        )
        input_stream = BytesIO()
        source.to_excel(input_stream, index=False)
        input_stream.seek(0)

        output_df, _ = process_timesheet(input_stream, filename="input.xlsx")

        self.assertEqual(len(output_df), 1)
        self.assertEqual(output_df.iloc[0]["Employee"], "Doe, Jane")
        self.assertEqual(output_df.iloc[0]["Earliest Actual Time In"], "08:15 AM")
        self.assertEqual(output_df.iloc[0]["Latest Actual Time Out"], "01:30 PM")
        self.assertEqual(output_df.iloc[0]["Total Hours Worked"], 5.25)

    def test_accepts_csv_input(self):
        source = pd.DataFrame(
            [
                {
                    "First Name": "John",
                    "Last Name": "Smith",
                    "Service Date": "2026-02-10",
                    "Actual Time In": "09:00 AM",
                    "Actual Time Out": "11:00 AM",
                }
            ]
        )
        input_stream = BytesIO(source.to_csv(index=False).encode("utf-8"))

        output_df, _ = process_timesheet(input_stream, filename="input.csv")

        self.assertEqual(len(output_df), 1)
        self.assertEqual(output_df.iloc[0]["Employee"], "Smith, John")
        self.assertEqual(output_df.iloc[0]["Total Hours Worked"], 2.0)

    def test_accepts_header_aliases(self):
        source = pd.DataFrame(
            [
                {
                    "firstname": "Mia",
                    "lastname": "Stone",
                    "DOS": "2026-03-02",
                    "Time In": "07:00",
                    "Time Out": "15:00",
                }
            ]
        )
        input_stream = BytesIO(source.to_csv(index=False).encode("utf-8"))

        output_df, _ = process_timesheet(input_stream, filename="alias.csv")

        self.assertEqual(output_df.iloc[0]["Employee"], "Stone, Mia")
        self.assertEqual(output_df.iloc[0]["Total Hours Worked"], 8.0)

    def test_groups_same_name_by_identifier(self):
        source = pd.DataFrame(
            [
                {
                    "Identifier": "A1",
                    "First Name": "Alex",
                    "Last Name": "Kim",
                    "Service Date": "2026-04-01",
                    "Actual Time In": "08:00 AM",
                    "Actual Time Out": "09:00 AM",
                },
                {
                    "Identifier": "B2",
                    "First Name": "Alex",
                    "Last Name": "Kim",
                    "Service Date": "2026-04-01",
                    "Actual Time In": "10:00 AM",
                    "Actual Time Out": "11:00 AM",
                },
            ]
        )
        input_stream = BytesIO()
        source.to_excel(input_stream, index=False)
        input_stream.seek(0)

        output_df, _ = process_timesheet(input_stream, filename="same_name.xlsx")

        self.assertEqual(len(output_df), 2)
        self.assertIn("Kim, Alex (A1)", set(output_df["Employee"]))
        self.assertIn("Kim, Alex (B2)", set(output_df["Employee"]))

    def test_adds_patient_call_hours_separately(self):
        source = pd.DataFrame(
            [
                {
                    "Identifier": "PV1",
                    "First Name": "Jane",
                    "Last Name": "Doe",
                    "Service Date": "2026-01-02",
                    "Service Code": "RNV",
                    "Actual Time In": "08:00 AM",
                    "Actual Time Out": "10:00 AM",
                    "Pay Units": 1.0,
                },
                {
                    "Identifier": "PV1",
                    "First Name": "Jane",
                    "Last Name": "Doe",
                    "Service Date": "2026-01-02",
                    "Service Code": "PatPC",
                    "Service Description": "Patient Phone Calls",
                    "Actual Time In": "05:00 PM",
                    "Actual Time Out": "05:30 PM",
                    "Pay Units": 0.5,
                },
            ]
        )
        input_stream = BytesIO(source.to_csv(index=False).encode("utf-8"))

        output_df, _ = process_timesheet(input_stream, filename="calls.csv")

        self.assertEqual(len(output_df), 1)
        self.assertEqual(output_df.iloc[0]["Employee"], "Doe, Jane (PV1)")
        self.assertEqual(output_df.iloc[0]["Earliest Actual Time In"], "08:00 AM")
        self.assertEqual(output_df.iloc[0]["Latest Actual Time Out"], "10:00 AM")
        self.assertEqual(output_df.iloc[0]["Call Hours Added"], 0.5)
        self.assertEqual(output_df.iloc[0]["Total Hours Worked"], 2.5)

    def test_employee_hours_summary_multi_week_pivot(self):
        source = pd.DataFrame(
            [
                {
                    "First Name": "Jane",
                    "Last Name": "Doe",
                    "Service Date": "2026-01-06",
                    "Actual Time In": "08:00 AM",
                    "Actual Time Out": "12:00 PM",
                },
                {
                    "First Name": "Jane",
                    "Last Name": "Doe",
                    "Service Date": "2026-01-13",
                    "Actual Time In": "09:00 AM",
                    "Actual Time Out": "01:00 PM",
                },
            ]
        )
        input_stream = BytesIO()
        source.to_excel(input_stream, index=False)
        input_stream.seek(0)

        output_df, excel_buf = process_timesheet(input_stream, filename="input.xlsx")

        self.assertEqual(len(output_df), 2)
        detail_sum = round(float(output_df["Total Hours Worked"].sum()), 2)
        summary_df = pd.read_excel(excel_buf, sheet_name="Employee Hours Summary")
        self.assertEqual(round(float(summary_df.iloc[0]["total_hours"]), 2), detail_sum)
        self.assertIn("2026-W02", summary_df.columns)
        self.assertIn("2026-W03", summary_df.columns)
        self.assertEqual(float(summary_df.iloc[0]["2026-W02"]), 4.0)
        self.assertEqual(float(summary_df.iloc[0]["2026-W03"]), 4.0)

        kpi = pd.read_excel(excel_buf, sheet_name="Summary")
        self.assertEqual(float(kpi.loc[kpi["Metric"] == "Total Hours", "Value"].iloc[0]), detail_sum)
        self.assertEqual(
            float(kpi.loc[kpi["Metric"] == "Sum of employee total hours", "Value"].iloc[0]),
            detail_sum,
        )

    def test_employee_hours_summary_splits_identifier_from_label(self):
        source = pd.DataFrame(
            [
                {
                    "Identifier": "PV1",
                    "First Name": "Jane",
                    "Last Name": "Doe",
                    "Service Date": "2026-01-06",
                    "Actual Time In": "08:00 AM",
                    "Actual Time Out": "10:00 AM",
                },
            ]
        )
        input_stream = BytesIO()
        source.to_excel(input_stream, index=False)
        input_stream.seek(0)

        _, excel_buf = process_timesheet(input_stream, filename="input.xlsx")
        summary_df = pd.read_excel(excel_buf, sheet_name="Employee Hours Summary")
        self.assertEqual(summary_df.iloc[0]["employee_name"], "Doe, Jane")
        self.assertEqual(summary_df.iloc[0]["employee_id"], "PV1")

    def test_employee_hours_summary_uses_source_employee_column_when_present(self):
        source = pd.DataFrame(
            [
                {
                    "Employee": "Display From Payroll",
                    "First Name": "Jane",
                    "Last Name": "Doe",
                    "Service Date": "2026-01-06",
                    "Actual Time In": "08:00 AM",
                    "Actual Time Out": "10:00 AM",
                },
            ]
        )
        input_stream = BytesIO(source.to_csv(index=False).encode("utf-8"))

        _, excel_buf = process_timesheet(input_stream, filename="input.csv")
        summary_df = pd.read_excel(excel_buf, sheet_name="Employee Hours Summary")
        self.assertEqual(summary_df.iloc[0]["employee_name"], "Display From Payroll")
        eid = summary_df.iloc[0]["employee_id"]
        self.assertTrue(
            eid == "" or (isinstance(eid, float) and pd.isna(eid)) or pd.isna(eid),
            msg="empty id should be blank; pandas often reads that as NaN from xlsx",
        )

    def test_filter_timesheet_fact_rows_excludes_totals(self):
        frame = pd.DataFrame(
            {
                "Employee": ["Doe, Jane", "Grand Total (Doe, Jane)", "OVERALL GRAND TOTAL"],
                "Total Hours Worked": [3.0, 3.0, 3.0],
            }
        )
        filtered = filter_timesheet_fact_rows(frame)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered.iloc[0]["Employee"], "Doe, Jane")

    def test_large_export_style_rounding_drift_does_not_fail_validation(self):
        source = pd.DataFrame(
            [
                {
                    "First Name": "Jane",
                    "Last Name": "Doe",
                    "Service Date": "2026-01-06",
                    "Actual Time In": "08:00 AM",
                    "Actual Time Out": "08:01 AM",
                },
                {
                    "First Name": "John",
                    "Last Name": "Smith",
                    "Service Date": "2026-01-06",
                    "Actual Time In": "08:00 AM",
                    "Actual Time Out": "08:01 AM",
                },
            ]
        )
        input_stream = BytesIO(source.to_csv(index=False).encode("utf-8"))

        output_df, excel_buf = process_timesheet(input_stream, filename="rounding.csv")

        self.assertEqual(len(output_df), 2)
        detail_total = round(float(output_df["Total Hours Worked"].sum()), 2)
        summary_df = pd.read_excel(excel_buf, sheet_name="Summary")
        summary_total = float(summary_df.loc[summary_df["Metric"] == "Sum of employee total hours", "Value"].iloc[0])
        self.assertEqual(summary_total, detail_total)
