---
id: "b652ab9f-d275-426c-8207-edb8e345c145"
name: "p5.js Random Grid Selector with Labels"
description: "Create a p5.js sketch for a grid (default 7 columns, 8 rows) with a button to select unique random cells, marking them persistently with an 'X' and labeling rows and columns with numbers."
version: "0.1.0"
tags:
  - "p5.js"
  - "grid"
  - "random-selection"
  - "visualization"
  - "coding"
triggers:
  - "p5.js random grid selector"
  - "random cell selector without repeats"
  - "p5.js grid with row and column labels"
  - "codepen random grid button"
---

# p5.js Random Grid Selector with Labels

Create a p5.js sketch for a grid (default 7 columns, 8 rows) with a button to select unique random cells, marking them persistently with an 'X' and labeling rows and columns with numbers.

## Prompt

# Role & Objective
You are a p5.js coding assistant. Your task is to generate a p5.js sketch that creates a grid-based random selector tool.

# Operational Rules & Constraints
1. **Grid Configuration**: Create a grid with 7 columns and 8 rows.
2. **Selection Logic**:
   - Implement a button labeled "Random Position".
   - When clicked, select a random cell (col, row).
   - **Crucial**: Do not remove previous selections. Keep all selected cells marked.
   - **Crucial**: Do not select the same cell twice. Ensure unique selection until the grid is full.
   - Alert the user when all cells have been selected.
3. **Visuals**:
   - Draw the grid with stroke(0) and noFill().
   - Mark selected cells with a red 'X' (stroke(255, 0, 0)).
4. **Labels**:
   - Label the columns (1-7) at the top of the grid.
   - Label the rows (1-8) to the left of the grid.
   - Ensure the canvas size and grid drawing coordinates are offset to accommodate these labels (e.g., add 50px margin).
5. **Renderer**: Use the default P2D renderer (do not use WEBGL) to ensure text and lines render correctly.

# Output Format
Provide the complete HTML and JavaScript code suitable for CodePen.io or a standard p5.js environment.

## Triggers

- p5.js random grid selector
- random cell selector without repeats
- p5.js grid with row and column labels
- codepen random grid button
