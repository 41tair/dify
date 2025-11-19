"""Template transformation node implementation"""

from typing import Any, Dict

from ..base import SimpleNode


class TemplateNode(SimpleNode):
    """
    Template node - transforms data using template strings.

    This node processes template strings with variable substitution.
    """

    @classmethod
    def _get_node_type(cls) -> str:
        return "template_transform"

    def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute template transformation.

        Args:
            inputs: Input variables for template substitution

        Returns:
            Transformed output
        """
        # Get template from node configuration
        template = self.node_data.get("template", self.node_data.get("prompt_template", ""))

        if not template:
            return {"output": ""}

        # Handle different template formats
        if isinstance(template, list):
            # Template is a list of messages (for chat format)
            result = []
            for message in template:
                role = message.get("role", "user")
                text = message.get("text", message.get("content", ""))

                # Resolve variables in the text
                resolved_text = self._resolve_template_with_inputs(text, inputs)

                result.append({
                    "role": role,
                    "content": resolved_text,
                })

            return {"messages": result, "output": result}

        else:
            # Simple string template
            resolved = self._resolve_template_with_inputs(template, inputs)
            return {"output": resolved}

    def _resolve_template_with_inputs(self, template: str, inputs: Dict[str, Any]) -> str:
        """
        Resolve template with input variables.

        Supports two formats:
        1. {{variable}} - simple variable substitution
        2. {{#node_id.variable#}} - variable pool references

        Args:
            template: Template string
            inputs: Input variables

        Returns:
            Resolved string
        """
        import re

        # First, resolve variable pool references {{#node_id.variable#}}
        resolved = self.resolve_template(template)

        # Then, resolve simple variable references {{variable}}
        pattern = re.compile(r"\{\{([a-zA-Z_][a-zA-Z0-9_]*)\}\}")

        def replace_var(match):
            var_name = match.group(1)
            if var_name in inputs:
                value = inputs[var_name]
                if isinstance(value, (dict, list)):
                    import json
                    return json.dumps(value)
                return str(value)
            return match.group(0)  # Keep original if not found

        resolved = pattern.sub(replace_var, resolved)

        return resolved