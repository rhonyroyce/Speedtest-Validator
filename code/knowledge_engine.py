"""Knowledge engine — loads and queries the 4 structured knowledge modules.

Aggregates RF parameter rules, throughput benchmarks, KPI mappings, and MOP
thresholds into a unified query interface. Does NOT use RAG/vector DB — all
lookups are direct Python dict access (~1ms vs ~260ms for RAG).

Implementation: Claude Code Prompt 5 (Knowledge Engine)
"""
# TODO: Implement KnowledgeEngine class with:
# - __init__(config) — load config, initialize knowledge modules
# - load_all() — load thresholds from Excel, initialize all knowledge dicts
# - get_rf_observation(param, value, **context) — generate observation text
# - get_throughput_context(tech, mimo, bw_mhz, direction) — theoretical peaks
# - get_kpi_impacts(rf_data) — evaluate RF against KPI rules
# - get_threshold(mimo_config, bw_lte, bw_nr_c1, bw_nr_c2, conn_mode) — speed test threshold
# - build_analysis_context(cell_data) — assemble full context dict for LLM prompt injection
#
# Dependencies:
#   - code/knowledge/rf_parameters.py
#   - code/knowledge/throughput_benchmarks.py
#   - code/knowledge/kpi_mappings.py
#   - code/knowledge/mop_thresholds.py
#   - code/config.py (for Excel paths)
