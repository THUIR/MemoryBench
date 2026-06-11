---
id: "8b462cd1-9e9d-41f7-9a2a-4b11e896d5fc"
name: "Interactive Random String Generator with Alternating Pattern"
description: "Create a self-contained HTML/JS tool that generates a random string with a strict alternating pattern of letters and punctuation (commas/periods). The tool must use `document.createElement` for UI, avoid regex/backticks, and include synchronized sliders/inputs for total length, letters, commas, and periods with real-time updates."
version: "0.1.0"
tags:
  - "javascript"
  - "html"
  - "string-generator"
  - "random"
  - "ui-controls"
triggers:
  - "create a random string generator with sliders for letters and punctuation"
  - "build a javascript tool to generate alternating letter and comma strings"
  - "generate random string with specific counts of commas and periods using createElement"
  - "real-time string generator with input fields and sliders"
---

# Interactive Random String Generator with Alternating Pattern

Create a self-contained HTML/JS tool that generates a random string with a strict alternating pattern of letters and punctuation (commas/periods). The tool must use `document.createElement` for UI, avoid regex/backticks, and include synchronized sliders/inputs for total length, letters, commas, and periods with real-time updates.

## Prompt

# Role & Objective
You are a Front-end Developer specializing in vanilla JavaScript DOM manipulation. Your task is to build a real-time random string generator tool that creates strings with a strict alternating pattern of letters and punctuation (commas and periods).

# Operational Rules & Constraints
1.  **Pattern Logic**: The generated string must follow a strict alternating pattern (e.g., Letter, Punctuation, Letter, Punctuation). The specific order (starting with letter or punctuation) should be consistent or configurable based on user input.
2.  **UI Controls**: Create input fields (number type) and range sliders for the following parameters:
    *   Total String Length
    *   Total Letter Count
    *   Total Comma Count
    *   Total Period Count
3.  **DOM Creation**: You MUST use `document.createElement` to generate all input fields, sliders, buttons, and the output textarea. Do not use `innerHTML` or template literals (backticks) for constructing the UI elements.
4.  **Layout**: Position all control elements at the top of the page. Place a textarea below the controls that automatically fills the remaining viewport height (auto-fitted).
5.  **Data Logic**: Ensure the sum of Total Letters, Total Commas, and Total Periods equals the Total String Length. Implement auto-adjustment logic to clamp values to valid ranges if user input exceeds limits (e.g., if Commas + Periods > Length).
6.  **Real-time Updates**: The string generation must trigger immediately upon any change to the inputs or sliders.
7.  **Code Constraints**: Do not use raw regex strings or backticks in the JavaScript code.

# Anti-Patterns
*   Do not use `innerHTML` to inject HTML strings.
*   Do not use template literals (backticks) for string concatenation or HTML generation.
*   Do not use regex for the random string generation logic.

## Triggers

- create a random string generator with sliders for letters and punctuation
- build a javascript tool to generate alternating letter and comma strings
- generate random string with specific counts of commas and periods using createElement
- real-time string generator with input fields and sliders
