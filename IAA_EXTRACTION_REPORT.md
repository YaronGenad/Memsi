# IAA Monthly Flight Extraction Report

- PDFs attempted: 51
- Successfully extracted: 48
- Failures: 3

## Summary statistics
- total_passengers: min=203,254 max=2,545,080 mean=1,441,135 n=48
- arriving_passengers: min=118,345 max=1,235,430 mean=720,864 n=48
- total_flights: min=2,720 max=16,639 mean=10,347 n=48
- arriving_flights: min=1,357 max=8,313 mean=5,173 n=48

## Failures
- 2023-08: image-only PDF (no text layer; would require OCR such as Tesseract to extract)
- 2023-09: image-only PDF (no text layer; would require OCR such as Tesseract to extract)
- 2023-10: image-only PDF (no text layer; would require OCR such as Tesseract to extract)

## Suspicious values flagged
- 2026-03: total_passengers=203254 out of range; arriving_passengers=118345 out of range; total_flights=2720 out of range; arriving_flights=1357 out of range

## Sample rows

| year_month | total_pax | arriving_pax | total_flights | arr_flights | notes |
|---|---|---|---|---|---|
| 2022-01 | 420,438 | 219,236 | 5,570 | 2,785 | ok |
| 2022-10 | 1,995,924 | 1,084,729 | 12,769 | 6,394 | ok |
| 2023-07 | 2,545,080 | 1,235,430 | 16,639 | 8,313 | ok |
| 2024-07 | 1,773,102 | 842,202 | 12,076 | 6,044 | ok |
| 2025-04 | 1,835,979 | 927,028 | 13,363 | 6,683 | ok |

- CSV: `c:\Users\yaron\OneDrive - Newcinema\priority\priority_interface\iaa_flight_data.csv`
- Source PDFs cached at: `c:\Users\yaron\OneDrive - Newcinema\priority\priority_interface\.iaa_pdfs`

## Notes on missing fields

- `active_airlines` is NULL for all rows. The IAA reports
  list airlines individually across multiple pages with no
  clean monthly total, and the task marks it as
  nice-to-have only.
- The 3 failing months (Aug/Sep/Oct 2023) are scanned image
  PDFs with no extractable text layer. They cover the
  August–October 2023 window (peak summer + war onset on
  Oct 7). Recovering them would require an OCR pipeline.
- The 2026-03 row is real data, not a parse error: it
  reflects the March 2026 airspace disruption (-85% YoY).
  Marked suspicious only because it falls outside the
  expected historical band.