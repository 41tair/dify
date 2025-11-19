"""Variable pool for managing data flow between nodes"""

import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Union

VariableValue = Union[str, int, float, dict, list, None]

# Pattern for variable references in templates: {{#node_id.variable_name#}}
VARIABLE_PATTERN = re.compile(r"\{\{#([a-zA-Z0-9_]+(?:\.[a-zA-Z_][a-zA-Z0-9_]*)+)#\}\}")


class VariablePool:
    """
    Manages variables and data flow between nodes in a workflow.

    Variables are referenced using a selector format: "node_id.variable_name"
    """

    def __init__(self):
        """Initialize the variable pool"""
        # Store variables in a nested dictionary: {node_id: {variable_name: value}}
        self._variables: Dict[str, Dict[str, VariableValue]] = defaultdict(dict)

        # Special variable namespaces
        self._user_inputs: Dict[str, Any] = {}
        self._system_variables: Dict[str, Any] = {}
        self._environment_variables: Dict[str, Any] = {}

    def set_user_inputs(self, inputs: Dict[str, Any]) -> None:
        """Set user inputs for the workflow"""
        self._user_inputs = inputs
        # Also store in the variable namespace for easy access
        self._variables["inputs"] = inputs.copy()

    def get_user_inputs(self) -> Dict[str, Any]:
        """Get user inputs"""
        return self._user_inputs.copy()

    def set(self, selector: str, value: VariableValue) -> None:
        """
        Set a variable value using a selector.

        Args:
            selector: Variable selector in format "node_id.variable_name"
            value: Value to set
        """
        parts = selector.split(".", 1)
        if len(parts) != 2:
            raise ValueError(f"Invalid selector format: {selector}")

        node_id, variable_name = parts
        self._variables[node_id][variable_name] = value

    def get(self, selector: str) -> Optional[VariableValue]:
        """
        Get a variable value using a selector.

        Args:
            selector: Variable selector in format "node_id.variable_name"

        Returns:
            Variable value or None if not found
        """
        parts = selector.split(".", 1)
        if len(parts) != 2:
            return None

        node_id, variable_name = parts

        # Check if it's a system variable
        if node_id == "sys":
            return self._system_variables.get(variable_name)

        # Check if it's an environment variable
        if node_id == "env":
            return self._environment_variables.get(variable_name)

        # Check regular variables
        if node_id in self._variables:
            return self._variables[node_id].get(variable_name)

        return None

    def get_node_variables(self, node_id: str) -> Dict[str, VariableValue]:
        """Get all variables for a specific node"""
        return self._variables.get(node_id, {}).copy()

    def set_node_variables(self, node_id: str, variables: Dict[str, VariableValue]) -> None:
        """Set all variables for a specific node"""
        self._variables[node_id] = variables.copy()

    def resolve_template(self, template: str) -> str:
        """
        Resolve variable references in a template string.

        Args:
            template: Template string with variable references like {{#node_id.var#}}

        Returns:
            Resolved string with variables replaced
        """
        def replace_variable(match):
            selector = match.group(1)
            value = self.get(selector)

            if value is None:
                # Keep the original placeholder if variable not found
                return match.group(0)

            # Convert value to string
            if isinstance(value, (dict, list)):
                import json
                return json.dumps(value)
            return str(value)

        return VARIABLE_PATTERN.sub(replace_variable, template)

    def clear(self) -> None:
        """Clear all variables"""
        self._variables.clear()
        self._user_inputs.clear()
        self._system_variables.clear()
        self._environment_variables.clear()

    def get_all_variables(self) -> Dict[str, Dict[str, VariableValue]]:
        """Get all variables in the pool"""
        return dict(self._variables)

    def set_system_variable(self, name: str, value: Any) -> None:
        """Set a system variable"""
        self._system_variables[name] = value

    def set_environment_variable(self, name: str, value: Any) -> None:
        """Set an environment variable"""
        self._environment_variables[name] = value

    def merge_variables(self, other_pool: "VariablePool") -> None:
        """Merge variables from another pool into this one"""
        for node_id, variables in other_pool._variables.items():
            self._variables[node_id].update(variables)

        self._system_variables.update(other_pool._system_variables)
        self._environment_variables.update(other_pool._environment_variables)

    def __repr__(self) -> str:
        """String representation of the variable pool"""
        total_vars = sum(len(vars) for vars in self._variables.values())
        return f"VariablePool(nodes={len(self._variables)}, variables={total_vars})"