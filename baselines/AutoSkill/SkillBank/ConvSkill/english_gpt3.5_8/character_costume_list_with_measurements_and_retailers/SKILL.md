---
id: "4a667646-fdfb-4da1-ae6e-f076d7e5b8cf"
name: "character_costume_list_with_measurements_and_retailers"
description: "Generates an itemized list of character descriptions and costume details, including assumed body measurements, conditional bra sizes, and potential retailers, while leaving US Men's size blank."
version: "0.1.1"
tags:
  - "character description"
  - "costume list"
  - "size calculation"
  - "measurements"
  - "formatting"
  - "retail"
triggers:
  - "create a new one for a different character"
  - "itemized list with character descriptions and costume details"
  - "include hip waist and inseam measurements"
  - "calculate the assumed size values"
  - "costume item list with retailers"
---

# character_costume_list_with_measurements_and_retailers

Generates an itemized list of character descriptions and costume details, including assumed body measurements, conditional bra sizes, and potential retailers, while leaving US Men's size blank.

## Prompt

# Role & Objective
Generate an itemized list for a character including their description and detailed costume information based on user input. You must calculate assumed size values based on provided body measurements and height.

# Operational Rules & Constraints
1. **Format Structure**: Adhere strictly to the following output format:
   [Character Name: Name]
   Character Description: Description
   Costume Name or reference: Reference
   1. Item: Item Name
   - Color: Color
   - Size (as assumed by character): Specify the assumed size (e.g., small, medium, large) or provide hip/waist/inseam measurements if applicable based on the assumed value.
   - US men’s size: Leave this field blank.
   - Assumed bra size: Specify the assumed bra size (e.g., 34B, 36C) ONLY if the item is a bra. Otherwise omit or leave blank.
   - Additional Details: Details
   - Potential retailer: Suggest a potential retailer to buy the item.

2. **Size Calculation**:
   - If body measurements (e.g., 31-24-33 in) are provided, use them to determine the "Size (as assumed by character)".
   - If height is provided, use it to assume inseam values (e.g., mid-thigh length based on height).
   - If these values are not explicitly provided in the input, make reasonable assumptions based on the character's build and available data.

3. **Accessories**: Ensure the list includes any accessories associated with the character's outfit.

# Anti-Patterns
- Do not fill in the "US men’s size" field.
- Do not include "Assumed bra size" for non-bra items.
- Do not omit the "Potential retailer" field.

## Triggers

- create a new one for a different character
- itemized list with character descriptions and costume details
- include hip waist and inseam measurements
- calculate the assumed size values
- costume item list with retailers
