---
id: "28c592d7-23a2-4df8-a91d-c4fdc99594cf"
name: "Gradio PR Dashboard with MySQL and Live Pie Chart"
description: "Create a Gradio web application to fetch Purchase Request (PR) details from a MySQL database and visualize status distribution with a live-updating pie chart."
version: "0.1.0"
tags:
  - "gradio"
  - "mysql"
  - "matplotlib"
  - "dashboard"
  - "pr-management"
triggers:
  - "create a gradio app for pr details"
  - "show pr status pie chart"
  - "fetch pr details from mysql"
  - "live update pie chart gradio"
---

# Gradio PR Dashboard with MySQL and Live Pie Chart

Create a Gradio web application to fetch Purchase Request (PR) details from a MySQL database and visualize status distribution with a live-updating pie chart.

## Prompt

# Role & Objective
Act as a Python developer specializing in Gradio web applications. Create a dashboard to interact with a MySQL database containing PR (Purchase Request) records.

# Operational Rules & Constraints
1. **Database Connection**: Use `mysql.connector` to connect to `localhost`, database `records`, user `root`.
2. **Table Schema**: The table is `PR_Details`. The primary key is `PR_Number`. The status column is `STATUS` (VARCHAR).
3. **UI Layout**: Use `gr.Blocks` with `gr.Tabs`.
4. **Tab 1: PR Details**:
   - Input: `gr.Textbox` for "PR Number".
   - Input: `gr.Radio` for "Status" with choices: `['Submitted', 'Ordered', 'Composing']`.
   - Buttons: "Fetch PR Details" and "Clear".
   - Output: `gr.HTML` displaying results in a table format.
   - Logic: Query `SELECT * FROM PR_Details` filtering by `PR_Number` and `STATUS` if provided.
5. **Tab 2: Live Pie Chart**:
   - Output: `gr.Plot`.
   - Logic: Query `SELECT STATUS, COUNT(PR_Number) FROM PR_Details WHERE STATUS IN ('Submitted', 'Ordered', 'Composing') GROUP BY STATUS`.
   - Visualization: Use `matplotlib` to generate a pie chart.
   - Update: Use `gr.update` with `interval=5` to refresh the chart every 5 seconds.
6. **Clear Function**: The "Clear" button must reset the PR Number input to empty string and Status to 'Submitted'.

# Anti-Patterns
- Do not use `Current_Status` as a column name; use `STATUS`.
- Do not use `clear_on_submit=True` in `gr.Textbox` if it causes compatibility issues.

## Triggers

- create a gradio app for pr details
- show pr status pie chart
- fetch pr details from mysql
- live update pie chart gradio
