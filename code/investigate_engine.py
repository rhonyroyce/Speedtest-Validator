"""Investigate engine — optional agentic tool-calling loop for deep analysis.

NOT in the core pipeline. Activated via --investigate CLI argument.
Uses the analysis model with 3 tools: query_dag, validate_threshold, check_playbook.
Runs a tool-calling loop to answer freeform questions about cell data.
"""
import json
import logging
from typing import Any

from .knowledge.causal_dag import CausalDAG
from .ollama_client import OllamaClient
from .threshold_engine import ThresholdEngine

logger = logging.getLogger(__name__)

# Maximum tool-calling iterations to prevent infinite loops
MAX_TOOL_ITERATIONS = 10

# Tool definitions for the LLM
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "query_dag",
            "description": (
                "Query the causal DAG knowledge graph. "
                "Trace root causes backward from a symptom node, or trace "
                "downstream KPI impacts forward from a root cause node."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "node_id": {
                        "type": "string",
                        "description": "DAG node ID (e.g. T2_RSRP, T1_VSWR, K_NR_ACCESS_SR)",
                    },
                    "direction": {
                        "type": "string",
                        "enum": ["backward", "forward"],
                        "description": "backward=trace root causes, forward=trace downstream effects",
                    },
                },
                "required": ["node_id", "direction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "validate_threshold",
            "description": (
                "Check a measured RF value against DAS thresholds. "
                "Returns pass/fail with delta and threshold bounds."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "parameter": {
                        "type": "string",
                        "description": "Parameter name: rsrp, sinr, rsrq, tx_power, dl, ul",
                    },
                    "value": {
                        "type": "number",
                        "description": "Measured value",
                    },
                },
                "required": ["parameter", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_playbook",
            "description": (
                "Look up mitigation playbooks matching a set of activated DAG nodes. "
                "Returns field action steps for remediation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "activated_nodes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of activated DAG node IDs",
                    },
                },
                "required": ["activated_nodes"],
            },
        },
    },
]


