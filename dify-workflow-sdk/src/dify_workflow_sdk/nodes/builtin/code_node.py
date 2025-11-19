"""Code execution node implementation"""

import ast
import sys
from io import StringIO
from typing import Any, Dict

from ..base import SimpleNode


class CodeNode(SimpleNode):
    """
    Code node - executes Python code within the workflow.

    This node allows executing arbitrary Python code with access to inputs
    and the ability to return outputs.
    """

    @classmethod
    def _get_node_type(cls) -> str:
        return "code"

    def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute Python code.

        Args:
            inputs: Input variables available to the code

        Returns:
            Output variables from the code execution
        """
        # Get code from node configuration
        code = self.node_data.get("code", "")
        if not code:
            return {}

        # Prepare execution environment
        global_vars = {
            "__builtins__": {
                # Safe built-in functions
                "len": len,
                "range": range,
                "int": int,
                "float": float,
                "str": str,
                "bool": bool,
                "list": list,
                "dict": dict,
                "set": set,
                "tuple": tuple,
                "sorted": sorted,
                "min": min,
                "max": max,
                "sum": sum,
                "abs": abs,
                "round": round,
                "print": print,
                "enumerate": enumerate,
                "zip": zip,
                "map": map,
                "filter": filter,
                "any": any,
                "all": all,
            }
        }

        # Add inputs to the execution environment
        local_vars = inputs.copy()

        # Capture stdout
        old_stdout = sys.stdout
        sys.stdout = StringIO()

        try:
            # Parse code to check for syntax errors
            ast.parse(code)

            # Execute the code
            exec(code, global_vars, local_vars)

            # Get stdout output
            stdout_output = sys.stdout.getvalue()

            # Prepare outputs
            outputs = {}

            # Get output definitions from node configuration
            output_vars = self.node_data.get("outputs", self.node_data.get("output_variables", []))

            if output_vars:
                # Extract specified output variables
                for var_config in output_vars:
                    if isinstance(var_config, str):
                        var_name = var_config
                    else:
                        var_name = var_config.get("name", var_config.get("variable"))

                    if var_name and var_name in local_vars:
                        outputs[var_name] = local_vars[var_name]
            else:
                # Return all new or modified variables
                for key, value in local_vars.items():
                    # Skip inputs that weren't modified
                    if key not in inputs or inputs[key] != value:
                        # Skip private variables (starting with _)
                        if not key.startswith("_"):
                            outputs[key] = value

            # Add stdout output if any
            if stdout_output:
                outputs["__stdout__"] = stdout_output

            return outputs

        except SyntaxError as e:
            raise ValueError(f"Syntax error in code: {e}")
        except Exception as e:
            raise RuntimeError(f"Error executing code: {e}")
        finally:
            # Restore stdout
            sys.stdout = old_stdout

    def _validate_inputs(self, inputs: Dict[str, Any]) -> None:
        """Validate that code is provided"""
        code = self.node_data.get("code", "")
        if not code or not code.strip():
            raise ValueError("Code node requires code to execute")