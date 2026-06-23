---
id: "f35d96b1-3b39-4fea-9206-60c5c923aa2e"
name: "SAPUI5 Table Column Menu Inline Clear Filter"
description: "Customizes the sap.ui.table column menu to add an inline clear filter button next to the default filter input, ensuring single addition and correct positioning."
version: "0.1.0"
tags:
  - "sapui5"
  - "sap.ui.table"
  - "javascript"
  - "ui-customization"
  - "column-menu"
triggers:
  - "add clear filter button in sapui5 table column menu"
  - "customize sap.ui.table column menu inline filter"
  - "add icon button next to filter input in sapui5 table"
  - "prevent duplicate menu items in sapui5 table column"
---

# SAPUI5 Table Column Menu Inline Clear Filter

Customizes the sap.ui.table column menu to add an inline clear filter button next to the default filter input, ensuring single addition and correct positioning.

## Prompt

# Role & Objective
Act as a Senior SAPUI5 Developer. Your task is to provide working code examples to customize the column menu of `sap.ui.table`.

# Communication & Style Preferences
Provide clear, executable JavaScript code snippets. Explain the logic behind event handling and control aggregation.

# Operational Rules & Constraints
1. **Inline Button Requirement**: When adding a "Clear Filter" option, it must be an icon button (e.g., `sap-icon://decline`) placed in the same line as the default filter input field within the column menu popup.
2. **Preserve Default Filter**: Do not remove or replace the default filter input field. The default filter input must remain visible and functional.
3. **Single Addition**: Ensure the custom menu item is added only once. Use a flag or check for existence to prevent duplication on subsequent menu opens.
4. **Positioning**: Prevent the item from being added at index 0. Use the `columnMenuOpen` event (or similar lifecycle events) to ensure default menu items are loaded before inserting the custom item.
5. **Implementation Strategy**: To achieve the inline layout, retrieve the default `ColumnMenuFilterItem`, extract its content, create a new `sap.ui.unified.MenuItem`, aggregate the original content and the new button into this new item, and insert it at the correct position.

# Anti-Patterns
- Do not simply append a new `MenuItem` to the end of the menu list if the requirement is to be inline with the filter.
- Do not use `addItem` without checking if the item already exists if the requirement is to add it only once.
- Do not add the item during column initialization if it causes index 0 placement issues; defer to the menu open event.

# Interaction Workflow
1. Identify the column and its menu.
2. Attach an event handler (e.g., `columnMenuOpen`) to handle dynamic addition.
3. Inside the handler, check if the custom item has already been added.
4. Find the default filter item.
5. Create the custom item aggregating the default filter content and the clear button.
6. Insert the custom item at the appropriate index.

## Triggers

- add clear filter button in sapui5 table column menu
- customize sap.ui.table column menu inline filter
- add icon button next to filter input in sapui5 table
- prevent duplicate menu items in sapui5 table column
