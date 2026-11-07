# ERRATA: `voting_by_method.csv`

Read this before using the dataset. It records every judgment call, source quirk and known limitation in
the extraction. (The companion dataset is `voter_registration.csv`; see `voter_registration.ERRATA.md`.)

## What the dataset is

Ballots cast, by county and by method of voting, for every Nebraska **primary and general election,
2000–2024** (26 elections), from the "Total Voting by Method / Location" table in each Secretary of State
canvass book (archived in `pdfs/`). One row per election × jurisdiction × method. 12,784 rows.

| column | meaning |
|---|---|
| `election_date` | ISO date of the election |
| `election_type` | `primary` or `general` |
| `jurisdiction` | county name, or `Statewide` |
| `jurisdiction_type` | `county` or `state` |
| `method` | standardized method name (below); `Total` is the printed total |
| `method_as_printed` | the column heading the book used (the 2000–2006 scanned books: as read from the page image) |
| `in_total` | `FALSE` if this method's count is **not** included in the printed `Total` (see 2018) |
| `count` | ballots cast |

**Do not sum across `method` without excluding `Total`, and without excluding rows where `in_total` is
`FALSE`; do not sum across `jurisdiction` without excluding `Statewide`.**

## Standardized methods

| `method` | what the books call it |
|---|---|
| `Polling Place` | At Polls, At the Polls, Polling Place, Voters at the Polls, Total at Polls |
| `Early/Absentee` | Early Voting, Early Voters, Absentees, (EV) Absentees, Absentee Voters, Early Voting/Absentees |
| `All Mail Precincts` | All Mail Precincts, Mail Precincts |
| `Provisional` | Provisional, Provisional Ballot |
| `Military & Overseas` | Military & Overseas, Military/Overseas, Military, Military Early Voters (2010 general) |
| `New/Former Resident` | New/Former Resident, New & Former Resident |
| `Total` | Total Voting |

**These mappings are my judgment.** "Absentee" (older books) and "Early Voting" (newer books) are combined
as `Early/Absentee`, and "Military Early Voters" is treated as `Military & Overseas`. The books do not
define the terms, so whether these are strictly the same category across 25 years is not established;
`method_as_printed` lets you undo or refine the grouping. The set of methods differs by election (the
number of available methods grew over time, and a few appear in only some books); a method a book doesn't
print has **no rows** for that election.

## How it was built

* **2002 primary through 2024 general (21 elections):** text-layer PDFs; `extract_voting_by_method.py`
  locates columns by header position on each page.
* **2000 primary, 2000 general, 2002 general, 2006 primary, 2006 general (5 elections):** scanned images.
  Rows were read with OCR (`ocr_voting_by_method.py`) and accepted only if the method columns summed
  exactly to the printed Total *and* the county had a single consistent candidate; every other county was
  **transcribed by hand from the page image** (`corrections/method_<election>.csv`, which always
  overrides OCR). Raw OCR candidates are in `data/ocr_raw_method/`.
  `build_scanned_voting_by_method.py` assembles them.

## Validation performed

Per election: 93 counties; each row's methods sum to its `Total` (except the 2018 military column, below);
county rows sum to `Statewide` for every method; no two counties with identical numbers (guards against
OCR attaching one county's numbers to its neighbour's name; this happened for 2 counties in the 2000
general and was caught and fixed). All 26 elections pass, except the source inconsistencies listed below.

## Blank cells

The books leave "All Mail Precincts" (and sometimes other cells) blank for counties that have none. Blanks
are stored as `0` *only* when the row's other cells sum exactly to the printed Total, which was confirmed
for every row. Where a blank could be placed in more than one column (continuation pages with no header),
the placement used was the one matching the column positions on pages with headers or the most commonly
blank column. This matters only for 2016 and 2014; the Total check cannot distinguish placements, so
those rows rest on that inference.

## Source inconsistencies and special cases

* **2018 primary and general: `Military & Overseas` is not in the printed Total.** In every county the
  Total equals Polling Place + All Mail Precincts + Provisional + Early/Absentee exactly. The military
  count therefore seems to be a subset already counted elsewhere (probably in Early Voting), but the book
  doesn't say. It is stored as printed with `in_total = FALSE`. In other years it is additive.
* **2016 primary:** county rows sum to 244,745 Polling Place / 58,744 Early/Absentee, but the statewide row
  prints 244,744 / 58,745. Values kept as printed.
* **2002 primary, Clay County:** Early/Absentee is printed as 10, but the printed Total (1,914) and the
  statewide column (13,861 vs. the counties' sum of 13,771) both imply 100. **Kept as printed (10)**; it
  is very likely a typo in the source.
* **2014 primary, Kimball County:** "Military/Overseas" is printed with a letter O ("O") instead of a
  zero. Read as `0`; consistent with the row total (519 + 3 + 104 = 626).
* **2006 general, Kimball County:** Early Voting is printed as **−258**. The printed Total (1,670 = 1,411 +
  1 + 258) and the statewide column show it should be +258. **Stored as 258**, deliberately not as printed.
  This is the one place the dataset overrides a printed value; confirmed on the page image.
* **2000 general:** the table is "Number of People Voting" and counts New/Former Resident voters for the
  *presidential* race only (noted on the page). Only the method columns are in this dataset.
* **2000 primary:** the printed table combines party and method columns in one table. Only the method
  columns (At the Polls, Military Overseas, Absentee) and Total are in this dataset; the party columns
  belong to a separate "voting by party" topic. A footnote says 4 Sarpy County voters voted a Reform Party
  ballot; that isn't a method and is not recorded here.
* **Totals row label** varies by book ("Statewide Total", "Totals", "TOTAL", "Grand Total", "Statewide");
  all are `Statewide`.
* **Election dates** are shared with the registration dataset (verified against each book; see that ERRATA).
* **Counts are ballots cast, not voters registered**, and are not the same as the turnout of each office:
  ballots cast for specific races can be lower (undervotes) or, for some local contests, a different
  population.

## Residual risk

For the scanned books, an OCR-accepted row could in principle hold an error that is offset elsewhere;
the county-to-statewide check makes this very unlikely, but the accepted rows were not each re-read
against the image. Hand-transcribed rows were each checked against their printed Total.

## Reproducing

```
python3 extract_voting_by_method.py   # rebuilds data/voting_by_method.csv, prints validation
```
Requires `pdfplumber`; the scanned elections also read `data/ocr_raw_method/` and `corrections/method_*.csv`.
Re-running `ocr_voting_by_method.py` (needs `tesseract`, `pdftoppm`, Pillow, numpy) regenerates OCR
candidates but not the hand corrections.
