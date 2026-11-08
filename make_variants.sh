#!/bin/bash
# usage: make_variants.sh <stem> <last_page>   -- extra OCR readings of every page, used to repair cells
stem=$1; last=$2
python3 ocr_race_pages.py $stem 1 $last 300 6 &
python3 ocr_race_pages.py $stem 1 $last 150 6 &
python3 ocr_race_pages.py $stem 1 $last 250 4 &
python3 ocr_race_pages.py $stem 1 $last 400 6 &
wait
python3 ocr_race_pages.py $stem 1 $last 300 6 c &
python3 ocr_race_pages.py $stem 1 $last 400 6 c &
python3 ocr_race_pages.py $stem 1 $last 200 6 c &
wait
