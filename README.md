# Generic Engineering PDF + STEP Dimension Verification Agent

MVP v0.1 — Streamlit application

## What it does
1. Extracts dimension-like text from text-based PDF drawings.
2. Reads STEP geometry using OpenCascade (OCP).
3. Builds a geometry inventory from:
   - overall X/Y/Z bounding-box spans
   - cylindrical face diameters
4. Normalizes units between mm and inch.
5. Compares PDF numeric candidates against compatible geometry inventory entries.
6. Exports comparison, extracted-dimension, and STEP-inventory CSV reports.

## Important engineering limitation
This MVP does **not** establish which PDF annotation belongs to which specific model edge, hole, view, datum, or feature. A `CANDIDATE MATCH` is only a numeric match in the available geometry inventory. `NOT MATCHED` is a discrepancy candidate and `REVIEW` means no direct comparison is implemented. Do not use this tool as the sole basis for product acceptance or manufacturing release.

The PDF parser requires extractable text. Scanned drawings and outlined/vectorized dimension text need OCR/vector interpretation, which is not included in v0.1.

## Run locally (Windows)
Install Python 3.10 or 3.11 (recommended), then open Command Prompt in this folder:

```bat
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
streamlit run app.py
```

Open the local URL printed in the terminal (usually http://localhost:8501).

## Deploy online with Streamlit Community Cloud
1. Extract this ZIP.
2. Upload `app.py`, `requirements.txt`, and `README.md` to the **root** of a GitHub repository.
3. Ensure the branch is `main`.
4. In Streamlit Community Cloud, create an app using that repository, branch `main`, and main file path `app.py`.
5. Deploy. The first build may take several minutes because the STEP geometry dependency is substantial.

If deployment fails while installing `cadquery-ocp`, use a Python 3.11 environment and review the Streamlit build logs. OCP wheels are platform/Python-version dependent.

## PDF parser patterns
The parser looks for common text forms:
- `Ø10`, `⌀10`, `%%c10`, `DIA 10`
- `R5`, `RAD 5`
- `90°`, `90 DEG`
- `25 ±0.2`
- `100 mm`, `2.5 in`

It may also find unrelated numbers. Review the extracted text context.

## Unit handling
The user must select PDF units and STEP model units. The app assumes the STEP importer reports geometry in the model units as stored by the STEP file/exporter. Confirm units from the originating CAD export settings.

## Next production development steps
- OCR and vector-graphics dimension extraction.
- Dimension-line and arrowhead detection.
- Orthographic view segmentation and view-to-model registration.
- Feature association (hole-to-cylinder, radius-to-arc/fillet, linear dimension-to-edge/face pair).
- Datum coordinate systems and GD&T interpretation.
- Multi-solid/assembly component mapping and native CAD metadata.
- Test suite with known-good and known-bad drawing/model pairs.
- Human approval, traceable audit log, controlled rules and revision management.
