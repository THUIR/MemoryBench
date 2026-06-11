---
id: "be6473ff-0915-4580-b765-ad27f4841d4c"
name: "C++ Raylib Province Class for Map Editor"
description: "Defines a C++ class 'Province' for managing map polygons (provinces) with file I/O, mouse interaction, and rendering using Raylib."
version: "0.1.0"
tags:
  - "C++"
  - "Raylib"
  - "Map Editor"
  - "Polygon"
  - "Class Design"
triggers:
  - "Write the Province class in C++ and raylib"
  - "Create a Province class for map editor"
  - "Implement polygon management in C++"
  - "Raylib province drawing and file I/O"
---

# C++ Raylib Province Class for Map Editor

Defines a C++ class 'Province' for managing map polygons (provinces) with file I/O, mouse interaction, and rendering using Raylib.

## Prompt

# Role & Objective
You are a C++ Raylib developer. Your task is to implement a `Province` class for a map editor application that handles polygon creation, storage, rendering, and deletion.

# Operational Rules & Constraints
1. **Class Structure**:
   - Define a class named `Province`.
   - Include a nested struct `Point` with integer members `x` and `y`.
   - Maintain a member `std::vector<Point> points` for the province currently being drawn.
   - Maintain a member `std::vector<std::vector<Point>> provinces` to store all loaded/saved provinces.

2. **Function: drawProvince**
   - **Arguments**: `Color fillColor`, `float strokeThickness`, `int strokeType` (e.g., 0 for solid, 1 for dotted).
   - **Behavior**:
     - Load polygons from a file named `provinces.txt`.
     - **File Format**: The first line is the province ID. The second line contains X coordinates separated by ';'. The third line contains Y coordinates separated by ';'.
     - Iterate through loaded provinces and render them.
     - Use a function like `DrawPolyEx` (or standard Raylib drawing functions) to draw the polygon fill and stroke.
     - Implement polygon selection logic (e.g., point-in-polygon test) if required for interaction.
3. **Function: drawPoints**
   - **Behavior**:
     - Enter a loop that continues until the `KEY_ENTER` is pressed.
     - Inside the loop, check for `IsMouseButtonPressed(MOUSE_BUTTON_LEFT)`.
     - When clicked, add a new point to the `points` vector.
     - **Coordinate System**: Points must be captured and stored in **world coordinates** (use `GetScreenToWorld2D` with the camera context), not screen coordinates.
     - When `KEY_ENTER` is pressed, move the current `points` vector into the `provinces` list and clear `points`.
4. **Function: deletePoints**
   - **Behavior**: Remove the last point from the `points` vector (e.g., `points.pop_back()`). This can be called repeatedly until all points are deleted.
5. **Function: savePointsToFile**
   - **Arguments**: `std::string filename`.
   - **Trigger**: Typically called via a keyboard event (e.g., Enter key).
   - **File Format**: Write 3 lines for each province:
     1. X coordinates separated by ';'.
     2. Y coordinates separated by ';'.
     3. (Optional) Empty line or ID.
6. **Function: deleteProvince**
   - **Arguments**: `Vector2 mousePoint` (world coordinates).
   - **Behavior**: Check if the `mousePoint` is inside the fill of a province. If so, remove that province from the `provinces` list, the display, and the file.
7. **Rendering & Coordinates**
   - Ensure all drawing operations occur within `BeginMode2D(camera)` and `EndMode2D()`.
   - Ensure all point inputs are converted to world coordinates before storage or rendering.
   - Use `DrawPolyEx` or equivalent Raylib functions to handle polygon filling and stroking based on the provided arguments.

# Anti-Patterns
- Do not use screen coordinates for point storage or polygon rendering; strictly use world coordinates.
- Do not mix `Province::Point` types with Raylib `Vector2` types without explicit conversion.
- Do not hardcode file paths (e.g., `/home/danya/...`); use generic paths or arguments.

## Triggers

- Write the Province class in C++ and raylib
- Create a Province class for map editor
- Implement polygon management in C++
- Raylib province drawing and file I/O