class InvestigateEngine:
    """Agentic investigation engine with tool-calling loop.

    Uses the analysis model to answer freeform questions about cell data
    by calling tools that query the causal DAG, check thresholds, and
    look up playbooks.
    """

    def __init__(
        self,
        config: dict,
        ollama_client: OllamaClient,
        dag: CausalDAG,
        threshold_engine: ThresholdEngine,
    ) -> None:
        self.config = config
        self.client = ollama_client
        self.dag = dag
        self.threshold_engine = threshold_engine

    def investigate(self, cell_data: dict, question: str) -> str:
        """Run a tool-calling investigation loop to answer a question.

        Args:
            cell_data: Cell measurement data (RF params, throughput, etc.).
            question: Freeform question about the cell data.

        Returns:
            Final answer string from the analysis model.
        """
        system_prompt = self._build_system_prompt(cell_data)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question},
        ]

        model = self.config["ollama"]["analysis_model"]
        temperature = self.config["ollama"].get("analysis_temperature", 0.3)

        for iteration in range(MAX_TOOL_ITERATIONS):
            # Call the model
            raw = self.client.chat_text(
                self._format_messages(messages),
                model=model,
                temperature=temperature,
            )

            # Check if the response contains a tool call
            tool_call = self._parse_tool_call(raw)

            if tool_call is None:
                # No tool call — this is the final answer
                logger.info("Investigation completed in %d iteration(s)", iteration + 1)
                return raw

            # Execute the tool
            tool_name = tool_call["name"]
            tool_args = tool_call["arguments"]
            logger.debug("Tool call [%d]: %s(%s)", iteration + 1, tool_name, tool_args)

            tool_result = self._execute_tool(tool_name, tool_args)

            # Append the exchange to messages
            messages.append({"role": "assistant", "content": raw})
            messages.append({
                "role": "user",
                "content": f"Tool result for {tool_name}:\n{json.dumps(tool_result, indent=2)}",
            })

        logger.warning("Investigation hit max iterations (%d)", MAX_TOOL_ITERATIONS)
        return raw

    def _build_system_prompt(self, cell_data: dict) -> str:
        """Build system prompt with cell context and available tools."""
        tools_desc = "\n".join(
            f"- {t['function']['name']}: {t['function']['description']}"
            for t in TOOL_DEFINITIONS
        )

        return (
            "You are a DAS RF validation expert investigating cell measurement issues.\n\n"
            "## Available Tools\n"
            f"{tools_desc}\n\n"
            "To call a tool, respond with EXACTLY this format on a single line:\n"
            'TOOL_CALL: {"name": "tool_name", "arguments": {...}}\n\n'
            "After receiving tool results, analyze them and either call another tool "
            "or provide your final answer.\n\n"
            "## Cell Data\n"
            f"```json\n{json.dumps(cell_data, indent=2, default=str)}\n```\n"
        )

    @staticmethod
    def _format_messages(messages: list[dict]) -> str:
        """Flatten messages into a single prompt string for chat_text."""
        parts = []
        for msg in messages:
            role = msg["role"].upper()
            parts.append(f"[{role}]\n{msg['content']}")
        return "\n\n".join(parts)

    @staticmethod
    def _parse_tool_call(response: str) -> dict | None:
        """Parse a tool call from the model response.

        Looks for: TOOL_CALL: {"name": "...", "arguments": {...}}
        """
        for line in response.strip().splitlines():
            line = line.strip()
            if line.startswith("TOOL_CALL:"):
                json_str = line[len("TOOL_CALL:"):].strip()
                try:
                    parsed = json.loads(json_str)
                    if "name" in parsed and "arguments" in parsed:
                        return parsed
                except json.JSONDecodeError:
                    continue
        return None

    def _execute_tool(self, name: str, arguments: dict) -> dict[str, Any]:
        """Execute a tool by name and return the result."""
        if name == "query_dag":
            return self._tool_query_dag(arguments)
        elif name == "validate_threshold":
            return self._tool_validate_threshold(arguments)
        elif name == "check_playbook":
            return self._tool_check_playbook(arguments)
        else:
            return {"error": f"Unknown tool: {name}"}

    def _tool_query_dag(self, args: dict) -> dict[str, Any]:
        """Query the causal DAG for root causes or downstream effects."""
        node_id = args.get("node_id", "")
        direction = args.get("direction", "backward")

        if node_id not in self.dag.nodes:
            return {"error": f"Node {node_id} not found in DAG"}

        if direction == "backward":
            activated = {node_id}
            chains = self.dag.trace_root_causes(activated)
            deduped = self.dag.deduplicate_impacts(chains)
            return {
                "direction": "backward",
                "node": node_id,
                "chains": deduped,
                "formatted": self.dag.format_for_llm(deduped),
            }
        else:
            # Forward: trace downstream from this node
            # Activate the node and common downstream nodes
            activated = {node_id}
            downstream = self.dag.trace_downstream_effects(node_id, activated)
            downstream_names = [
                self.dag.nodes[nid].name for nid in downstream if nid in self.dag.nodes
            ]
            return {
                "direction": "forward",
                "node": node_id,
                "downstream_ids": downstream,
                "downstream_names": downstream_names,
            }

    def _tool_validate_threshold(self, args: dict) -> dict[str, Any]:
        """Check a parameter value against thresholds."""
        param = args.get("parameter", "")
        value = args.get("value", 0)

        sm_params = {"rsrp", "sinr", "rsrq", "tx_power"}
        if param in sm_params:
            kwargs = {"rsrp": 0.0, "sinr": 0.0, "rsrq": 0.0, "tx_power": 0.0}
            kwargs[param] = float(value)
            result = self.threshold_engine.check_service_mode(
                end_type="antenna_end", **kwargs,
            )
            return result.get(param, {"error": "parameter not in result"})

        return {"error": f"Parameter '{param}' not supported for threshold check"}

    def _tool_check_playbook(self, args: dict) -> dict[str, Any]:
        """Look up playbooks for activated nodes."""
        activated = set(args.get("activated_nodes", []))
        playbooks = self.dag.get_matching_playbooks(activated)
        return {
            "activated": list(activated),
            "playbook_count": len(playbooks),
            "playbooks": [
                {"title": pb.get("title", ""), "steps": pb.get("steps", [])}
                for pb in playbooks
            ],
        }
