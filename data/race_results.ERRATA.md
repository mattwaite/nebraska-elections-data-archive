# ERRATA: `race_results.csv`

Read this before using the dataset. It records the schema, what is and is not covered, every judgment call
and every known limitation. **This dataset is partial: 21 of 26 elections, and only statewide, federal and
legislative offices.** The coverage section says exactly which, and why.

## What the dataset is

County-level results for each race, from the "Federal Offices" and "State Offices" sections of the Secretary
of State canvass books (archived in `pdfs/`). The books print each race as a wide table with candidates as
column headings; this file has one row per election × race × jurisdiction × candidate. 50,299 rows,
977 races.

| column | meaning |
|---|---|
| `election_date`, `election_type` | as in the other datasets (`primary` or `general`) |
| `race_id` | stable identifier for one race: date, office, district, term, party ballot, recount flag |
| `office` | standardized office (list below) |
| `office_level` | `federal`, `state` or `legislative` |
| `office_as_printed` | the title line the book used |
| `district` | `District 3`, or empty for statewide offices. Words and leading zeros are normalized ("District Three", "District 03" → `District 3`). For `President`, a district value means the by-congressional-district tabulation |
| `district_inferred` | `True` where the book prints no district label for a U.S. House race and I assigned the one congressional district whose counties (taken from the labelled House races in the same book) contain all of the race's counties. This affects the 2002 and 2004 primaries and some Democratic and Libertarian House primaries in 2018-2024. Treat these districts as inferred, not printed |
| `term` | `Two Year Term`, `Four Year Term`, `Six Year Term`, or empty when the book doesn't say |
| `primary_ballot` | for primaries, the party whose nomination the race decides (`Republican`, `Democratic`, `Libertarian`, `Nonpartisan`); empty in general elections |
| `voter_group` | only in the 2002, 2004 and 2012 primaries, which print each partisan race once for registered party voters and again for nonpartisans who took that party's ballot: `Republican voters`, `Democratic voters`, `Libertarian voters`, `Green voters`, `Nebraska Party voters`, `Nonpartisan voters (Republican ballot)`, and so on. **These are separate tables of the same race; a candidate's full vote is the sum of the two groups** (the book prints no combined county table). Empty everywhere else |
| `is_recount` | `True` for the separate recount table some books print (2022 primary Legislative District 18). Recounts are separate races in this file; don't add them to the original |
| `jurisdiction` | county name, or `Total` for the race total |
| `jurisdiction_type` | `county` or `race_total` |
| `partial_county_precincts` | when a county is split between districts the book writes "Sarpy (57 precincts)"; this is that number |
| `candidate` | candidate name as printed, with the party label and the winner mark removed. Presidential tickets are one candidate ("Donald J. Trump & JD Vance") |
| `party` | the candidate's party as printed (`Republican`, `Democratic`, `Libertarian`, `By Petition`, ...); empty for nonpartisan offices (Legislature, Regents, State Board of Education) and write-ins. **In primaries, where the book prints no per-candidate party, it is set to the `primary_ballot`** |
| `candidate_as_printed` | the heading text for that column, kept so you can re-derive the above |
| `is_write_in` | `True` for "Write-In Scatterings" rows. These are the sum of all write-in votes, not a person |
| `winner` | `True`/`False` only in the 2024 general, the one book that marks winners (a check mark). **Empty in every other election; empty means unknown, not "lost"** |
| `votes` | votes |
| `ocr_derived` | `True` for a cell in a scanned book whose value was not the main OCR reading: it was repaired from another OCR reading or a high-resolution re-read of that one cell, or solved as the one unknown in a column whose Total is known. In every case the column then adds up to the printed Total. 17 cells in the 2006 general |
| `total_derived` | `True` for 57 rows where the book prints no Total row (see below) |

**`Total` is a row, not a column.** To get a race result, filter `jurisdiction_type == "race_total"`. Never
sum across `jurisdiction` without excluding `Total`, and never sum across `candidate` rows of different
`race_id`.

## Offices included

