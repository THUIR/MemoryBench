---
id: "5e6ed013-e388-4c28-8923-4a5f08508e98"
name: "leaflet_cost_validated_map_placement_with_bounds"
description: "Implements a workflow where a user triggers placement via a button, validates a cost condition, draws a polyline and marker from a fixed start point, deducts the cost, fits the map bounds to the new feature, and cleans up event listeners."
version: "0.1.1"
tags:
  - "leaflet"
  - "javascript"
  - "map-interaction"
  - "event-listeners"
  - "game-logic"
  - "bounds-fitting"
triggers:
  - "add a station to the map"
  - "leaflet interaction with money check"
  - "draw polyline and marker on click"
  - "implement map placement workflow"
  - "set the map bounds after the polyline is added"
---

# leaflet_cost_validated_map_placement_with_bounds

Implements a workflow where a user triggers placement via a button, validates a cost condition, draws a polyline and marker from a fixed start point, deducts the cost, fits the map bounds to the new feature, and cleans up event listeners.

## Prompt

# Role & Objective
Act as a JavaScript/Leaflet.js developer. Implement a map interaction workflow where a user triggers a placement mode via a button, clicks the map to place an item (polyline and marker), subject to a cost validation check, and automatically adjusts the map view to fit the new feature.

# Operational Rules & Constraints
1. **Trigger**: Set up an event listener on a specific button (e.g., ID 'newStation').
2. **Map Interaction**: When the button is clicked, attach a `click` event listener to the map object.
3. **Validation**: Inside the map click handler, check a condition (e.g., `money <= <NUM>`) before proceeding.
4. **Visuals**:
   - Create a `L.polyline` connecting a fixed start coordinate (e.g., `secondCityCoords`) to the clicked location (`e.latlng`).
   - Create a `L.circleMarker` at the clicked location.
   - **Bounds Fitting**: After adding the polyline, set the map bounds to fit the area of the polyline using `map.fitBounds(polyline.getBounds())`.
5. **State Update**: Deduct the cost from the money variable (e.g., `money -= <NUM>`).
6. **Cleanup**: Remove the map click event listener immediately after the item is placed using `map.off('click', handlerFunction)`.
7. **Marker Interaction**: Add a click event listener to the newly created marker to log a message to the console.

# Anti-Patterns
- Do not leave the map click listener active after placement.
- Do not perform the action if the cost validation fails.
- Do not forget to fit the map bounds after drawing the polyline.

## Triggers

- add a station to the map
- leaflet interaction with money check
- draw polyline and marker on click
- implement map placement workflow
- set the map bounds after the polyline is added
