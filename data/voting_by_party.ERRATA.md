# ERRATA: `voting_by_party.csv`

Read this before using the dataset. It records every judgment call, source quirk and known limitation in
the extraction. Companion datasets: `voter_registration.csv`, `voting_by_method.csv` (see their ERRATA files).

## What the dataset is

Ballots cast in each **primary election, 2000–2024** (13 elections), by county and by the party category
the voter appears under, from the "Total Voting by Party" table of each Secretary of State canvass book
(archived in `pdfs/`). One row per election × jurisdiction × party. 7,426 rows.

**Primary elections only.** General-election books have no by-party table (general ballots are not party
ballots), so there are no general-election rows.

| column | meaning |
|---|---|
| `election_date` | ISO date of the election |
| `election_type` | always `primary` (kept for consistency with the other datasets) |
| `jurisdiction` | county name, or `Statewide` |
| `jurisdiction_type` | `county` or `state` |
| `party` | party category (below); `Total` is the printed total |
| `party_as_printed` | the column heading the book used; `(footnote only)` where a count appears only in a footnote |
| `count` | ballots cast |

**Do not sum across `party` without excluding `Total`, and do not sum across `jurisdiction` without
excluding `Statewide`.**

## What the party categories mean (read this)

* **Each count is a category of *voter*, as the book labels it; the books do not say whether it means the
  voter's registration or the ballot they cast.** Through 2022 the two coincide in practice only to the extent
  the book's categories do: e.g. `Nonpartisan` voters received a nonpartisan ballot (state and local
  nonpartisan offices) unless a party opened its primary to them. I have not independently verified, for
  every year, whether any party's column includes nonpartisan-registered voters who took that party's ballot.
* **2024 is different and has extra categories.** The book's table adds four columns marked with an
  asterisk, "Nonpartisan Republican*, Nonpartisan Democratic*, Nonpartisan Libertarian*, Nonpartisan Legal
  Marijuana NOW*". The footnote says the Democratic, Libertarian and Legal Marijuana NOW parties opened their
  2024 primaries to nonpartisans (Neb. Rev. Stat. §32-912), and that for the Republican Party nonpartisans
  could vote only for U.S. Senate and U.S. House. In this dataset these are
  `Nonpartisan (Republican ballot)`, `Nonpartisan (Democratic ballot)`, `Nonpartisan (Libertarian ballot)`
  and `Nonpartisan (Legal Marijuana NOW ballot)`. The 2024 `Nonpartisan` category is the book's
  "Nonpartisan (no party ballot)". All nine 2024 categories are additive: they sum to the printed Total.
  **To compare Republican turnout across years, decide whether to include the 2024
  "Nonpartisan (Republican ballot)" voters** (who could vote only in two federal races); the 2024
  `Republican` column alone is the closest like-for-like with earlier years.
* **The set of parties differs by election** (e.g. Green and Nebraska parties in 2002–2008; Americans Elect
  in 2012; Natural Law in 2000; Legal Marijuana NOW from 2022). A party a book doesn't print has no rows.
* Party names are standardized: "Democrat" → `Democratic`; the older "Nebraska" party is `Nebraska Party`.

## How it was built

* **2002 through 2024 primaries (11 elections):** text-layer PDFs; `extract_voting_by_party.py` locates
  columns by header position. The 2024 table's header is wrapped across many lines, so its ten column
  positions are fixed in the script from the page.
* **2000 and 2006 primaries (2 elections):** scanned images. OCR candidates (`ocr_voting_by_party.py`; the
  2000 table is shared with `ocr_voting_by_method.py`) were accepted only if the party columns summed
  exactly to the printed Total and the county had a single consistent candidate; every other county was
  transcribed by hand from the page image (`corrections/party_<election>.csv`, which always wins).
  `build_scanned_voting_by_party.py` assembles them.

## Validation performed

Per election: 93 counties; each row's parties sum to its `Total`; county rows sum to `Statewide` for
every party; no two counties with identical numbers (this caught OCR attaching Sarpy's numbers to Saunders
in the 2006 primary, fixed by hand). All 13 elections pass, except the source inconsistency below.

## Source inconsistencies and special cases

* **2014 primary:** the statewide Republican figure is printed as 225,212 but the county rows sum to
  225,214, and the statewide row's parties sum to 324,225 against a printed Total of 324,227 (2 off, which
  would be explained if the statewide Republican figure were 225,214). Values kept as printed.
* **Footnote-only parties**, added as separate rows (zero for every other county, which is implied because
  the columns then reconcile to Total):
  * 2002 primary: `Green`, Douglas 4 ("Douglas county had 4 voters from the Green party"). The Total
    includes them.
  * 2000 primary: `Reform Party`, Sarpy 4 ("Sarpy County had 4 registered voters with the Reform party
    vote in the Primary"). The Total includes them. (The 2000 book's registration table has a separate
    Reform Party footnote of 55; see the registration ERRATA.)
* **2000 primary, Dawson County:** `Nonpartisan` is printed as 0 (the row still sums to its Total).
* **Totals row label** varies ("Statewide Total", "Totals", "TOTAL"); all are `Statewide`.
* **Column order varies by year** (e.g. Total first in 2002–2012 books); this does not affect the data.

## Residual risk

For the two scanned books, an OCR-accepted row could in principle hold an error that is offset elsewhere;
the county-to-statewide check makes this very unlikely, but the accepted rows were not each re-read against
the image. Hand-transcribed rows were each checked against their printed Total.

## Reproducing

```
python3 extract_voting_by_party.py   # rebuilds data/voting_by_party.csv, prints validation
```
Requires `pdfplumber`; the scanned elections also read `data/ocr_raw_party/`, `data/ocr_raw_method/` and
`corrections/party_*.csv`. Re-running the OCR scripts (needs `tesseract`, `pdftoppm`, Pillow, numpy)
regenerates OCR candidates but not the hand corrections.
