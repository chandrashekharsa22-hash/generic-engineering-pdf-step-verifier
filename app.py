import re
import math
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st
import fitz  # PyMuPDF

st.set_page_config(page_title="Engineering PDF + STEP Verifier", page_icon="📐", layout="wide")
st.title("📐 Generic Engineering PDF Dimension Verification Agent")
st.caption("MVP v0.1 • PDF annotation extraction + STEP geometry inventory + candidate comparison")

st.warning(
    "Engineering review tool only. This MVP extracts dimension-like text from PDF and compares numeric "
    "values with a limited inventory of measurable STEP geometry (overall bounding-box spans and cylindrical "
    "diameters). It does not yet associate each annotation with its exact drawing view, datum, edge, hole, "
    "or feature. Therefore results are candidate matches, not proof of conformity. All findings require "
    "drawing/geometry review before manufacturing release."
)

# ---------- PDF extraction ----------
DIM_PATTERNS = [
    # Diameter and radius symbols, common Unicode and ASCII variants
    ("Diameter", re.compile(r"(?:Ø|⌀|%%c|DIA\.?\s*)\s*([+-]?\d+(?:\.\d+)?)", re.I)),
    ("Radius", re.compile(r"(?:R\s*|RAD\.?\s*)([+-]?\d+(?:\.\d+)?)", re.I)),
    # Explicit angular dimensions
    ("Angle", re.compile(r"([+-]?\d+(?:\.\d+)?)\s*(?:°| DEG\b)", re.I)),
    # Plus/minus tolerance dimensions such as 25.0 ±0.2
    ("Linear", re.compile(r"(?<![\w.])([+-]?\d+(?:\.\d+)?)\s*(?:±|\+/-)\s*\d+(?:\.\d+)?", re.I)),
    # General numeric dimensions, optionally followed by units
    ("Linear", re.compile(r"(?<![\w.])([+-]?\d+(?:\.\d+)?)\s*(?:mm\b|cm\b|inch\b|in\b)", re.I)),
]

def extract_pdf_dimensions(pdf_bytes):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    rows = []
    for page_no, page in enumerate(doc, start=1):
        text = page.get_text("text") or ""
        for kind, pattern in DIM_PATTERNS:
            for m in pattern.finditer(text):
                value = float(m.group(1))
                context = text[max(0, m.start()-55):min(len(text), m.end()+55)].replace("\n", " ")
                rows.append({
                    "Page": page_no,
                    "Type": kind,
                    "Value": value,
                    "Context": re.sub(r"\s+", " ", context).strip(),
                    "Source": "PDF text"
                })
    # De-duplicate identical detections on the same page/type/value/context
    seen, unique = set(), []
    for row in rows:
        key = (row["Page"], row["Type"], round(row["Value"], 6), row["Context"])
        if key not in seen:
            seen.add(key)
            unique.append(row)
    return unique, doc.page_count

# ---------- STEP geometry extraction ----------
def extract_step_geometry(step_path):
    try:
        from OCP.STEPControl import STEPControl_Reader
        from OCP.IFSelect import IFSelect_ReturnStatus
        from OCP.TopAbs import TopAbs_SOLID, TopAbs_FACE
        from OCP.TopExp import TopExp_Explorer
        from OCP.Bnd import Bnd_Box
        from OCP.BRepBndLib import BRepBndLib
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        from OCP.GeomAbs import GeomAbs_Cylinder
    except Exception as exc:
        raise RuntimeError(
            "STEP geometry engine could not load. Install dependencies from requirements.txt. "
            f"Underlying error: {exc}"
        )

    reader = STEPControl_Reader()
    status = reader.ReadFile(str(step_path))
    if status != IFSelect_ReturnStatus.IFSelect_RetDone:
        raise RuntimeError("The STEP reader could not read this file. Check that it is a valid .step/.stp file.")
    reader.TransferRoots()
    shape = reader.OneShape()
    if shape.IsNull():
        raise RuntimeError("No usable geometry was found in the STEP file.")

    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box)
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    spans = [
        ("Overall X span", abs(xmax-xmin), "Bounding box"),
        ("Overall Y span", abs(ymax-ymin), "Bounding box"),
        ("Overall Z span", abs(zmax-zmin), "Bounding box"),
    ]

    features = []
    for name, value, source in spans:
        if value > 1e-8:
            features.append({"Feature type": "Overall span", "Feature": name, "Value (model units)": value, "Source": source})

    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    cyl_index = 0
    while explorer.More():
        face = explorer.Current()
        try:
            surface = BRepAdaptor_Surface(face, True)
            if surface.GetType() == GeomAbs_Cylinder:
                radius = surface.Cylinder().Radius()
                if radius > 1e-8:
                    cyl_index += 1
                    features.append({
                        "Feature type": "Cylinder diameter",
                        "Feature": f"Cylindrical face {cyl_index} diameter",
                        "Value (model units)": 2.0 * radius,
                        "Source": "STEP cylindrical surface"
                    })
        except Exception:
            pass
        explorer.Next()

    return features, {
        "X span": xmax-xmin, "Y span": ymax-ymin, "Z span": zmax-zmin,
        "Solid bounding box": f"X {xmin:.4f}..{xmax:.4f}, Y {ymin:.4f}..{ymax:.4f}, Z {zmin:.4f}..{zmax:.4f}"
    }

