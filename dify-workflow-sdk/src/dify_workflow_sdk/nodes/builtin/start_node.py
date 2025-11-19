"""Start node implementation"""

from typing import Any, Dict

from ..base import SimpleNode


class StartNode(SimpleNode):
    """
    Start node - entry point of a workflow.

    This node receives the initial inputs and passes them to the workflow.
    """

    @classmethod
    def _get_node_type(cls) -> str:
        return "start"

    def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the start node.

        The start node simply passes through the inputs, optionally
        extracting specific variables defined in the node configuration.

        Args:
            inputs: Initial workflow inputs

        Returns:
            Outputs to pass to next nodes
        """
        outputs = {}

        # Get variable definitions from node data
        variables = self.node_data.get("variables", [])

        for var_def in variables:
            var_name = var_def.get("variable", var_def.get("label", var_def.get("name")))
            var_type = var_def.get("type", "string")
            required = var_def.get("required", False)
            default_value = var_def.get("default")

            if not var_name:
                continue

            # Get value from inputs
            value = inputs.get(var_name)

            if value is None:
                if required:
                    raise ValueError(f"Required input '{var_name}' not provided")
                elif default_value is not None:
                    value = default_value
                else:
                    # Skip optional variables without values
                    continue

            # Type conversion if needed
            if var_type == "integer" and not isinstance(value, int):
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    raise ValueError(f"Cannot convert '{var_name}' to integer")
            elif var_type == "float" and not isinstance(value, float):
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    raise ValueError(f"Cannot convert '{var_name}' to float")
            elif var_type == "boolean" and not isinstance(value, bool):
                if isinstance(value, str):
                    value = value.lower() in ("true", "yes", "1")
                else:
                    value = bool(value)

            outputs[var_name] = value

        # If no variables defined, pass through all inputs
        if not variables:
            outputs = inputs.copy()

        # Store outputs in variable pool for other nodes
        for key, value in outputs.items():
            self.set_variable(f"{self.node_id}.{key}", value)

        return outputs