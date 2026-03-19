"""Output Word document generator — creates RF_Throughput_Analysis.docx.

Generates a comprehensive RF analysis document with:
- Title page (site ID, date, analyst)
- Executive Summary (overall pass/fail, key findings)
- Site Configuration table (from CIQ)
- RF Parameter Deep Dive sections (per sector/tech)
- Summary tables (Band Config, Full Results, BLER Summary, BW vs Throughput, RX Chain)
- Glossary

References: MS2 KPI and Counters.xlsx for KPI domain context.

Implementation: Claude Code Prompt 8 (Output Generation)
"""
# TODO: Implement OutputDocxGenerator class with:
# - __init__(config) — load config, set output path, load template styles
# - generate(results, site_config, analysis_data) — create complete document
# - _add_title_page(doc, site_id, date) — formatted title page
# - _add_executive_summary(doc, results) — pass/fail summary, key metrics
# - _add_site_config_table(doc, ciq_data) — CIQ-derived configuration table
# - _add_rf_deep_dive(doc, sector_data) — per-sector RF parameter analysis
# - _add_summary_tables(doc, results) — Band Config, Results, BLER, BW, RX Chain tables
# - _add_glossary(doc) — RF/telecom terminology
# - _apply_styles(doc) — consistent formatting (fonts, heading styles, table styles)
#
# Document sections (matching SFY0803A_RF_Throughput_Analysis.docx structure):
#   1. Title Page
#   2. Executive Summary
#   3. Site Configuration
#   4. RF Parameter Analysis (per sector)
#   5. Throughput Analysis (per sector)
#   6. Summary Tables
#   7. KPI Correlation Summary
#   8. Glossary
#
# Dependencies:
#   - python-docx
#   - code/config.py (for output path, document metadata)
#   - code/knowledge/rf_parameters.py (for observation templates)
