# Branding assets

> **Protected assets.** Files here are used byte-for-byte in every generated report. Never edit, re-encode, crop,
> redraw or regenerate them in code.

## Header selection (18-Nov-2026)

`exporters.report_header_image()` picks the header for both Word and PDF reports:
- If `Header_CheckSphere.png`, `Header_CheckSphere.jpg` or `Header_CheckSphere.jpeg` exists in this folder, that
  file is used.
- Otherwise the legacy `aaditya_enterprise_header.jpg` is used, as a fallback only.

`Header_CheckSphere` has **not been supplied yet**. Place the owner's file here unchanged. Its SHA-256 is part of the
report cache key, so cached reports rebuild automatically. After the owner approves the new header, remove the
AADITYA fallback from `report_header_image()`.


## `aaditya_enterprise_header.jpg`

The AADITYA ENTERPRISE banner supplied by the business owner (709 × 133 px, JPEG). It is the **source of truth** for
the report header: logo, company name, address, telephone number and e-mail are taken from this image exactly as
supplied. The text is never re-typed or redrawn in code.

**Where it is used**

- Every generated Word report (`.docx`): `backend/exporters.py`, `_docx_apply_header()`, called by `build_case_docx()`.
  That is the only Word report builder. It serves `GET /api/exports/case/{case_id}/docx` for every case source
  (Super Admin / Supervisor created, imported, Allocate New Verification, agent Create New Verification).
  - The image sits in the Word **page header**, so it repeats on every page. It uses the same header on all pages,
    with no separate first-page header.
  - It is scaled to the full width between the page margins with its original aspect ratio, so it is never stretched.
  - The page's top margin is set to `header distance + banner height + 0.2 in`, so the report title and body always
    start below the banner and are never covered.
- PDF reports (`vee_report._render_pdf`) draw the same image at the top of every page, at the same width and aspect ratio.

**Replacing the artwork**

Replace this file with the new banner and keep the same file name. The size and proportions are read from the image
itself, so no code change is needed. Run `backend/tests/verify_three_updates.py` afterwards. It checks that the
exported Word header is byte-identical to this file, keeps its proportions, fits the margins and does not cover the
body.
