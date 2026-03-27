"""Tests for causal_dag.py — 5-tier causal DAG loader, traversal, and formatting.

Tests:
1. test_load_dag_from_json — 123 nodes, 159 edges from JSON
2. test_tier_assignment — nodes have correct tier labels
3. test_activate_from_measurements — RF failures activate correct nodes
4. test_trace_root_causes — backward traversal finds chains
5. test_trace_downstream_effects — forward traversal finds KPI impacts
6. test_deduplicate_impacts — dedup keeps longest path
7. test_get_matching_playbooks — activated nodes match playbooks
8. test_format_for_llm — formatted output is non-empty and structured
"""
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from code.knowledge.causal_dag import CausalDAG, CausalEdge, CausalNode, load_dag

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


@pytest.fixture
def config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


@pytest.fixture
def dag(config):
    return CausalDAG(config)


# === Loading tests ===


class TestLoadDag:
    def test_load_dag_from_json(self, config):
        """Verify load_dag() parses all 123 nodes and 159 edges from the JSON."""
        nodes, edges = load_dag(config)
        assert len(nodes) >= 123, f"Expected >=123 nodes, got {len(nodes)}"
        assert len(edges) >= 159, f"Expected >=159 edges, got {len(edges)}"

    def test_tier_assignment(self, dag):
        """Nodes have correct tier labels (T1-T4 from prefix, T5 for K_ prefix)."""
        # T1 node
        assert "T1_VSWR" in dag.nodes
        assert dag.nodes["T1_VSWR"].tier == "T1"

        # T2 node
        assert "T2_RSRP" in dag.nodes
        assert dag.nodes["T2_RSRP"].tier == "T2"

        # T5 node (K_ prefix)
        t5_nodes = [n for n in dag.nodes.values() if n.tier == "T5"]
        assert len(t5_nodes) > 0, "Expected T5 KPI nodes"
        for n in t5_nodes:
            assert n.id.startswith("K_"), f"T5 node {n.id} should start with K_"


# === Activation tests ===


class TestActivation:
    def test_activate_from_measurements_rf_fail(self, dag):
        """RF failures activate correct T2 nodes."""
        measurements = {
            "rsrp": -85,   # Below -75 threshold
            "sinr": 15,    # Below 25 threshold
            "rsrq": -5,    # Within range — should NOT activate
            "tx_power": -10,  # Negative — should NOT activate
        }
        activated = dag.activate_from_measurements(measurements)
        assert "T2_RSRP" in activated, "Low RSRP should activate T2_RSRP"
        assert "T2_SINR" in activated, "Low SINR should activate T2_SINR"
        assert "T2_RSRQ" not in activated, "In-range RSRQ should not activate"

    def test_activate_from_measurements_throughput_fail(self, dag):
        """Boolean pass/fail flags activate corresponding nodes."""
        measurements = {
            "dl_pass": False,
            "ul_pass": True,
        }
        activated = dag.activate_from_measurements(measurements)
        assert "T2_MIMO_RANK" in activated, "DL fail should activate T2_MIMO_RANK"
        assert "T2_TX_POWER" not in activated, "UL pass should not activate T2_TX_POWER"

    def test_activate_from_measurements_physical_fail(self, dag):
        """Physical layer failures activate T1 nodes."""
        measurements = {
            "vswr_pass": False,
            "rssi_hot_pass": False,
        }
        activated = dag.activate_from_measurements(measurements)
        assert "T1_VSWR" in activated
        assert "T1_RSSI_HOT" in activated

    def test_activate_all_passing(self, dag):
        """All-passing measurements should activate nothing (or minimal borderline)."""
        measurements = {
            "rsrp": -55,    # Well within -75 to -50
            "sinr": 35,     # Well above 25
            "rsrq": -6,     # Within -12 to -3
            "tx_power": -15,
            "dl_pass": True,
            "ul_pass": True,
        }
        activated = dag.activate_from_measurements(measurements)
        # Should not activate any core RF nodes
        assert "T2_RSRP" not in activated
        assert "T2_SINR" not in activated
        assert "T2_DL_TPUT" not in activated


# === Traversal tests ===


class TestTraversal:
    def test_trace_root_causes(self, dag):
        """Backward traversal from T2_SINR should find T1 root causes."""
        activated = {"T2_SINR"}
        chains = dag.trace_root_causes(activated)
        assert len(chains) > 0, "Should find at least one root cause chain for SINR"

        # At least one chain should trace back to a T1 node
        root_tiers = {c["root_tier"] for c in chains}
        assert "T1" in root_tiers, f"Expected T1 root cause, got tiers: {root_tiers}"

    def test_trace_downstream_effects(self, dag):
        """Forward traversal from T1_VSWR should find downstream effects."""
        # First activate relevant nodes so forward traversal can follow
        activated = {"T1_VSWR", "T2_RSRP", "T2_SINR"}
        downstream = dag.trace_downstream_effects("T1_VSWR", activated)
        assert len(downstream) > 0, "VSWR should have downstream effects"


# === Deduplication tests ===


class TestDeduplicate:
    def test_deduplicate_impacts(self, dag):
        """Dedup keeps longest path when same root_cause→symptom pair exists."""
        chains = [
            {
                "symptom": "T2_SINR",
                "symptom_name": "SINR",
                "root_cause": "T1_PIM",
                "root_cause_name": "PIM",
                "path": ["T2_SINR", "T1_PIM"],
                "root_tier": "T1",
                "symptom_tier": "T2",
            },
            {
                "symptom": "T2_SINR",
                "symptom_name": "SINR",
                "root_cause": "T1_PIM",
                "root_cause_name": "PIM",
                "path": ["T2_SINR", "T1_RTWP", "T1_PIM"],
                "root_tier": "T1",
                "symptom_tier": "T2",
            },
        ]
        deduped = dag.deduplicate_impacts(chains)
        assert len(deduped) == 1, "Should collapse to single chain"
        assert len(deduped[0]["path"]) == 3, "Should keep the longest path"


# === Playbook tests ===


class TestPlaybooks:
    def test_get_matching_playbooks(self, dag):
        """Activated T1_VSWR should match the VSWR playbook."""
        activated = {"T1_VSWR"}
        playbooks = dag.get_matching_playbooks(activated)
        assert len(playbooks) >= 1, "Should match at least 1 playbook for VSWR"

        titles = [pb.get("title", "") for pb in playbooks]
        assert any(
            "VSWR" in t for t in titles
        ), f"Expected VSWR playbook, got: {titles}"

    def test_no_playbooks_when_passing(self, dag):
        """Empty activated set should return no playbooks."""
        playbooks = dag.get_matching_playbooks(set())
        assert len(playbooks) == 0


# === Formatting tests ===


class TestFormatting:
    def test_format_for_llm_with_chains(self, dag):
        """Formatted output should be non-empty and structured."""
        chains = [
            {
                "symptom": "T2_SINR",
                "symptom_name": "SINR",
                "root_cause": "T1_VSWR",
                "root_cause_name": "VSWR / Return Loss Alarm",
                "path": ["T2_SINR", "T1_PIM", "T1_VSWR"],
                "root_tier": "T1",
                "symptom_tier": "T2",
            },
        ]
        output = dag.format_for_llm(chains)
        assert "Causal Chain Analysis" in output
        assert "VSWR" in output
        assert "Chain 1" in output

    def test_format_for_llm_no_chains(self, dag):
        """Empty chains should return a 'no issues' message."""
        output = dag.format_for_llm([])
        assert "normal range" in output.lower() or "no causal" in output.lower()
