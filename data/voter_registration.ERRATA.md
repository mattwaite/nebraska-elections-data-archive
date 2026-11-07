# ERRATA: `voter_registration.csv`

Read this before using the dataset. It records every judgment call, source quirk and known limitation in
the extraction, so a later researcher doesn't have to rediscover them.

## What the dataset is

Registered voters by county and party for every Nebraska **primary and general election, 2000–2024**
(26 elections), taken from the "Number of Registered Voters" table in each Nebraska Secretary of State
canvass book (the "Official Results" PDFs at <https://sos.nebraska.gov/previous-elections>, archived in
`pdfs/`). One row per election × jurisdiction × party. 14,471 rows.

| column | meaning |
|---|---|
| `election_date` | ISO date of the election |
| `election_type` | `primary` or `general` |
| `jurisdiction` | county name, or `Statewide` |
| `jurisdiction_type` | `county` or `state` |
| `precincts` | number of precincts as printed (repeated on each party row; **empty** where the book prints none, see below) |
| `party` | party name, or `Total` |
| `count` | registered voters |

**Do not sum across `party` without excluding `Total`, and do not sum across `jurisdiction` without
excluding `Statewide`.** Both are stored as ordinary rows so that a single filter returns them.
`precincts` must never be summed across `party` rows.

These are the counts printed in the canvass book for that election, i.e. the registration snapshot the
state used for that election, not a single date-stamped statewide file.

## How it was built

* **2002 primary through 2024 general (21 elections):** the PDFs have a text layer.
  `extract_voter_registration.py` locates each table's columns by the x-position of the header words and
  assigns each number to a column.
* **2000 primary, 2000 general, 2002 general, 2006 primary, 2006 general (5 elections):** the PDFs are
  scanned images. Rows were read with OCR (`ocr_registration.py`); an OCR row was accepted only if its
  party counts summed exactly to its printed Total. Every other row was **transcribed by hand from the
  page image** and stored in `corrections/<election>.csv`, which always overrides OCR
  (`build_scanned_registration.py`). Raw OCR candidates are kept in `data/ocr_raw/`.

## Validation performed

For every election: exactly 93 counties; each row's party counts sum to its `Total`; the county rows sum to
the `Statewide` row for every party column and for `Total`. All 26 elections pass, except the items listed
below under "Source inconsistencies". Precinct counts are checked the same way (county sum vs. statewide)
and reported as warnings.

Residual risk, scanned books only: an OCR row that passed the checks could still hold an error that is
offset elsewhere. The county-to-statewide check makes this very unlikely, but those rows were not each
re-read against the page image. Precinct counts on OCR rows are **not** covered by the per-row sum check;
they are only covered by the statewide precinct check (which caught three misreads, fixed).

## Choices made in normalizing

* **Party names are standardized across years.** "Democrat" → `Democratic`. The older "Nebraska" party is
  `Nebraska Party`, to keep it distinct from `No Labels Nebraska` (2024 general). Other names used:
  `Republican`, `Libertarian`, `Nonpartisan`, `Legal Marijuana NOW`, `Green`, `Natural Law`,
  `Americans Elect`, `Reform Party`, `Last Party`.
* **The set of parties differs by election**, matching the printed table. A party absent from a book has
  no rows for that election (it is not zero-filled).
* **Blank cells are stored as 0.** Some books leave a cell empty rather than printing 0. Every such case
  was confirmed by the row's party counts summing to its Total.
* **Statewide row label.** The books call it "Statewide Total", "Totals", "TOTAL", "Grand Total", etc.;
  all are `Statewide`.
* **Election dates** were checked against the cover or header of each book, except the 2004 general
  (Nov 2, 2004), whose book has no extractable date text; it is the known statutory date.
* **Footnote asterisks** on county names (e.g. `Douglas*`) were removed.

## Source inconsistencies and gaps (values are as printed unless stated)

* **2014 primary: no statewide row.** The book prints no statewide total in this table. The dataset has
  county rows only for that election; no total was computed.
* **Precinct totals that don't add up in the source:** 2014 general (counties sum to 1,371, statewide row
  prints 1,367) and 2010 primary (counties sum to 1,635, statewide prints 1,634). Values kept as printed.
* **`precincts` is empty** for the 2000 general, 2008 general, 2010 general and 2012 general, because those
  tables have no precincts column.
* **Parties reported only in footnotes**, added as separate rows; for all other counties these parties are
  recorded as 0, which is implied because the columns then reconcile to Total:
  * 2002 primary: `Green`, Douglas 25, Sarpy 1 (statewide 26). The Total includes them.
  * 2002 general: `Green`, Douglas 143, Sarpy 12 (statewide 155); `Last Party`, Johnson 2. "Last Party" is
    the name as printed in the footnote and may be a typo in the source. Totals include them.
  * 2000 primary: `Reform Party`, Sarpy 55. The Total includes them.
* **2000 general, Sarpy footnote not used.** The footnote says 55 voters are registered Reform Party, but
  the printed Total (71,106) equals the other parties' sum without them, so they are *not* in the dataset
  for this election.
* **Split digits in the 2010 general PDF** (e.g. "1" and "4" printed separately for 14) were rejoined; the
  affected rows now reconcile (Buffalo, Lancaster).
* **Hand-read cells:** OCR confused several digits in the scans (a 2000 primary Dixon Republican cell is
  smudged in the scan; 2,084 was inferred from the row sum and checked against the statewide total).

## Reproducing

```
python3 extract_voter_registration.py   # rebuilds data/voter_registration.csv, prints validation
```
Requires `pdfplumber`; the scanned elections also read `data/ocr_raw/` and `corrections/`. Re-running
`ocr_registration.py` (needs `tesseract`, `pdftoppm`, Pillow, numpy) regenerates OCR candidates but not the
hand corrections.
