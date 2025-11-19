"""End node implementation"""

from typing import Any, Dict

from ..base import SimpleNode


class EndNode(SimpleNode):
    """
    End node - exit point of a workflow.

    This node collects outputs from the workflow and returns them as final results.
    """

    @classmethod
    def _get_node_type(cls) -> str:
        return "end"

    def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the end node.

        The end node collects outputs based on its configuration and
        returns them as the workflow's final output.

        Args:
            inputs: Inputs from previous nodes

        Returns:
            Final workflow outputs
        """
        outputs = {}

        # Get output definitions from node data
        output_configs = self.node_data.get("outputs", [])

        if output_configs:
            # Process configured outputs
            for output_config in output_configs:
                var_name = output_config.get("variable", output_config.get("name"))
                value_selector = output_config.get("value_selector", output_config.get("selector"))

                if not var_name:
                    continue

                # Get value from variable pool using selector
                if value_selector:
                    if isinstance(value_selector, list):
                        # Convert list selector to string format
                        selector = ".".join(value_selector)
                    else:
                        selector = value_selector

                    value = self.get_variable(selector)
                else:
                    # Try to get from inputs
                    value = inputs.get(var_name)

                if value is not None:
                    outputs[var_name] = value

        else:
            # If no outputs configured, return all inputs
            outputs = inputs.copy()

        return outputs