# ---------- UI ----------
left, right = st.columns(2)
with left:
    st.subheader("1. Engineering drawing")
    pdf_file = st.file_uploader("Upload dimensioned PDF", type=["pdf"])
with right:
    st.subheader("2. Reference 3D model")
    step_file = st.file_uploader("Upload STEP model (.step / .stp)", type=["step", "stp"])

st.subheader("3. Verification settings")
c1, c2, c3 = st.columns(3)
with c1:
    pdf_unit = st.selectbox("PDF drawing units", ["mm", "inch"], index=0)
with c2:
    step_unit = st.selectbox("STEP model units", ["mm", "inch"], index=0)
with c3:
    tolerance = st.number_input("Comparison tolerance", min_value=0.0001, value=0.05, step=0.01, format="%.4f",
                                help="Absolute comparison tolerance in the selected normalized unit.")
st.caption("The STEP importer normally returns geometry in the STEP file's model units. Confirm the units from the source CAD/export settings.")

if st.button("Extract and compare dimensions", type="primary", use_container_width=True):
    if not pdf_file or not step_file:
        st.error("Upload both a PDF drawing and a STEP model to run verification.")
    else:
        try:
            with st.spinner("Reading PDF annotations and STEP geometry..."):
                pdf_rows, page_count = extract_pdf_dimensions(pdf_file.getvalue())
                suffix = Path(step_file.name).suffix.lower()
                if suffix not in [".step", ".stp"]:
                    raise RuntimeError("Reference model must be a .step or .stp file.")
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    tmp.write(step_file.getvalue())
                    step_path = Path(tmp.name)
                try:
                    model_features, bbox = extract_step_geometry(step_path)
                finally:
                    step_path.unlink(missing_ok=True)

            if pdf_unit == "inch" and step_unit == "mm":
                pdf_factor, model_factor = 25.4, 1.0
                normalized_unit = "mm"
            elif pdf_unit == "mm" and step_unit == "inch":
                pdf_factor, model_factor = 1.0, 25.4
                normalized_unit = "mm"
            elif pdf_unit == "inch" and step_unit == "inch":
                pdf_factor, model_factor = 1.0, 1.0
                normalized_unit = "inch"
            else:
                pdf_factor, model_factor = 1.0, 1.0
                normalized_unit = "mm"

            model_df = pd.DataFrame(model_features)
            if not model_df.empty:
                model_df["Value (normalized)"] = model_df["Value (model units)"] * model_factor

            st.success(f"STEP geometry loaded. PDF pages: {page_count}. Measurable model features: {len(model_features)}.")
            st.subheader("4. STEP model geometry inventory")
            st.write(bbox["Solid bounding box"])
            st.dataframe(model_df, use_container_width=True, hide_index=True)

            st.subheader("5. Extracted PDF dimension candidates")
            if not pdf_rows:
                st.warning("No dimension-like text was extracted. The PDF may be scanned, vector text may be outlined, or annotations may use an unsupported notation. OCR and manual review are needed.")
                pdf_df = pd.DataFrame(columns=["Page","Type","Value","Context","Source"])
            else:
                pdf_df = pd.DataFrame(pdf_rows)
                pdf_df["Value (normalized)"] = pdf_df["Value"] * pdf_factor
                st.dataframe(pdf_df, use_container_width=True, hide_index=True)

            st.subheader("6. Candidate comparison")
            results = []
            for row in pdf_rows:
                val = float(row["Value"]) * pdf_factor
                kind = row["Type"]
                if kind == "Diameter":
                    candidates = model_df[model_df["Feature type"] == "Cylinder diameter"] if not model_df.empty else pd.DataFrame()
                elif kind == "Linear":
                    candidates = model_df[model_df["Feature type"] == "Overall span"] if not model_df.empty else pd.DataFrame()
                else:
                    candidates = pd.DataFrame()

                if candidates.empty:
                    status = "REVIEW"
                    best = None
                    delta = None
                    note = "No directly comparable extracted STEP feature for this annotation type."
                else:
                    diffs = (candidates["Value (normalized)"] - val).abs()
                    idx = diffs.idxmin()
                    best = candidates.loc[idx, "Feature"]
                    delta = float(diffs.loc[idx])
                    if delta <= tolerance:
                        status = "CANDIDATE MATCH"
                        note = "Numeric value matches an available geometry candidate; feature/view association is not proven."
                    else:
                        status = "NOT MATCHED"
                        note = "No candidate in the selected geometry class is within the configured tolerance."
                results.append({
                    "PDF page": row["Page"], "Dimension type": kind, "PDF value": row["Value"],
                    "Normalized value": val, "Closest STEP feature": best,
                    "STEP value": (float(candidates.loc[idx, "Value (normalized)"]) if best is not None else None),
                    "Absolute difference": delta, "Status": status, "Finding": note,
                    "PDF text context": row["Context"]
                })

            result_df = pd.DataFrame(results)
            if result_df.empty:
                st.info("No extracted dimensions were available for comparison.")
            else:
                matched = int((result_df["Status"] == "CANDIDATE MATCH").sum())
                notmatched = int((result_df["Status"] == "NOT MATCHED").sum())
                review = int((result_df["Status"] == "REVIEW").sum())
                m1,m2,m3 = st.columns(3)
                m1.metric("Candidate matches", matched)
                m2.metric("Not matched", notmatched)
                m3.metric("Manual review", review)
                st.dataframe(result_df, use_container_width=True, hide_index=True)

            st.subheader("7. Download inspection report")
            if not result_df.empty:
                st.download_button("Download comparison report CSV", result_df.to_csv(index=False).encode("utf-8"),
                                   "pdf_step_dimension_comparison.csv", "text/csv")
            if not model_df.empty:
                st.download_button("Download STEP geometry inventory CSV", model_df.to_csv(index=False).encode("utf-8"),
                                   "step_geometry_inventory.csv", "text/csv")
            if not pdf_df.empty:
                st.download_button("Download extracted PDF dimensions CSV", pdf_df.to_csv(index=False).encode("utf-8"),
                                   "pdf_extracted_dimensions.csv", "text/csv")

            st.info(
                "Interpretation: CANDIDATE MATCH means the value was found somewhere in the selected geometry inventory, "
                "not that the specific drawing dimension is correctly attached to the intended feature. NOT MATCHED is "
                "a discrepancy candidate, not an automatic rejection. REVIEW means the feature type cannot be compared "
                "by this MVP. Verify view, datum, orientation, dimension type, units, and tolerances manually."
            )
        except Exception as exc:
            st.error(f"Verification could not be completed: {exc}")
            st.exception(exc)

with st.expander("Supported in this MVP / known limitations"):
    st.markdown("""
    **Supported**
    - Text-based PDF dimension candidate extraction for common diameter, radius, angle, tolerance and unit suffix patterns.
    - STEP model bounding-box X/Y/Z spans.
    - Cylindrical face diameters from STEP geometry.
    - Unit normalization between mm and inch.
    - CSV inspection outputs.

    **Not yet supported**
    - OCR of scanned PDFs or text converted to vector outlines.
    - Associating a PDF annotation to a particular view, edge, hole, datum, or feature.
    - Exact radius/angle/position verification, GD&T, threads, hole patterns, ordinate dimensions, or geometric tolerances.
    - Native SolidWorks/Inventor files, assemblies with component-level traceability, or automatic drawing markup.
    - Automatic pass/fail certification.

    **Recommended production workflow:** use this as a triage tool, then add view registration, feature recognition, datum/coordinate mapping, GD&T interpretation, and a human approval step.
    """)

st.caption("Version 0.1 • Candidate comparison only • Do not use as the sole basis for manufacturing acceptance.")
