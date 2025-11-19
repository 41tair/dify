"""YAML workflow parser for Dify workflow format"""

import yaml
from typing import Any, Dict, Optional

from ..core.graph import Graph, Node, Edge
from ..exceptions import WorkflowParseError


class YAMLParser:
    """Parser for YAML workflow definitions"""

    @classmethod
    def parse(cls, yaml_content: str) -> Dict[str, Any]:
        """
        Parse YAML workflow content.

        Args:
            yaml_content: YAML string content

        Returns:
            Workflow dictionary

        Raises:
            WorkflowParseError: If parsing fails
        """
        try:
            data = yaml.safe_load(yaml_content)
        except yaml.YAMLError as e:
            raise WorkflowParseError(f"Failed to parse YAML: {e}")

        if not isinstance(data, dict):
            raise WorkflowParseError("YAML content must be a dictionary")

        return data

    @classmethod
    def parse_file(cls, file_path: str) -> Dict[str, Any]:
        """
        Parse YAML workflow from file.

        Args:
            file_path: Path to YAML file

        Returns:
            Workflow dictionary
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return cls.parse(f.read())
        except FileNotFoundError:
            raise WorkflowParseError(f"File not found: {file_path}")
        except Exception as e:
            raise WorkflowParseError(f"Failed to read file: {e}")

    @classmethod
    def workflow_to_graph(cls, workflow_data: Dict[str, Any]) -> Graph:
        """
        Convert workflow data to a Graph object.

        Args:
            workflow_data: Parsed workflow dictionary

        Returns:
            Graph object ready for execution
        """
        # Get the workflow section
        if "workflow" in workflow_data:
            workflow = workflow_data["workflow"]
        else:
            workflow = workflow_data

        # Get graph data
        if "graph" not in workflow:
            raise WorkflowParseError("Workflow must contain a 'graph' section")

        graph_data = workflow["graph"]

        # Create graph
        graph = Graph(graph_id=workflow_data.get("app", {}).get("name", "workflow"))

        # Add nodes
        nodes_data = graph_data.get("nodes", [])
        for node_data in nodes_data:
            node = cls._parse_node(node_data)
            graph.add_node(node)

        # Add edges
        edges_data = graph_data.get("edges", [])
        for edge_data in edges_data:
            edge = cls._parse_edge(edge_data)
            graph.add_edge(edge)

        # Validate the graph
        if not graph.validate():
            raise WorkflowParseError("Invalid graph structure")

        return graph

    @classmethod
    def _parse_node(cls, node_data: Dict[str, Any]) -> Node:
        """
        Parse a single node from the workflow data.

        Args:
            node_data: Node dictionary

        Returns:
            Node object
        """
        node_id = node_data.get("id")
        if not node_id:
            raise WorkflowParseError("Node must have an 'id'")

        # Extract node configuration
        data = node_data.get("data", {})

        # Get node type (can be in data or at top level)
        node_type = data.get("type", node_data.get("type", "unknown"))

        # Get position if available
        position = node_data.get("position")

        return Node(
            id=node_id,
            type=node_type,
            data=data,
            position=position,
        )

    @classmethod
    def _parse_edge(cls, edge_data: Dict[str, Any]) -> Edge:
        """
        Parse a single edge from the workflow data.

        Args:
            edge_data: Edge dictionary

        Returns:
            Edge object
        """
        edge_id = edge_data.get("id")
        source = edge_data.get("source")
        target = edge_data.get("target")

        if not source or not target:
            raise WorkflowParseError("Edge must have 'source' and 'target'")

        # Generate ID if not provided
        if not edge_id:
            edge_id = f"{source}-{target}"

        return Edge(
            id=edge_id,
            source=source,
            target=target,
            source_handle=edge_data.get("sourceHandle", "source"),
            target_handle=edge_data.get("targetHandle", "target"),
            data=edge_data.get("data"),
        )

    @classmethod
    def extract_inputs(cls, workflow_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract input variable definitions from the workflow.

        Args:
            workflow_data: Parsed workflow dictionary

        Returns:
            Dictionary of input variable definitions
        """
        inputs = {}

        # Get workflow section
        if "workflow" in workflow_data:
            workflow = workflow_data["workflow"]
        else:
            workflow = workflow_data

        # Find start node(s) and extract variables
        graph = workflow.get("graph", {})
        nodes = graph.get("nodes", [])

        for node in nodes:
            data = node.get("data", {})
            if data.get("type") == "start":
                variables = data.get("variables", [])
                for var in variables:
                    var_name = var.get("variable", var.get("label"))
                    if var_name:
                        inputs[var_name] = {
                            "type": var.get("type", "string"),
                            "required": var.get("required", False),
                            "default": var.get("default"),
                            "description": var.get("desc", var.get("description", "")),
                        }

        return inputs