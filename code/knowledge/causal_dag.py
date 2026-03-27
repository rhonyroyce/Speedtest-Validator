"""Causal DAG — 5-tier knowledge graph for root cause analysis.

Loads the causal_dag.json (T1 Physical → T2 RF → T3 Parameter → T4 Counter → T5 KPI)
and provides traversal methods for backward root-cause tracing, forward impact
propagation, playbook matching, and LLM prompt formatting.

Config-driven: all settings come from config.yaml `causal_dag` section.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class CausalNode:
    """Single node in the causal DAG."""

    id: str
    name: str
    tier: str
    raw: dict = field(repr=False, default_factory=dict)

    @property
    def tier_num(self) -> int:
        """Extract numeric tier (1-5) from id prefix like 'T2_SINR' or 'K_...' (T5)."""
        if self.id.startswith("K_"):
            return 5
        for i in range(1, 6):
            if self.id.startswith(f"T{i}_"):
                return i
        return 0


@dataclass
class CausalEdge:
    """Directed edge between two nodes."""

    from_id: str
    to_id: str
    relationship: str = ""
    mechanism: str = ""
    strength: str = ""
    raw: dict = field(repr=False, default_factory=dict)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_dag(config: dict) -> tuple[dict[str, CausalNode], list[CausalEdge]]:
    """Load causal_dag.json and parse into typed objects.

    Args:
        config: Full application config dict (reads ``causal_dag.path``
                or ``paths.causal_dag``).

    Returns:
        (nodes_by_id, edges) — dict of CausalNode keyed by id, list of CausalEdge.
    """
    dag_cfg = config.get("causal_dag", {})
    path = dag_cfg.get("path") or config.get("paths", {}).get("causal_dag", "")

    if not os.path.isabs(path):
        # Resolve relative to project root (two levels up from this file)
        project_root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        path = os.path.join(project_root, path)

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    nodes: dict[str, CausalNode] = {}
    edges: list[CausalEdge] = []

    # Parse T1-T4 nodes (flat arrays)
    for tier_key in ("nodes_T1", "nodes_T2", "nodes_T3", "nodes_T4"):
        tier_label = tier_key.replace("nodes_", "")  # e.g. "T1"
        for raw_node in data.get(tier_key, []):
            nid = raw_node.get("id", "")
            nodes[nid] = CausalNode(
                id=nid,
                name=raw_node.get("name", ""),
                tier=tier_label,
                raw=raw_node,
            )

    # Parse T5 nodes (nested under category keys like NR_ACCESS, NR_RETAIN, ...)
    t5_data = data.get("nodes_T5", {})
    if isinstance(t5_data, dict):
        for _category, node_list in t5_data.items():
            if not isinstance(node_list, list):
                continue
            for raw_node in node_list:
                nid = raw_node.get("id", "")
                nodes[nid] = CausalNode(
                    id=nid,
                    name=raw_node.get("name", ""),
                    tier="T5",
                    raw=raw_node,
                )

    # Parse edges (key is "edges" in JSON, "causal_edges" is metadata count)
    for raw_edge in data.get("edges", []):
        edges.append(
            CausalEdge(
                from_id=raw_edge.get("from", ""),
                to_id=raw_edge.get("to", ""),
                relationship=raw_edge.get("relationship", ""),
                mechanism=raw_edge.get("mechanism", ""),
                strength=raw_edge.get("strength", ""),
                raw=raw_edge,
            )
        )

    logger.info(
        "Loaded causal DAG: %d nodes, %d edges", len(nodes), len(edges)
    )
    return nodes, edges


# ---------------------------------------------------------------------------
# Measurement → node-id mapping
# ---------------------------------------------------------------------------

# Maps measurement keys (from cell_data / threshold_result) to T2 node ids
# and the condition under which that node is "activated" (i.e. anomalous).
_MEASUREMENT_ACTIVATION_MAP: dict[str, dict[str, Any]] = {
    # RF observables — activate when outside DAS antenna-end thresholds
    "rsrp": {"node": "T2_RSRP", "fail_below": -75, "fail_above": -40},
    "sinr": {"node": "T2_SINR", "fail_below": 25},
    "rsrq": {"node": "T2_RSRQ", "fail_below": -12, "fail_above": -3},
    "tx_power": {"node": "T2_TX_POWER", "fail_above": 0},
    # Throughput pass/fail — activates MIMO rank (most common RF cause of throughput issues)
    "dl_pass": {"node": "T2_MIMO_RANK", "activate_on_false": True},
    "ul_pass": {"node": "T2_TX_POWER", "activate_on_false": True},
    # Physical layer (T1) — detected from threshold_result
    "vswr_pass": {"node": "T1_VSWR", "activate_on_false": True},
    "rssi_hot_pass": {"node": "T1_RSSI_HOT", "activate_on_false": True},
    "rssi_cold_pass": {"node": "T1_RSSI_COLD", "activate_on_false": True},
    "rssi_imbalance_pass": {"node": "T1_RSSI_IMBALANCE", "activate_on_false": True},
    "fiber_loss_pass": {"node": "T1_FIBER_LOSS", "activate_on_false": True},
}


# ---------------------------------------------------------------------------
# CausalDAG class
# ---------------------------------------------------------------------------


class CausalDAG:
    """Config-driven causal DAG for root cause analysis."""

    def __init__(self, config: dict) -> None:
        self.config = config
        dag_cfg = config.get("causal_dag", {})
        self.max_depth: int = dag_cfg.get("max_chain_depth", 5)
        self.dedup_enabled: bool = dag_cfg.get("deduplicate_kpi_impacts", True)
        self.borderline_pct: float = dag_cfg.get("borderline_threshold_pct", 10)

        self.nodes, self.edges = load_dag(config)

        # Build adjacency indices
        self._forward: dict[str, list[CausalEdge]] = {}   # from → [edges]
        self._backward: dict[str, list[CausalEdge]] = {}  # to   → [edges]
        for edge in self.edges:
            self._forward.setdefault(edge.from_id, []).append(edge)
            self._backward.setdefault(edge.to_id, []).append(edge)

        # Load playbooks and chains from JSON
        self._playbooks: list[dict] = []
        self._chains: list[dict] = []
        self._load_extras(config)

    def _load_extras(self, config: dict) -> None:
        """Load playbooks and cross_domain_chains from the JSON file."""
        dag_cfg = config.get("causal_dag", {})
        path = dag_cfg.get("path") or config.get("paths", {}).get("causal_dag", "")
        if not os.path.isabs(path):
            project_root = os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            )
            path = os.path.join(project_root, path)

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self._playbooks = data.get("mitigation_playbooks", [])
        self._chains = data.get("cross_domain_chains", [])

    # ------------------------------------------------------------------
    # 1. activate_from_measurements
    # ------------------------------------------------------------------

    def activate_from_measurements(self, measurements: dict) -> set[str]:
        """Determine which DAG nodes are activated by the given measurements.

        Args:
            measurements: Merged dict of cell_data + threshold_result fields.

        Returns:
            Set of activated node IDs.
        """
        activated: set[str] = set()

        for key, rule in _MEASUREMENT_ACTIVATION_MAP.items():
            value = measurements.get(key)
            if value is None:
                continue

            node_id = rule["node"]
            if node_id not in self.nodes:
                continue

            # Boolean pass/fail flags
            if rule.get("activate_on_false"):
                if value is False:
                    activated.add(node_id)
                continue

            # Numeric threshold checks
            try:
                val = float(value)
            except (TypeError, ValueError):
                continue

            fail_below = rule.get("fail_below")
            fail_above = rule.get("fail_above")

            if fail_below is not None and val < fail_below:
                activated.add(node_id)
            if fail_above is not None and val > fail_above:
                activated.add(node_id)

            # Borderline detection
            if self.borderline_pct > 0:
                if fail_below is not None:
                    margin = abs(fail_below) * (self.borderline_pct / 100)
                    if fail_below <= val <= fail_below + margin:
                        activated.add(node_id)

        return activated

    # ------------------------------------------------------------------
    # 2. trace_root_causes (backward traversal)
    # ------------------------------------------------------------------

    def trace_root_causes(self, activated: set[str]) -> list[dict]:
        """Trace activated nodes backward to find root cause chains.

        Returns list of chain dicts with keys:
            symptom, root_cause, path (list of node IDs), edges (list of edge info),
            root_tier, symptom_tier.
        """
        chains: list[dict] = []

        for node_id in sorted(activated):
            paths = self._trace_backward(node_id, set(), 0)
            for path in paths:
                if len(path) < 2:
                    continue
                root_id = path[-1]
                root_node = self.nodes.get(root_id)
                symptom_node = self.nodes.get(node_id)
                chains.append({
                    "symptom": node_id,
                    "symptom_name": symptom_node.name if symptom_node else node_id,
                    "root_cause": root_id,
                    "root_cause_name": root_node.name if root_node else root_id,
                    "path": path,
                    "root_tier": root_node.tier if root_node else "",
                    "symptom_tier": symptom_node.tier if symptom_node else "",
                })

        return chains

    def _trace_backward(
        self, node_id: str, visited: set[str], depth: int
    ) -> list[list[str]]:
        """Recursively trace backward edges from node_id."""
        if depth >= self.max_depth or node_id in visited:
            return [[node_id]]

        visited = visited | {node_id}
        parents = self._backward.get(node_id, [])

        if not parents:
            return [[node_id]]

        all_paths: list[list[str]] = []
        for edge in parents:
            parent_paths = self._trace_backward(edge.from_id, visited, depth + 1)
            for p in parent_paths:
                all_paths.append([node_id] + p)

        return all_paths

    # ------------------------------------------------------------------
    # 3. trace_downstream_effects (forward traversal)
    # ------------------------------------------------------------------

    def trace_downstream_effects(
        self, root_id: str, activated: set[str]
    ) -> list[str]:
        """Trace forward from root_id, returning downstream node IDs that are activated.

        Only follows edges whose target is in the activated set OR is a T5 KPI node.
        """
        downstream: list[str] = []
        self._trace_forward(root_id, activated, set(), downstream, 0)
        return downstream

    def _trace_forward(
        self,
        node_id: str,
        activated: set[str],
        visited: set[str],
        result: list[str],
        depth: int,
    ) -> None:
        """Recursively trace forward edges."""
        if depth >= self.max_depth or node_id in visited:
            return

        visited = visited | {node_id}
        children = self._forward.get(node_id, [])

        for edge in children:
            child_id = edge.to_id
            child_node = self.nodes.get(child_id)
            # Follow edge if child is activated or is a T5 KPI
            is_kpi = child_node and child_node.tier == "T5"
            if child_id in activated or is_kpi:
                if child_id not in result:
                    result.append(child_id)
                self._trace_forward(child_id, activated, visited, result, depth + 1)

    # ------------------------------------------------------------------
    # 4. deduplicate_impacts
    # ------------------------------------------------------------------

    def deduplicate_impacts(self, chains: list[dict]) -> list[dict]:
        """Remove chains that share the same root cause, keeping the longest path."""
        if not self.dedup_enabled:
            return chains

        # Group by (root_cause, symptom) — keep longest path
        best: dict[tuple[str, str], dict] = {}
        for chain in chains:
            key = (chain["root_cause"], chain["symptom"])
            existing = best.get(key)
            if existing is None or len(chain["path"]) > len(existing["path"]):
                best[key] = chain

        # Further dedup: if multiple symptoms share the same root cause,
        # keep all but annotate
        return list(best.values())

    # ------------------------------------------------------------------
    # 5. get_matching_playbooks
    # ------------------------------------------------------------------

    def get_matching_playbooks(self, activated: set[str]) -> list[dict]:
        """Return playbooks whose entry_point is in the activated set.

        Also matches playbooks whose entry_point is a root cause of an
        activated node (one hop backward).
        """
        # Expand activated to include one-hop-back root causes
        expanded = set(activated)
        for node_id in activated:
            for edge in self._backward.get(node_id, []):
                expanded.add(edge.from_id)

        matching: list[dict] = []
        seen_titles: set[str] = set()

        for pb in self._playbooks:
            entry = pb.get("entry_point", "")
            title = pb.get("title", "")
            if entry in expanded and title not in seen_titles:
                matching.append(pb)
                seen_titles.add(title)

        return matching

    # ------------------------------------------------------------------
    # 6. format_for_llm
    # ------------------------------------------------------------------

    def format_for_llm(self, chains: list[dict]) -> str:
        """Format causal chains into a structured text block for LLM prompts.

        Returns a concise summary suitable for injection into prompt templates.
        """
        if not chains:
            return "No causal chains identified — all measurements within normal range."

        lines: list[str] = []
        lines.append(f"### Causal Chain Analysis ({len(chains)} chain(s) identified)\n")

        for i, chain in enumerate(chains, 1):
            path_str = " → ".join(chain["path"])
            lines.append(
                f"**Chain {i}**: {chain.get('root_cause_name', chain['root_cause'])} "
                f"→ {chain.get('symptom_name', chain['symptom'])}"
            )
            lines.append(f"  - Root Tier: {chain.get('root_tier', 'Unknown')}")
            lines.append(f"  - Full Path: {path_str}")
            lines.append("")

        return "\n".join(lines)
