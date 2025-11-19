"""If-Else conditional node implementation"""

from typing import Any, Dict

from ..base import SimpleNode


class IfElseNode(SimpleNode):
    """
    If-Else node - conditional branching in workflows.

    This node evaluates conditions and routes execution based on the result.
    """

    @classmethod
    def _get_node_type(cls) -> str:
        return "if_else"

    def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute conditional logic.

        Args:
            inputs: Input variables for condition evaluation

        Returns:
            Output with branch decision
        """
        # Get conditions from node configuration
        conditions = self.node_data.get("conditions", [])

        # Evaluate conditions in order
        for i, condition in enumerate(conditions):
            if self._evaluate_condition(condition, inputs):
                return {
                    "result": True,
                    "branch": f"condition_{i}",
                    "branch_index": i,
                }

        # No conditions met, use else branch
        return {
            "result": False,
            "branch": "else",
            "branch_index": -1,
        }

    def _evaluate_condition(self, condition: Dict[str, Any], inputs: Dict[str, Any]) -> bool:
        """
        Evaluate a single condition.

        Args:
            condition: Condition configuration
            inputs: Available variables

        Returns:
            True if condition is met, False otherwise
        """
        # Get condition parameters
        variable = condition.get("variable", condition.get("left"))
        operator = condition.get("operator", condition.get("comparison", "=="))
        value = condition.get("value", condition.get("right"))

        # Get the variable value
        if variable:
            # Check if it's a selector
            if "." in variable:
                var_value = self.get_variable(variable)
            else:
                var_value = inputs.get(variable)
        else:
            return False

        # Evaluate based on operator
        try:
            if operator in ("==", "equals", "is"):
                return var_value == value
            elif operator in ("!=", "not_equals", "is_not"):
                return var_value != value
            elif operator in (">", "greater_than"):
                return float(var_value) > float(value)
            elif operator in (">=", "greater_than_or_equals"):
                return float(var_value) >= float(value)
            elif operator in ("<", "less_than"):
                return float(var_value) < float(value)
            elif operator in ("<=", "less_than_or_equals"):
                return float(var_value) <= float(value)
            elif operator in ("contains", "in"):
                return str(value) in str(var_value)
            elif operator == "not_contains":
                return str(value) not in str(var_value)
            elif operator == "starts_with":
                return str(var_value).startswith(str(value))
            elif operator == "ends_with":
                return str(var_value).endswith(str(value))
            elif operator == "is_empty":
                return not var_value
            elif operator == "is_not_empty":
                return bool(var_value)
            elif operator == "and":
                # Multiple conditions with AND
                sub_conditions = condition.get("conditions", [])
                return all(self._evaluate_condition(c, inputs) for c in sub_conditions)
            elif operator == "or":
                # Multiple conditions with OR
                sub_conditions = condition.get("conditions", [])
                return any(self._evaluate_condition(c, inputs) for c in sub_conditions)
            else:
                # Unknown operator, default to false
                return False

        except (TypeError, ValueError):
            # Type conversion failed, condition is false
            return False