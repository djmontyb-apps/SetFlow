
# SetFlow v0.9

SetFlow is a small Streamlit prototype for DJ playlist sequencing.

It orders a playlist using:
- Camelot-key compatibility
- BPM compatibility
- optional half/double-time matching
- energy flow
- same-artist spacing

## Required spreadsheet columns

`Title`, `Artist`, `BPM`, `Camelot Key`, `Energy`

Other columns are preserved.

## Run on a Mac

1. Install Python 3.11 or newer.
2. Open Terminal in this folder.
3. Create a virtual environment (recommended):

   python3 -m venv .venv
   source .venv/bin/activate

4. Install dependencies:

   pip install -r requirements.txt

5. Start SetFlow:

   streamlit run app.py

Your browser should open automatically.

## First test

Upload `sample_salsa.csv` or your own Salsa XLSX file.

Suggested first settings:
- Balanced
- Key 60% / BPM 40%
- BPM tolerance 4
- Half/double tempo ON
- Energy flow Smooth
- Energy influence 15%
- Artist spacing Normal
- Optimization depth Standard

## Notes

This is a prototype. The scoring is deliberately transparent so it can be tuned by ear.
