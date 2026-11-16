# Product-value demonstration

Produced by `python tools/demo.py` with Anonimizer 0.1.0, policy `internal-dev`, 60 rows, seed 1. Every number below is computed by the script; nothing is typed in by hand.

The three source files are synthetic fixtures. Their ground truth is written by `tests/fixtures/build_fixtures.py` from what it plants; that script does not use the detector. The generation request names no anomaly: both generators receive the file and a row count.

The baseline is `tools/baseline_mock.py`: it reads the header and the first 200 rows, guesses one type per column and emits clean values. It stands for an ordinary schema-driven mock-data request.

## Summary

| Fixture | Planted anomaly classes | Found in the source by Anonimizer | Present in Anonimizer's output | Present in the baseline's output |
|---|---|---|---|---|
| customers_hidden.csv | 27 | 27 | 26 | 1 |
| orders_multi.tsv | 20 | 20 | 20 | 1 |
| inventory_mixed.xlsx | 25 | 25 | 24 | 0 |

"Present in the output" is measured by profiling each output file again and checking for the same anomaly class in the same column. It is a class-level check, not a count comparison.

## customers_hidden.csv

| Table | Column | Planted class | Planted | Detected | In Anonimizer output | In baseline output |
|---|---|---|---|---|---|---|
| table_1 | (row) | row.duplicate | 2 | 2 | yes | no |
| table_1 | (row) | row.ragged_long | 1 | 1 | yes | no |
| table_1 | (row) | row.ragged_short | 1 | 1 | yes | no |
| table_1 | balance | format.number_deviation | 1 | 1 | yes | no |
| table_1 | balance | missing.empty | 2 | 2 | yes | no |
| table_1 | balance | missing.marker | 4 | 4 | yes | no |
| table_1 | balance | numeric.negative | 2 | 2 | yes | no |
| table_1 | balance | numeric.zero | 4 | 4 | yes | no |
| table_1 | balance | type.text_in_number | 1 | 1 | yes | no |
| table_1 | country | category.rare_value | 1 | 1 | yes | no |
| table_1 | country | missing.marker | 1 | 1 | yes | no |
| table_1 | country | text.rare_pattern | 1 | 1 | yes | no |
| table_1 | customer_id | key.duplicate | 3 | 3 | yes | no |
| table_1 | email | missing.marker | 1 | 1 | yes | no |
| table_1 | email | text.padded | 1 | 1 | yes | no |
| table_1 | full_name | text.rare_pattern | 1 | 1 | yes | no |
| table_1 | loyalty_points | missing.marker | 1 | 1 | yes | no |
| table_1 | loyalty_points | missing.whitespace | 1 | 1 | yes | no |
| table_1 | loyalty_points | type.text_in_number | 1 | 1 | yes | no |
| table_1 | notes | missing.empty | 4520 | 4520 | yes | yes |
| table_1 | notes | missing.quoted_empty | 2 | 2 | yes | no |
| table_1 | notes | text.formula_like | 1 | 1 | yes | no |
| table_1 | notes | text.multiline | 1 | 1 | yes | no |
| table_1 | notes | text.rare_pattern | 3 | 3 | no | no |
| table_1 | signup_date | format.date_deviation | 3 | 3 | yes | no |
| table_1 | signup_date | missing.empty | 1 | 1 | yes | no |
| table_1 | signup_date | value.invalid_date | 2 | 2 | yes | no |

Coverage: table_1: 31/31 scenarios in 60 rows (full coverage needs 11 rows packed, 31 with one scenario per row).

Findings not listed in the ground truth: category.rare_value in table_1.notes (x3).

Planted classes not found again in Anonimizer's output: text.rare_pattern in table_1.notes.

Self-check on the generated file: 27 covered scenarios found again, 4 not found again (category.rare_value, text.rare_pattern).

Privacy assessment: passed, tier LOCAL_ONLY (singling out: passed, linkability: passed, inference: passed, source leakage: passed).

Scenario Manifest (31 entries), first entries:

| Scenario | Column | Data rows | Location |
|---|---|---|---|
| row with more fields than the header (extra fields: 1) | (row) | 2 | line 3 |
| value containing a line break | notes | 7 | line 8, field 10 |
| rare text layout (kind: code, pattern: =A{9-16}("a{3-4}:/{2}a{5-8}.a{3-4}")) | notes | 8 | line 10, field 10 |
| date-shaped value that is not a real calendar date (format: Y-M-D) | signup_date | 9 | line 11, field 4 |
| rare text layout (kind: phrase, pattern: A{5-8}-A{3-4}-9{3-4} a{3-4} a{3-4}) | notes | 12 | line 14, field 10 |
| literal missing-value marker (literal: null) | email | 13 | line 15, field 3 |
| cell holding only whitespace (length: 2) | loyalty_points | 16 | line 18, field 7 |
| literal missing-value marker (literal: UNKNOWN) | country | 20 | line 22, field 5 |
| negative number | balance | 21 | line 23, field 6 |
| rare text layout (kind: sentence, pattern: C{5-8} a{3-4} a{5-8} a{3-4}) | notes | 29 | line 31, field 10 |
| empty cell | signup_date | 30 | line 32, field 4 |
| numeric zero (distinct from a missing value) | balance | 31 | line 33, field 6 |

First rows of the synthetic file (fictional values):

```
customer_id | full_name | email | signup_date | country | balance | loyalty_points | status | last_contact | notes
777360 | Lutit Atema | cota.rimaju@example.org | 2021-09-08 | TO | 2691.01 | 625 | guzazi | 2024-12-20 | 
920871 | Abo Hececive | ijunovo.foluda@example.org | 2016-02-29 | ZU | 7562.42 | 1558 | azohipu | 2023-12-05 | Thagu iso e teriv imobafi | zajo
745715 | Sini Evedaru | ajek.onaza@example.com | 2022-02-27 | OS | 3638.59 | 1223 | azohipu | 2022-08-08 | 
627373 | Inohehag Ezekiza | emun.egaku@example.net | 2023-12-01 | TO | 6888.93 | 4234 | azohipu | 2022-04-22 | Hedah arin asaz
161908 | Olereze Uvekalec | imuholo.uzubof@example.org | 2017-04-30 | TE | 3557.45 | 7874 | azohipu | 2023-06-21 | 
372168 | Aredos Gumodag | bodoboc.gupahaz@example.com | 2015-04-21 | TE | 5326.76 | 558 | azohipu | 2023-03-28 | 
363143 | Ovapojo Iboma | pigeb.azak@example.net | 2015-04-25 | ZU | 3034.50 | 3991 | guzazi | 2024-02-06 | Bukob\nnel u omebe kokunud
399106 | Sobehogu Imunu | baca.supelal@example.org | 2018-04-30 | TE | 9994.59 | 3217 | azohipu | 2022-06-17 | =OJOBELUGAZICELIG("ican://okusel.ifu")
653505 | Fukoc Cevuna | izuve.tima@example.com | 2021-09-31 | HU | 41.92 | 7806 | azohipu | 2022-11-30 | Vubic afa t otohu rehucur
144450 | Lesos Katav | icedit.tevih@example.com | 2016-09-07 | TE | 1541.78 | 6394 | azohipu | 2023-01-18 | 
907387 | Ika Lopece | rinop.ovudur@example.net | 2016-01-18 | TE | 6960.70 | 8794 | azohipu | 2022-06-30 | Vubic afa t otohu rehucur
```

## orders_multi.tsv

| Table | Column | Planted class | Planted | Detected | In Anonimizer output | In baseline output |
|---|---|---|---|---|---|---|
| table_1 | (row) | row.blank_inside_table | 1 | 1 | yes | no |
| table_1 | (row) | row.ragged_long | 1 | 1 | yes | no |
| table_1 | amount_eur | format.number_deviation | 3 | 3 | yes | no |
| table_1 | amount_eur | missing.marker | 1 | 1 | yes | no |
| table_1 | amount_eur | numeric.zero | 1 | 1 | yes | no |
| table_1 | comment | missing.empty | 1117 | 1117 | yes | yes |
| table_1 | comment | text.non_ascii | 82 | 82 | yes | no |
| table_1 | comment | text.rare_pattern | 1 | 1 | yes | no |
| table_1 | customer_ref | key.dangling_reference | 2 | 2 | yes | no |
| table_1 | customer_ref | key.multiplicity | 152 | 152 | yes | no |
| table_1 | customer_ref | missing.marker | 1 | 1 | yes | no |
| table_1 | order_date | format.date_deviation | 2 | 2 | yes | no |
| table_1 | order_date | value.invalid_date | 1 | 1 | yes | no |
| table_1 | order_no | text.padded | 1 | 1 | yes | no |
| table_1 | quantity | missing.empty | 1 | 1 | yes | no |
| table_1 | quantity | numeric.negative | 1 | 1 | yes | no |
| table_1 | quantity | type.text_in_number | 1 | 1 | yes | no |
| table_2 | city | missing.empty | 1 | 1 | yes | no |
| table_2 | vip | format.boolean_deviation | 1 | 1 | yes | no |
| table_2 | vip | missing.marker | 1 | 1 | yes | no |

