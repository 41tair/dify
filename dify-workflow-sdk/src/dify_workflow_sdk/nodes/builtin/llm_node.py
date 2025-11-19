"""Mock LLM node implementation"""

from typing import Any, Dict
from ..base import SimpleNode


class LLMNode(SimpleNode):
    """
    Mock LLM node for demonstration purposes.

    In a real implementation, this would integrate with LLM providers
    like OpenAI, Anthropic, etc.
    """

    @classmethod
    def _get_node_type(cls) -> str:
        return "llm"

    def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute mock LLM call.

        Args:
            inputs: Input variables

        Returns:
            Mock LLM response
        """
        # Get prompt template from node configuration
        prompt_template = self.node_data.get("prompt_template", [])

        # Build the prompt
        messages = []
        for msg in prompt_template:
            role = msg.get("role", "user")
            text = msg.get("text", "")

            # Resolve variables in text
            if text and inputs:
                for key, value in inputs.items():
                    text = text.replace(f"{{{{{key}}}}}", str(value))

            messages.append({
                "role": role,
                "content": text
            })

        # Mock LLM response
        # In a real implementation, this would call the actual LLM API
        mock_response = self._generate_mock_response(messages)

        return {
            "content": mock_response,
            "messages": messages,
            "model": self.node_data.get("model", {}).get("name", "mock-model"),
        }

    def _generate_mock_response(self, messages: list) -> str:
        """Generate a mock response based on the messages."""
        # Look for system message
        system_msg = ""
        for msg in messages:
            if msg["role"] == "system":
                system_msg = msg["content"]
                break

        # Generate response based on system message
        if "robot" in system_msg.lower():
            return "🤖 BEEP BOOP! I AM A ROBOT. PROCESSING YOUR REQUEST... COMPLETE! 🤖"
        elif "assistant" in system_msg.lower():
            return "I'm here to help you with your request."
        else:
            # Default response
            return f"Mock LLM response based on prompt: {system_msg[:100] if system_msg else 'No system prompt'}"