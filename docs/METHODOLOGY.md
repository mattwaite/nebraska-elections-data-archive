# Methodology

How the canvass-book PDFs became tidy CSVs. For the specifics and caveats of each dataset, see its
`data/*.ERRATA.md`.

## Principles

* **Tidy, not display.** The books are laid out for printing: wide tables, parties or methods as columns,
  totals as the last column or row. The CSVs have one row per election × jurisdiction × category, and
  `Total` / `Statewide` are ordinary values.
* **Topic by topic, not year by year.** The layout of a table changes from year to year, but what it
  measures does not. Each topic is extracted across all years into one file.
* **Keep what was printed.** Category names are standardized (for example "Absentee" and "Early Voting"
  become `Early/Absentee`), but the original heading is kept in a `*_as_printed` column. Where the source
  contradicts itself, the printed value is kept and the contradiction is documented.
* **Every dataset ships with an ERRATA file.**

## Text-layer PDFs

The extractors use `pdfplumber` word positions rather than table detection:

1. Group words into lines by vertical center.
2. Treat a line as a data row if it starts with a county name followed by numbers.
3. Locate columns from header-word x-positions.
4. Assign each row's numbers to columns. Blank cells (such as "All Mail Precincts" for counties without
   any) are resolved by an order-preserving assignment, constrained so the row sums to its printed total.
   Continuation pages without headers reuse the positions from pages that have them.
5. Merge digits the PDF splits apart ("1", "4" → 14) and fix the letter O printed for zero.

## Race results

Races are the hardest topic: a page holds up to a dozen small tables, laid out in two columns, with candidate
names wrapped over several lines above each. The extractor (`extract_races.py`) works in layers:

1. **Tables from grid lines** (`race_blocks.py`). In 2010 and later each table is drawn with thin rectangles.
   Connected groups of them are the tables and their vertical lines are the column edges. Header words and
   numbers are assigned to columns by those edges, which is more reliable than text position (names are
   centred over a column, numbers right-aligned).
2. **Tables from text positions** (`race_text_tables.py`) for pages with no grid. Header names are cut into
   one group per column by a small dynamic program that matches each group to the column's centre or right
   edge.
3. **Races from tables.** A table without candidate headings continues the previous table; so does one with the
   same candidates and no new district label; a table with the same counties but different candidates adds
   columns to the same race.
4. **Office, district, term** come from the title lines above each table (first the table's half of the page,
   then the full-width lines).
5. **Validation:** county rows must sum to the race Total for every candidate, with one Total per candidate and
   no duplicate counties. The CSV is only written for elections that pass.

**Scanned books** (race results) add an OCR layer: `ocr_race_pages.py` turns each page into word boxes,
`ocr_pages.py` cleans digits and county names and hands them to the same parser, further OCR readings of the same
pages (`make_variants.sh`) and per-cell high-resolution re-reads (`cell_ocr.py`) repair cells until each column adds
up to its printed Total, and pages the parser cannot structure are transcribed by hand
(`corrections/races_<book>.txt`) and checked the same way. `review_races.py` lists what still fails.

Because some layouts need page-specific handling, the CSV includes only the elections that pass; the ERRATA
lists the rest.

## Scanned PDFs

The 2000 primary and general, 2002 general, and 2006 primary and general books are images. For each:

1. Render the page at several resolutions (120, 150, 200 and 300 dpi) and OCR it with `tesseract`, as whole
   pages and as individual row bands.
2. Keep every distinct reading as a candidate row (`data/ocr_raw*/`).
3. Accept a candidate only if its columns sum exactly to the printed total *and* the county has one
   consistent candidate.
4. Transcribe every remaining county by hand from the page image into `corrections/`. A correction always
   overrides OCR.

OCR sometimes attaches one county's numbers to a neighboring county's name. The duplicate-row check below
exists because that happened and was caught.

## Validation

Run on every election, and failing any of them fails the build:

* 93 counties.
* Each row's categories sum to its printed `Total`.
* County rows sum to the `Statewide` row for each category.
* No two counties (with a total over 500) have identical numbers.

Precinct counts are also summed against the statewide figure, but a mismatch there is a warning, because
the source itself disagrees in places.

Known source inconsistencies are listed in the extractor (`KNOWN_SOURCE_ISSUES`) and in the ERRATA. They are
reported as warnings, not failures, and the values are kept as printed.

## Limits

* A scanned-book row accepted from OCR could in principle hold an error that is offset elsewhere in the
  row. The county-to-statewide check makes this unlikely, but accepted rows were not each re-read against
  the image. Hand-transcribed rows were each checked against their printed total.
* Blank cells on headerless continuation pages (2014 and 2016, voting by method) are placed by inference.
  The total check cannot distinguish placements.
* Category standardization is a judgment. The books do not define their terms.