`President`, `U.S. Senate`, `U.S. House`, `Governor`, `Lieutenant Governor`, `Secretary of State`, `Auditor of
Public Accounts`, `State Treasurer`, `Attorney General`, `Public Service Commissioner`, `Legislature`,
`State Board of Education`, `University Regents`. (Governor and Lieutenant Governor are one ticket in the
books, so there are no `Lieutenant Governor` rows.)

**Not included:** judicial retention, community college boards, school and Educational Service Unit boards,
Natural Resources Districts, public power and utility districts, reclamation districts, learning community
boards, and ballot measures. Special elections are not in the archive at all.

## Coverage

Included (every check passes, apart from the five source issues listed below):

2002 primary; 2004 primary and general; 2006 general; 2008 general; 2010 primary and general; 2012 primary and general; 2014
primary and general; 2016, 2018, 2020, 2022 and 2024 primaries and generals.

**Not yet included**, and why:

| election | reason |
|---|---|
| 2000 primary and general, 2002 general, 2006 primary | scanned images. The reading pipeline exists (below) and the 2006 general is done with it, but these four need much more hand correction: the 2006 primary prints each race several times by kind of voter in dense side-by-side tables; the 2002 general scan is shaded and OCR is poor; the 2000 books are 195 and 339 pages |
| 2008 primary | the U.S. House pages interleave a continuing county list in the right column with new tables in the left; the text-position parser mis-groups them and 23 candidate totals fail validation |

Nothing from those books is in the CSV. Their absence says nothing about the results.

## How it was built

1. **Find tables from the grid lines.** In 2010 and later (and the 2002 primary) every result table is drawn
   with thin rectangles. Connected groups of them are the tables, and their vertical lines are the column
   edges, so a candidate's header words and a county's numbers land in the same column by position.
   (Candidate names are centred over their columns and numbers are right-aligned, so matching by text
   position alone is unreliable.) A page can hold up to a dozen tables side by side and stacked.
2. **Group tables into races.** A table without a candidate header continues the previous one; so does one
   with the same candidates and no new district label. A table that prints the same county list with different
   candidates (2010 primary) is more candidate columns of the same race. The office comes from the title
   above, the district and term from the labels above or inside the table.
3. **Parse candidates.** Names, parties in parentheses or on a following line, the winner mark, and
   write-in columns; summary sub-columns ("Dem / NP / Total", "Republican Votes ...") are dropped and the
   Total sub-column is the candidate's vote.
4. **Validate** (`extract_races.py`; the CSV is not written unless everything passes): each candidate's
   county rows sum to the race Total; exactly one Total per candidate; no county appears twice in a race.
5. 2004 and 2008 (and the occasional half page elsewhere) have no grid; their tables are found from the word
   "County" in each header and the names are matched to columns by a small dynamic program.
6. Where one grid holds several different tables (2010 general State Board of Education and Regents pages),
   the tables are read from text positions instead.
7. Where a page has result rows outside any grid (2016 general, half-page tables), `race_text_tables.py` reads
   them from text positions instead.

## Corrections to earlier releases

Three defects in the first published versions of this file were found and fixed:

* **2010 general:** a ballot measure (For / Against) was filed under `State Treasurer`; those 188 rows are removed.
* **Voter groups:** a label fragment such as "Democratic Party" in 2014-2024 primaries was mistaken for a voter-group
  heading, giving those races a spurious `voter_group` (and a different `race_id`). `voter_group` is now empty
  outside the 2002, 2004 and 2012 primaries.
* **District labels:** side-by-side tables share one line of labels ("District Fifteen   District Seventeen"), and some
  were given their neighbour's district (2016 and 2010 legislative and Regents races, 2024 House primaries). Labels
  are now matched to tables by position, and I checked that no two different races share a `race_id`.

## Scanned books (2006 general)

The 2006 general book is a scan with no text layer. How it was read:

1. Every page was OCR'd with tesseract (`ocr_race_pages.py`) into word boxes, and read by the same table parser as the
   text books (`ocr_pages.py` presents OCR words as a page). Digit look-alikes inside numbers are repaired and
   near-miss county names are snapped to the real county; a cell that is not a number is marked unreadable.
2. Seven more OCR readings of every page (other resolutions and a version with the ruling lines erased) are used to
   repair cells: a column that does not add up to its Total is fixed only by replacing one to three cells with values
   other readings gave, if exactly one choice makes the column add up. A high-resolution re-read of the individual cells
   is a further source. A county row lost under a heavy underline is restored only if the column then adds up.
3. Pages the parser could not structure (stacked small tables: the Legislature, State Board of Education and
   Regents pages, and U.S. House District 3) were **transcribed by hand from the page images**
   (`corrections/races_2006_general.txt`). Each transcribed column was checked against its printed Total, and all of
   them matched. A few candidate names the OCR garbled were corrected by hand (`corrections/races_2006_general.json`).

Residual risk: a mis-read digit that the sum check cannot see (two offsetting errors in one column) would survive;
and candidate names read by OCR on the non-transcribed pages (statewide races, Senate, House Districts 1 and 2,
Governor) were checked by eye against the images but not exhaustively.

## Judgment calls

* **Single-county races print no Total.** When a district lies within one county the book omits the Total
  row. The county row is copied as the Total with `total_derived = True` (57 rows).
* **`Total` for a district means the district.** A race that spans parts of several counties is the sum of
  those county parts (`partial_county_precincts` shows when a county is split; the books write it as "(31 precincts)" or "/31 prec").
* **2012 and 2014 primaries** print each candidate with Rep/Dem/NP/Total sub-columns or by voter group. For
  2014 the `Total` sub-column is the candidate's vote and the breakdown by registration is not kept; for 2012
  the voter groups are kept as `voter_group`.
* **Summary tables** ("Totals" by voter group) are skipped; they hold no county rows.
* **Primary `party`** is filled from the ballot, not from the book (the book prints it only in the section
  title).
* **Winner:** see above. I did not compute winners from the votes, because ranked and multi-seat rules differ.
* **District and term labels are normalized**; `office_as_printed` keeps the title.
* **Write-in rows** are kept as ordinary rows with `is_write_in = True`.

## Source inconsistencies (kept as printed)

| election | race | what the book prints |
|---|---|---|
| 2016 general | President, District 1, Jill Stein & Ajamu Baraka | county rows sum to 3,375, printed Total is 3,374 |
| 2016 primary | President, Libertarian, John McAfee | county rows sum to 124, printed Total is 123 |
| 2002 primary | U.S. Senate, Democratic ballot, nonpartisan voters, Charlie A. Matulka | county rows sum to 562, printed Total is 561 |
| 2014 primary | Auditor of Public Accounts, Republican, Charlie Janssen | county rows sum to 93,262, printed Total is 93,212 |
| 2016 primary | University Regents District 7, Bob Phares | county rows sum to 35,549, printed Total is 33,549 (a digit may be wrong in the Total or in a county; not resolved) |

## Limits

* **Column assignment of names is not independently checked.** The sum checks catch a wrong number, a missing
  row and a wrong table. They cannot catch two adjacent candidates' names being swapped. I checked this on the
  2024 general (where the winner mark must be on the top vote-getter: all 44 races) and spot-checked other
  years against the PDFs, but I did not hand-verify every name.
* **Completeness is checked by census, not proof.** I tabulated races per office per election and looked for
  gaps. A race the parser never found would not trigger a sum failure.
* **Ballot-measure, judicial and local races are absent** (see above).
* **Candidate identity is the printed name.** The same person can be spelled differently across years; there
  is no candidate ID.
* **Over- and undervotes are not in the books.** These are votes for candidates only.

## Reproducing

```
python3 extract_races.py            # report for every text-layer book
python3 extract_races.py --write    # rebuild data/race_results.csv (fails unless the published books pass)
```
Requires `pdfplumber`. `PUBLISH` in `extract_races.py` lists the elections written to the CSV.