Coverage: table_1: 20/20 scenarios in 60 rows (full coverage needs 7 rows packed, 21 with one scenario per row); table_2: 3/3 scenarios in 60 rows (full coverage needs 2 rows packed, 3 with one scenario per row).

Findings not listed in the ground truth: category.rare_value in table_1.comment (x1).

Self-check on the generated file: 22 covered scenarios found again, 1 not found again (category.rare_value).

Privacy assessment: passed, tier LOCAL_ONLY (singling out: passed, linkability: passed, inference: passed, source leakage: passed).

Scenario Manifest (23 entries), first entries:

| Scenario | Column | Data rows | Location |
|---|---|---|---|
| blank row inside the table | (row) |  | line 54 |
| numeric zero (distinct from a missing value) | amount_eur | 3 | line 7, field 5 |
| literal missing-value marker (literal: -) | amount_eur | 8 | line 12, field 5 |
| negative number | quantity | 11 | line 15, field 4 |
| empty cell | comment | 17 | line 21, field 7 |
| empty cell | quantity | 18 | line 22, field 4 |
| number written in a different format from the rest of the column (format: thou_dot_dec_comma) | amount_eur | 19 | line 23, field 5 |
| key value occurring a given number of times (occurrences per value: 3+) | customer_ref | 22 40 44 | line 26, field 2; line 44, field 2; line 48, field 2 |
| number written in a different format from the rest of the column (format: dec_comma|{n} €) | amount_eur | 24 | line 28, field 5 |
| row with more fields than the header (extra fields: 1) | (row) | 25 | line 29 |
| value containing non-ASCII characters | comment | 28 | line 32, field 7 |
| key value occurring a given number of times (occurrences per value: 1) | customer_ref | 33 | line 37, field 2 |

First rows of the synthetic file (fictional values):

```
Do consequat amet et magna sed veniam
Lorem ipsum tempor | Nisi ipsum laboris

order_no | customer_ref | order_date | quantity | amount_eur | channel | comment
UPO-329569 | D-8085 | 29.09.2022 | 2 | 857,06 | enatu | 
LOR-625845 | U-4343 | 29.09.2022 | 7 | 5523,48 | ahe | 
EJE-858784 | A-4103 | 10.12.2022 | 61 | 0,00 | ahe | nikagalop cetaàkçi
EMI-994348 | B-1538 | 20.06.2023 | 18 | 3662,39 | ahe | 
VIT-363859 | U-9160 | 06.02.2022 | 36 | 4633,61 | enatu | 
KUD-604372 | E-6579 | 28.01.2023 | 81 | 8760,83 | ahe | 
PAN-358765 | O-6586 | 11.02.2023 | 98 | 5726,07 | enatu | 
ITE-207204 | V-0836 | 06.12.2023 | 3 | - | ahe | ogenir socñte
```

## inventory_mixed.xlsx

| Table | Column | Planted class | Planted | Detected | In Anonimizer output | In baseline output |
|---|---|---|---|---|---|---|
| Stock#1 | active | format.boolean_deviation | 1 | 1 | yes | no |
| Stock#1 | description | category.rare_value | 1 | 1 | yes | no |
| Stock#1 | description | text.rare_pattern | 1 | 1 | yes | no |
| Stock#1 | qty | missing.empty | 3 | 3 | yes | no |
| Stock#1 | qty | missing.marker | 1 | 1 | yes | no |
| Stock#1 | qty | numeric.zero | 1 | 1 | yes | no |
| Stock#1 | qty | storage.number_as_text | 2 | 2 | yes | no |
| Stock#1 | qty | xlsx.error_value | 1 | 1 | yes | no |
| Stock#1 | received | missing.empty | 2 | 2 | yes | no |
| Stock#1 | received | missing.marker | 1 | 1 | yes | no |
| Stock#1 | received | storage.date_as_text | 1 | 1 | yes | no |
| Stock#1 | received | value.invalid_date | 1 | 1 | yes | no |
| Stock#1 | supplier_id | key.dangling_reference | 1 | 1 | yes | no |
| Stock#1 | supplier_id | key.multiplicity | 41 | 41 | yes | no |
| Stock#1 | total | numeric.negative | 1 | 1 | yes | no |
| Stock#1 | total | numeric.zero | 4 | 4 | yes | no |
| Stock#1 | total | xlsx.error_value | 3 | 3 | yes | no |
| Stock#1 | total | xlsx.formula_cell | 400 | 400 | no | no |
| Stock#1 | unit_price | format.number_deviation | 1 | 1 | yes | no |
| Stock#1 | unit_price | numeric.negative | 1 | 1 | yes | no |
| Stock#1 | unit_price | storage.number_as_text | 1 | 1 | yes | no |
| Suppliers | (row) | row.duplicate | 1 | 1 | yes | no |
| Suppliers | rating | missing.empty | 2 | 2 | yes | no |
| Suppliers | rating | missing.marker | 1 | 1 | yes | no |
| Suppliers | supplier_id | key.duplicate | 1 | 1 | yes | no |

