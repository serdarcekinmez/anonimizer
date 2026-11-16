# Known limitations (version 0.1.0)

## Input formats

- Supported: CSV, TSV and other single-character-delimited text; XLSX and XLSM (macros are never run).
- Not supported: `.xls`, `.xlsb`, password-protected workbooks, ODS, fixed-width text, JSON, Parquet, databases.
- CSV delimiter is one character among `, ; tab |` unless given in the recipe. Quote character is `"` unless given.
- Encodings detected: UTF-8 (with or without BOM), UTF-16 and UTF-32 with BOM, otherwise Windows-1252. Other legacy encodings must be named in the recipe.
- In a CSV, "row" means record. A quoted field with line breaks makes record numbers differ from physical line numbers; the manifest gives both.

## Structure detection

- Tables are found by blank rows and blank columns. Two tables stacked with no blank row between them are seen as one. A table with one fully empty column and no header there is split in two. Both cases are fixed by editing the recipe.
- A header is recognised by its cells being words. A table whose first data row is all text and which has no header is read with that row as header.
- A region that starts more than 30 rows below the top of its block (a side table far down a sheet) gets no header analysis and a confidence of 0.3.
- Footer lines glued to a table (totals, notes without a blank row before them) are read as data rows, usually reported as short rows.
- Merged cells, hidden rows and columns, comments, data validations, defined names, pivot tables, charts and external links are counted, not interpreted, and never reproduced.
- Multi-row headers and pivoted layouts are not understood.
- Composite keys are not detected. A reference is proposed only towards a single unique column of another table in the same file, and for integer columns only when the name suggests an identifier.

## Anomaly detection

- Classes are the ones listed in `anonimizer/contract.py` (`DESCRIPTIONS`). An anomaly outside those classes is not reported.
- Numeric outliers are judged by digit count, not by value. 9 and 99999 differ; 10000 and 99999 do not.
- Rare text layouts are reported only in columns that are regular enough (at least 90 % of values share non-rare layouts), at most six per column plus an aggregate.
- Duplicate rows are counted, not located (no row numbers for them in the private profile).
- Distinct-value tracking keeps exact values up to 1,000 distinct per column, then hashes. Memory grows with the number of rows in high-cardinality columns (about 8 bytes per row and column).
- Day/month order that cannot be decided from the values is reported as ambiguous, and such dates are generated with days of 12 or less.
- `1,234` is read as thousands unless the column shows decimal commas elsewhere.
- Missing-value markers are a fixed list plus the ones named in the recipe. Numerical NaN does not exist in CSV or XLSX cells; `NaN` there is text and is treated as a marker.
- A column where no type reaches 60 % is reported as mixed.

## Generation

- Values follow pattern classes, not distributions. Do not use the output for statistics or model training.
- Columns are generated independently: relationships between columns of the same row (city and postal code, start date before end date, total = quantity x price) are not preserved. Only declared key behaviour is.
- Formulas are never written. A formula column becomes a column of plain values.
- Category columns produce invented category tokens unless a person approves copying the frequent values.
- Mixed newlines, undecodable bytes, NUL bytes and unterminated quotes of the source are reported and not reproduced. Quoting style is not preserved except for quoted empty fields.
- A single-column CSV cannot represent an unquoted empty cell (it would be a blank line).
- Control characters cannot be stored in XLSX output.
- At most one generated value per column and row can carry a scenario. Combinations of anomalies in the same cell are not generated.
- The first data row is kept ordinary when the request leaves room for it.

## Privacy

See [privacy-limitations.md](privacy-limitations.md) and [threat-model.md](threat-model.md). In short: no attack-based evaluation, no external tier, names of columns, sheets and tables are copied, and "synthetic" does not mean "anonymous".

## Interface

- One user, one file, one session. State lives in memory and in a private temporary folder removed on exit.
- Checked by server tests and by running the page script in an embedded JavaScript engine. Not yet exercised in a real browser by the developer.
- No progress bar: analysing a file of several hundred megabytes shows "Analysing every cell" until it is done.
- The page never receives the values of the source file. The region preview shows the kind of each cell (text, number, date, missing) for the first eight rows; the column grid shows synthetic sample rows of ordinary values produced from the applied contract. Neither is a view of the source rows, so a wrong header or boundary has to be recognised from cell kinds and row numbers.
- "Confirmed by you" means that the table settings were applied with the confirm button. It records a user action; it does not check that the regions are right.
- Bulk renaming works on the kept columns of one table (spelling, find and replace, prefix, suffix). There are no saved naming presets.
- Columns are edited one at a time. Rules that link several columns of one row are not detected and not preserved; the only relationships found are single-column key references between tables.
- The layout, the colours and the behaviour of the reorganised page (2026-11-16) were not seen in a real browser: no browser could be started in the development sandbox.

## Performance (measured on the development machine, Python 3.12)

- 300,000 rows x 10 columns (29 MB CSV): profile in about 8 s, peak memory about 190 MB; full run including assessment about 10 s.
- 2,000,000 rows x 10 columns (186 MB CSV): full run in about 75 s, peak memory about 260 MB (`pytest --runslow tests/bench`, run once on 2026-11-16).
- Not measured: wide files (hundreds of columns), files with many high-cardinality text columns, large XLSX workbooks.

## Process

- No independent review has taken place. The fixtures, the detector and the tests have the same author.
- `tools/gate.py --release` fails by design until the owner dispositions the open findings.
