"""Simplified graph representation for workflow execution"""

import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class Node:
    """Simple node representation"""
    id: str
    type: str
    data: Dict[str, Any]
    position: Optional[Dict[str, float]] = None

    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, Node):
            return False
        return self.id == other.id


@dataclass
class Edge:
    """Simple edge representation"""
    id: str
    source: str
    target: str
    source_handle: str = "source"
    target_handle: str = "target"
    data: Optional[Dict[str, Any]] = None

    def __hash__(self) -> int:
        return hash(self.id)


class Graph:
    """Simplified graph representation for workflow execution"""

    def __init__(self, graph_id: Optional[str] = None):
        """Initialize an empty graph"""
        self.graph_id = graph_id or "default"
        self.nodes: Dict[str, Node] = {}
        self.edges: Dict[str, Edge] = {}
        self.in_edges: Dict[str, List[str]] = defaultdict(list)  # node_id -> [edge_ids]
        self.out_edges: Dict[str, List[str]] = defaultdict(list)  # node_id -> [edge_ids]
        self.root_node_id: Optional[str] = None

    def add_node(self, node: Node) -> None:
        """Add a node to the graph"""
        self.nodes[node.id] = node

        # If this is a start node, set it as root
        if node.type == "start":
            self.root_node_id = node.id

    def add_edge(self, edge: Edge) -> None:
        """Add an edge to the graph"""
        if edge.source not in self.nodes:
            raise ValueError(f"Source node {edge.source} not found in graph")
        if edge.target not in self.nodes:
            raise ValueError(f"Target node {edge.target} not found in graph")

        self.edges[edge.id] = edge
        self.out_edges[edge.source].append(edge.id)
        self.in_edges[edge.target].append(edge.id)

    def get_node(self, node_id: str) -> Optional[Node]:
        """Get a node by ID"""
        return self.nodes.get(node_id)

    def get_edge(self, edge_id: str) -> Optional[Edge]:
        """Get an edge by ID"""
        return self.edges.get(edge_id)

    def get_start_node(self) -> Optional[Node]:
        """Get the start node of the graph"""
        if self.root_node_id:
            return self.nodes.get(self.root_node_id)

        # Find start node if not explicitly set
        for node in self.nodes.values():
            if node.type == "start":
                self.root_node_id = node.id
                return node

        # If no explicit start node, find nodes with no incoming edges
        for node_id, node in self.nodes.items():
            if node_id not in self.in_edges or not self.in_edges[node_id]:
                self.root_node_id = node_id
                return node

        return None

    def get_next_nodes(self, node_id: str) -> List[Node]:
        """Get all nodes that come after the given node"""
        next_nodes = []

        # Get all outgoing edges from this node
        out_edge_ids = self.out_edges.get(node_id, [])
        for edge_id in out_edge_ids:
            edge = self.edges.get(edge_id)
            if edge:
                target_node = self.nodes.get(edge.target)
                if target_node:
                    next_nodes.append(target_node)

        return next_nodes

    def get_previous_nodes(self, node_id: str) -> List[Node]:
        """Get all nodes that come before the given node"""
        prev_nodes = []

        # Get all incoming edges to this node
        in_edge_ids = self.in_edges.get(node_id, [])
        for edge_id in in_edge_ids:
            edge = self.edges.get(edge_id)
            if edge:
                source_node = self.nodes.get(edge.source)
                if source_node:
                    prev_nodes.append(source_node)

        return prev_nodes

    def get_all_node_ids(self) -> Set[str]:
        """Get all node IDs in the graph"""
        return set(self.nodes.keys())

    def get_all_edge_ids(self) -> Set[str]:
        """Get all edge IDs in the graph"""
        return set(self.edges.keys())

    def validate(self) -> bool:
        """Validate the graph structure"""
        # Check if graph has nodes
        if not self.nodes:
            logger.error("Graph has no nodes")
            return False

        # Check if graph has a start node
        start_node = self.get_start_node()
        if not start_node:
            logger.error("Graph has no start node")
            return False

        # Check for cycles (simple DFS)
        if self._has_cycles():
            logger.error("Graph contains cycles")
            return False

        # Check if all edges reference valid nodes
        for edge in self.edges.values():
            if edge.source not in self.nodes:
                logger.error(f"Edge {edge.id} references invalid source node {edge.source}")
                return False
            if edge.target not in self.nodes:
                logger.error(f"Edge {edge.id} references invalid target node {edge.target}")
                return False

        return True

    def _has_cycles(self) -> bool:
        """Check if the graph has cycles using DFS"""
        visited = set()
        rec_stack = set()

        def visit(node_id: str) -> bool:
            visited.add(node_id)
            rec_stack.add(node_id)

            # Check all neighbors
            for next_node in self.get_next_nodes(node_id):
                if next_node.id not in visited:
                    if visit(next_node.id):
                        return True
                elif next_node.id in rec_stack:
                    return True

            rec_stack.remove(node_id)
            return False

        # Check from all unvisited nodes
        for node_id in self.nodes:
            if node_id not in visited:
                if visit(node_id):
                    return True

        return False

    def to_dict(self) -> Dict[str, Any]:
        """Convert graph to dictionary representation"""
        return {
            "graph_id": self.graph_id,
            "nodes": [
                {
                    "id": node.id,
                    "type": node.type,
                    "data": node.data,
                    "position": node.position,
                }
                for node in self.nodes.values()
            ],
            "edges": [
                {
                    "id": edge.id,
                    "source": edge.source,
                    "target": edge.target,
                    "sourceHandle": edge.source_handle,
                    "targetHandle": edge.target_handle,
                    "data": edge.data,
                }
                for edge in self.edges.values()
            ],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Graph":
        """Create graph from dictionary representation"""
        graph = cls(graph_id=data.get("graph_id"))

        # Add nodes
        for node_data in data.get("nodes", []):
            node = Node(
                id=node_data["id"],
                type=node_data.get("type", node_data.get("data", {}).get("type", "unknown")),
                data=node_data.get("data", {}),
                position=node_data.get("position"),
            )
            graph.add_node(node)

        # Add edges
        for edge_data in data.get("edges", []):
            edge = Edge(
                id=edge_data.get("id", f"{edge_data['source']}-{edge_data['target']}"),
                source=edge_data["source"],
                target=edge_data["target"],
                source_handle=edge_data.get("sourceHandle", "source"),
                target_handle=edge_data.get("targetHandle", "target"),
                data=edge_data.get("data"),
            )
            graph.add_edge(edge)

        return graph