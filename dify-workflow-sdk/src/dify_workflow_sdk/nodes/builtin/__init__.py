"""Built-in workflow nodes"""

from .code_node import CodeNode
from .end_node import EndNode
from .if_else_node import IfElseNode
from .start_node import StartNode
from .template_node import TemplateNode
from .llm_node import LLMNode

# Node registry mapping node types to classes
NODE_REGISTRY = {
    "start": StartNode,
    "end": EndNode,
    "code": CodeNode,
    "template_transform": TemplateNode,
    "template": TemplateNode,  # Alias
    "if_else": IfElseNode,
    "ifelse": IfElseNode,  # Alias
    "llm": LLMNode,  # Mock LLM node
}


def get_node_class(node_type: str):
    """Get node class by type"""
    return NODE_REGISTRY.get(node_type)


def register_node(node_type: str, node_class):
    """Register a custom node type"""
    NODE_REGISTRY[node_type] = node_class


__all__ = [
    "StartNode",
    "EndNode",
    "CodeNode",
    "TemplateNode",
    "IfElseNode",
    "NODE_REGISTRY",
    "get_node_class",
    "register_node",
]