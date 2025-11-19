"""SDK Exception definitions"""


class WorkflowSDKError(Exception):
    """Base exception for Workflow SDK"""
    pass


class WorkflowParseError(WorkflowSDKError):
    """Error parsing workflow definition"""
    pass


class WorkflowExecutionError(WorkflowSDKError):
    """Error during workflow execution"""
    pass


class NodeExecutionError(WorkflowExecutionError):
    """Error executing a node"""
    def __init__(self, node_id: str, message: str):
        self.node_id = node_id
        super().__init__(f"Node {node_id}: {message}")


class WorkflowTimeoutError(WorkflowExecutionError):
    """Workflow execution timeout"""
    pass


class WorkflowValidationError(WorkflowSDKError):
    """Workflow validation error"""
    pass


class VariableNotFoundError(WorkflowExecutionError):
    """Variable not found in variable pool"""
    pass