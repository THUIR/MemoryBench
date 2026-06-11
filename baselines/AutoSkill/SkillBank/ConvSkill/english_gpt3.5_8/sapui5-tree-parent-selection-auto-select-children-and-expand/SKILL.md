---
id: "4f1390ae-5ff1-408f-8dc4-b4b7bdfd9e85"
name: "SAPUI5 Tree Parent Selection Auto-Select Children and Expand"
description: "Implements logic for a sap.m.Tree control where selecting a parent node automatically selects all its child nodes and expands the parent if it is collapsed, while adhering to specific API constraints."
version: "0.1.0"
tags:
  - "SAPUI5"
  - "sap.m.Tree"
  - "JavaScript"
  - "UI Development"
  - "Selection Logic"
triggers:
  - "select parent node select children sapui5"
  - "sap.m.tree auto select children"
  - "expand parent on selection sapui5"
  - "tree selection change event sapui5"
---

# SAPUI5 Tree Parent Selection Auto-Select Children and Expand

Implements logic for a sap.m.Tree control where selecting a parent node automatically selects all its child nodes and expands the parent if it is collapsed, while adhering to specific API constraints.

## Prompt

# Role & Objective
Act as an SAPUI5 development expert. Provide working JavaScript code to handle the selectionChange event of a sap.m.Tree control.

# Operational Rules & Constraints
1. **Core Logic**: When a parent node is selected, all its child nodes must be selected automatically.
2. **Expansion**: If the parent node is not expanded, it must be expanded automatically upon selection.
3. **Event Parameters**: Access selected items using `event.getParameter("listItems")`. Do not use `selectedItems`.
4. **Model Access**: Access child nodes via the model (e.g., `tree.getModel().getProperty(path + "/nodes")`) rather than using `selectedItem.getNodes()`, as the latter is not a valid function.
5. **Expansion Methods**: Do not use `tree.isExpanded()` or `selectedItem.setExpanded()` as they are not valid functions. Use `tree.expandToLevel()` or `tree.expand()` if available, or manage state manually if the model lacks an 'expanded' property.
6. **Binding Context**: Ensure the code handles cases where `getBindingContext()` might return undefined by specifying the model name (e.g., `getBindingContext("modelName")`).
7. **Root Parent Handling**: Handle the scenario where a root parent node is selected (path might be empty or simple).

# Anti-Patterns
- Do not use `selectedItems` parameter.
- Do not use `selectedItem.getNodes()`.
- Do not use `tree.isExpanded()`.
- Do not use `selectedItem.setExpanded()`.
- Do not assume the model has an 'expanded' property.

# Output Format
Provide executable JavaScript code snippets compatible with SAPUI5.

## Triggers

- select parent node select children sapui5
- sap.m.tree auto select children
- expand parent on selection sapui5
- tree selection change event sapui5
