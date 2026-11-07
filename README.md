# Nebraska Elections Data Archive

Nebraska's Secretary of State publishes past election results as canvass-book PDFs: page after page of
display-formatted tables, some of them scans of paper. This project archives those PDFs and converts the
tables into **tidy, analysis-ready long CSVs**, one file per topic, with every election from 2000 to 2024
combined into each file.

The archive covers who was registered, how people voted, which party's primary they voted in, and, for 20 of
the 26 elections so far, who got how many votes in each county for statewide, federal and legislative
races.

## The datasets

| file | what it holds | elections | rows |
|---|---|---|---|
| [`data/voter_registration.csv`](data/voter_registration.csv) | Registered voters by county and party, plus number of precincts | 26 (13 primary, 13 general) | 14,471 |
| [`data/voting_by_method.csv`](data/voting_by_method.csv) | Ballots cast by county and method (polling place, early/absentee, mail, provisional, military/overseas, new/former resident) | 26 | 12,784 |
| [`data/voting_by_party.csv`](data/voting_by_party.csv) | Ballots cast in each primary, by county and party category | 13 (primaries only) | 7,426 |
| [`data/race_results.csv`](data/race_results.csv) | Votes by county and candidate for President, U.S. Senate and House, statewide offices, the Legislature, Regents and the State Board of Education | **20 of 26** (2002 primary; 2004 primary and general; 2008 general; 2010-2024 primary and general) | 48,138 |

Each dataset has an **ERRATA file next to it** (`data/<name>.ERRATA.md`). Read it before you analyze the
data. It records the schema, the method, every judgment call, every inconsistency in the source, and every
hand correction.

**Race results are partial.** Judicial retention, local contests and ballot measures are not included, and
6 elections are not in the file yet (2000, 2002 general, 2006, 2008 primary). The ERRATA lists each
one and why. A missing election means "not done", not "no data".

### Shape of the data

The data is long: one row per election × jurisdiction × category. `Total` and `Statewide` are ordinary
values, so a filter is all it takes to pull them.

```
election_date,election_type,jurisdiction,jurisdiction_type,precincts,party,count
2000-05-09,primary,Statewide,state,1777,Republican,517347
2000-05-09,primary,Statewide,state,1777,Democratic,381155
```

Common columns:

| column | meaning |
|---|---|
| `election_date` | ISO date of the election |
| `election_type` | `primary` or `general` |
| `jurisdiction` | county name (93 counties) or `Statewide` |
| `jurisdiction_type` | `county` or `state` |
| `party` / `method` | the category; the value `Total` is the printed total |
| `*_as_printed` | the heading the book used, so you can undo or refine my standardization |
| `count` | the number |

Race results add `race_id`, `office`, `district`, `candidate`, `party` and `votes`, with the race total as a
`Total` row (`jurisdiction_type == "race_total"`). Per-dataset columns and caveats are in the ERRATA files. The two rules that apply everywhere:

* **Don't sum across `party` or `method` without excluding `Total`.**
* **Don't sum across `jurisdiction` without excluding `Statewide`.**

### Examples

Statewide U.S. Senate results, 2024 general:

```python
import pandas as pd
rr = pd.read_csv("data/race_results.csv")
q = rr[(rr.election_date == "2024-11-05") & (rr.office == "U.S. Senate") & (rr.jurisdiction_type == "race_total")]
print(q[["term", "candidate", "party", "votes"]])
```

Total registered voters in Lancaster County, every general election:

```python
import pandas as pd
df = pd.read_csv("data/voter_registration.csv")
q = df[(df.jurisdiction == "Lancaster") & (df.party == "Total") & (df.election_type == "general")]
print(q[["election_date", "count"]])
```

## How reliable is it?

Every election is validated, and the checks are the reason to trust the data:

* All 93 counties are present.
* Each row's categories sum to its printed `Total`.
* County rows sum to the `Statewide` row for every category.
* No two counties have identical numbers (this catches OCR attaching one county's numbers to its neighbor).

Race results are additionally checked so that each candidate's county rows sum to the race total. Text-based
PDFs were parsed from their text layer. The **scanned books (2000 primary and general, 2002 general, 2006 primary and general)** were read with OCR.
A row was accepted from OCR only if its columns summed to the printed total and the county had a single
consistent reading. Every other row was **transcribed by hand from the page image** (the files in
[`corrections/`](corrections/) always override OCR).

Where the state's own tables disagree with themselves, the value is **kept as printed** and the
discrepancy is documented. There is one deliberate exception: a printed −258 early-voting count in Kimball
County (2006 general), stored as 258 because the printed total and the statewide column both require it.
See [`data/voting_by_method.ERRATA.md`](data/voting_by_method.ERRATA.md).

See [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) for the full approach.

## Repository layout

```
pdfs/                      the 26 source canvass books (general and primary, 2000-2024)
manifest.csv               source URL, file size and SHA-256 of every PDF
data/                      the tidy CSVs and their ERRATA files
  ocr_raw*/                cached OCR candidates for the scanned books
corrections/               hand transcriptions that override OCR
download_pdfs.py           fetches the PDFs from sos.nebraska.gov
extract_*.py               one extractor per topic; each rebuilds its CSV and prints validation
race_blocks.py, race_text_tables.py   table finders used by extract_races.py (grid lines; text positions)
ocr_*.py, build_scanned_* OCR passes and assembly for the scanned books
docs/METHODOLOGY.md        how extraction and validation work
```

## Reproducing

```bash
pip install -r requirements.txt
python3 download_pdfs.py                # only if you want to re-fetch the PDFs
python3 extract_voter_registration.py
python3 extract_voting_by_method.py
python3 extract_voting_by_party.py
python3 extract_races.py --write
```

Each extractor prints the validation results and rewrites its CSV. Re-running the OCR scripts also needs
`tesseract` and `pdftoppm` (poppler). It regenerates OCR candidates but not the hand corrections.

## Source

All PDFs come from the Nebraska Secretary of State's
[Previous Elections](https://sos.nebraska.gov/previous-elections) page. `manifest.csv` lists the exact URL
and checksum of each file. The Secretary of State's office is the authority on these numbers; this project
only restructures them. If you find an error, please open an issue with the election, county and page.

## Roadmap

* Race results for the remaining 6 elections: the 2008 primary needs more parser work; 2000, 2002 general and 2006
  are scans that need OCR and hand correction.
* Ballot measures, judicial retention and local contests.
* Special elections, which this project does not yet cover.

## License

* Code: [MIT](LICENSE).
* Data (`data/`, `corrections/`): [CC0](LICENSE-DATA.md), public domain.
* The source PDFs in `pdfs/` are public records published by the State of Nebraska and are not covered by
  either license.
