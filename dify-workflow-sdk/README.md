# Dify Workflow SDK

A standalone Python SDK for executing Dify workflows independently of the Dify platform. This SDK extracts the core workflow execution engine from Dify, allowing you to run workflow YAML files in any Python application.

## Features

- **Standalone Execution**: Run Dify workflows without the full Dify backend
- **YAML Support**: Load and execute workflows from YAML files
- **Extensible Node System**: Built-in nodes and support for custom nodes
- **Variable Management**: Sophisticated variable pool for data flow between nodes
- **Event Streaming**: Real-time event streaming during workflow execution
- **Protocol-based Architecture**: Clean abstractions for storage, repository, and models

## Installation

```bash
# Clone the repository
git clone <repo-url>
cd dify-workflow-sdk

# Create virtual environment
uv venv
source .venv/bin/activate

# Install dependencies
uv pip install -e .
```

## Quick Start

```python
from dify_workflow_sdk import WorkflowEngine

# Load and run a workflow from YAML file
engine = WorkflowEngine.from_yaml_file("workflow.yml")
outputs = engine.run_sync(inputs={"message": "Hello, World!"})
print(outputs)
```

## Usage Examples

### Simple Workflow Execution

```python
from dify_workflow_sdk import WorkflowEngine, WorkflowConfig

# Create configuration
config = WorkflowConfig(
    max_execution_steps=500,
    max_execution_time=300.0,
    debug=True
)

# Load workflow from YAML file
engine = WorkflowEngine.from_yaml_file(
    "path/to/workflow.yml",
    config=config
)

# Execute synchronously
outputs = engine.run_sync(inputs={
    "input_var": "value"
})
print("Results:", outputs)
```

### Streaming Execution

```python
# Execute with event streaming
for event in engine.run(inputs={"input_var": "value"}, stream=True):
    print(f"Event: {event.__class__.__name__}")

    if hasattr(event, 'outputs'):
        print(f"Outputs: {event.outputs}")
```

### Creating Workflows Programmatically

```python
from dify_workflow_sdk import Graph, Node, Edge, WorkflowEngine

# Create graph
graph = Graph(graph_id="my_workflow")

# Add nodes
start_node = Node(id="start", type="start", data={
    "variables": [
        {"variable": "input", "type": "string", "required": True}
    ]
})
graph.add_node(start_node)

code_node = Node(id="process", type="code", data={
    "code": "output = input.upper()"
})
graph.add_node(code_node)

end_node = Node(id="end", type="end", data={
    "outputs": [
        {"variable": "result", "value_selector": "process.output"}
    ]
})
graph.add_node(end_node)

# Add edges
graph.add_edge(Edge(id="e1", source="start", target="process"))
graph.add_edge(Edge(id="e2", source="process", target="end"))

# Run workflow
engine = WorkflowEngine(workflow=graph)
outputs = engine.run_sync(inputs={"input": "hello"})
print(outputs)  # {'result': 'HELLO'}
```

### Custom Node Development

```python
from dify_workflow_sdk import SimpleNode, register_node

class CustomTransformNode(SimpleNode):
    @classmethod
    def _get_node_type(cls):
        return "custom_transform"

    def execute(self, inputs):
        # Your custom logic here
        text = inputs.get("text", "")
        transformed = text.replace("old", "new")
        return {"output": transformed}

# Register the custom node
register_node("custom_transform", CustomTransformNode)
```

## Built-in Node Types

### Start Node
Entry point of the workflow, defines input variables.

```yaml
- id: start
  data:
    type: start
    variables:
    - variable: message
      type: string
      required: true
```

### End Node
Exit point of the workflow, defines output variables.

```yaml
- id: end
  data:
    type: end
    outputs:
    - variable: result
      value_selector: previous_node.output
```

### Code Node
Executes Python code with sandboxed environment.

```yaml
- id: code
  data:
    type: code
    code: |
      result = input_var * 2
      print(f"Processed: {result}")
```

### Template Node
Transforms data using template strings.

```yaml
- id: template
  data:
    type: template_transform
    template: "Hello {{name}}, welcome!"
```

### If-Else Node
Conditional branching based on conditions.

```yaml
- id: condition
  data:
    type: if_else
    conditions:
    - variable: age
      operator: '>='
      value: 18
```

## Workflow YAML Format

```yaml
app:
  name: my_workflow
  mode: workflow

workflow:
  graph:
    nodes:
    - id: start
      data:
        type: start
        variables:
        - variable: input
          type: string
          required: true

    - id: process
      data:
        type: code
        code: |
          output = input.upper()

    - id: end
      data:
        type: end
        outputs:
        - variable: result
          value_selector: process.output

    edges:
    - source: start
      target: process
    - source: process
      target: end
```

## Architecture

### Core Components

- **GraphEngine**: Main orchestrator for workflow execution
- **Graph**: Represents workflow structure with nodes and edges
- **VariablePool**: Manages data flow between nodes
- **RuntimeState**: Tracks execution state and node outputs

### Extension Points

- **FileStorage Protocol**: Implement for custom file storage
- **WorkflowRepository Protocol**: Implement for execution persistence
- **Custom Nodes**: Extend BaseNode or SimpleNode for custom logic

## Differences from Dify

This SDK is a simplified, standalone version of Dify's workflow engine:

- **No Database Dependencies**: Uses in-memory storage by default
- **No Web Framework**: Removed Flask dependencies
- **Simplified LLM Support**: Optional, requires separate installation
- **Core Nodes Only**: Includes essential nodes (Start, End, Code, Template, If-Else)
- **Protocol-based Extensions**: Clean interfaces for customization

## Roadmap

- [ ] Additional node types (HTTP Request, Loop, Iteration)
- [ ] LLM node with provider abstractions
- [ ] Distributed execution support
- [ ] Workflow validation and debugging tools
- [ ] Visual workflow builder integration

## Contributing

Contributions are welcome! Please ensure:

1. Code follows existing patterns
2. Tests are included for new features
3. Documentation is updated

## License

[License information based on original Dify project]

## Acknowledgments

This SDK is extracted from the [Dify](https://github.com/langgenius/dify) project, an open-source platform for developing LLM applications.