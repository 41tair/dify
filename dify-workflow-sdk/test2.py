#!/usr/bin/env python3
"""
Test script for Dify Workflow SDK - Fixed version

This demonstrates:
1. Proper path setup for importing the SDK
2. Correct input variable usage based on workflow schema
3. Mock LLM node implementation
"""

import sys
import os

# Add SDK to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from dify_workflow_sdk import WorkflowEngine

print("=" * 60)
print("Dify Workflow SDK - Test2.py (Fixed)")
print("=" * 60)

# Load workflow from YAML file
print("\nLoading workflow from workflow1.yml...")
engine = WorkflowEngine.from_yaml_file("workflow1.yml")

# Get and display the input schema
print("\nWorkflow Input Schema:")
print("-" * 30)
input_schema = engine.get_input_schema()
for var_name, var_config in input_schema.items():
    print(f"  Variable: {var_name}")
    print(f"    Type: {var_config['type']}")
    print(f"    Required: {var_config['required']}")
    if var_config.get('description'):
        print(f"    Description: {var_config['description']}")

# Run the workflow with correct input
print("\n" + "=" * 60)
print("Executing workflow...")
print("-" * 30)

# workflow1.yml expects 'dsl' as input (a paragraph type)
test_input = "Convert this text to a robot response"
print(f"Input: dsl = '{test_input}'")

try:
    outputs = engine.run_sync(inputs={"dsl": test_input})

    print("\nWorkflow executed successfully!")
    print("-" * 30)
    print("Outputs:")
    for key, value in outputs.items():
        print(f"  {key}: {value}")

except Exception as e:
    print(f"\nError executing workflow: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
print("Note: The LLM node is using a mock implementation")
print("that returns a robot-themed response.")
print("=" * 60)