Coverage: Stock#1: 21/22 scenarios in 60 rows (full coverage needs 5 rows packed, 23 with one scenario per row); Stock#2: 0/0 scenarios in 4 rows (full coverage needs 0 rows packed, 0 with one scenario per row); Suppliers: 4/4 scenarios in 41 rows (full coverage needs 3 rows packed, 4 with one scenario per row); Archive: 0/0 scenarios in 3 rows (full coverage needs 0 rows packed, 0 with one scenario per row).

Planted classes not found again in Anonimizer's output: xlsx.formula_cell in Stock#1.total.

Not generated (formulas are inventoried only; the generated cell holds a plain value): cell computed by a formula.

Self-check on the generated file: 25 covered scenarios found again, 0 not found again.

Privacy assessment: passed, tier LOCAL_ONLY (singling out: passed, linkability: passed_with_residual_risk, inference: passed, source leakage: passed).

Scenario Manifest (25 entries), first entries:

| Scenario | Column | Data rows | Location |
|---|---|---|---|
| key value occurring a given number of times (occurrences per value: 3+) | supplier_id | 2 21 30 | C5; C24; C33 |
| spreadsheet error value (code: #VALUE!) | total | 3 | H6 |
| boolean written in a different style (style: yes_no:lower) | active | 6 | G9 |
| category value that occurs very rarely | description | 9 | B12 |
| key value occurring a given number of times (occurrences per value: 1) | supplier_id | 10 | C13 |
| empty cell | received | 11 | F14 |
| spreadsheet error value (code: #N/A) | qty | 15 | D18 |
| date stored as text in a date column | received | 18 | F21 |
| number written in a different format from the rest of the column (format: dec_comma) | unit_price | 20 | E23 |
| number stored as text in a numeric column | qty | 24 | D27 |
| date-shaped value that is not a real calendar date (format: Y-M-D) | received | 27 | F30 |
| literal missing-value marker (literal: TBD) | qty | 28 | D31 |

First rows of the synthetic file (fictional values):

```
Do consequat amet
sku | description | supplier_id | qty | unit_price | received | active | total |  |  | code | meaning
ETI-19753 | Cacetog nurez | 39 | 92 | 51.25 | 45015 | 1 | 24254.41 |  |  | A | Bekehemajib
UPU-56313 | Gbepul imehi | 64 | 530 | 852.5700000000001 | 44827 | 1 | 29722.46 |  |  | R | Jehipasanomotu
NOS-44719 | Gbepul imehi | 23 | 94 | 743 | 44776 | 1 | #VALUE! |  |  | L | Mimelipipej
EGI-81865 | Uuruzi otu | 23 | 216 | 11.22 | 44759 | 1 | 95079.03 |  |  | G | Lebogugecoteruli
ANU-25122 | Slejone acomu | 47 | 210 | 275.36 | 44381 | 1 | 845573.03
ZOC-76314 | Slejone acomu | 5 | 613 | 866.49 | 45271 | yes | 53192.84
AZU-95045 | Uuruzi otu | 47 | 863 | 561.78 | 44968 | 1 | 20224.32
EPA-29949 | Slejone acomu | 55 | 596 | 655.05 | 44476 | 1 | 92354.12
UNE-49509 | Oiluvu lekit | 67 | 974 | 745.3099999999999 | 45060 | 1 | 723526.6899999999
NOH-52424 | Vukeza leke | 24 | 275 | 641.6900000000001 | 44241 | 1 | 51303.53
```

## What this does and does not show

- It shows that the detector finds anomalies nobody listed in the request, including one text value in a numeric column placed at 97.5 % of the file, and that the generator reproduces their pattern classes.
- It shows what a schema-driven generator misses when the anomalies lie outside its sample. A baseline given an explicit list of anomalies would reproduce them; the point is that someone has to know them first.
- The fixtures were written by the same author as the detector. Agreement on them is evidence that the listed classes work, not that every anomaly in real files will be found.
- The judge for all three columns is Anonimizer's own profiler. A class it cannot see is invisible here.
- Class-level presence does not mean equal frequency. The output is a test dataset, not a statistical sample.
- A green privacy assessment means the listed checks behaved as specified on these files. It is not a certification and not proof of legal anonymity.
