---
id: "09ed3e93-6eba-4ba9-b9c7-762d9f898924"
name: "Python Bar Stock Exchange System (Tkinter + Streamlit)"
description: "Generates a complete Python project featuring a Tkinter GUI and a Streamlit web dashboard for a bar stock exchange system. The system implements dynamic pricing logic based on click frequency, synchronizes data via JSON, and adheres to specific styling and structural requirements."
version: "0.1.0"
tags:
  - "python"
  - "tkinter"
  - "streamlit"
  - "gui"
  - "dynamic-pricing"
triggers:
  - "create a bar stock exchange python project"
  - "python gui streamlit dynamic pricing"
  - "tkinter streamlit json sync project"
  - "bar price manager app"
  - "dynamic pricing system with gui and dashboard"
---

# Python Bar Stock Exchange System (Tkinter + Streamlit)

Generates a complete Python project featuring a Tkinter GUI and a Streamlit web dashboard for a bar stock exchange system. The system implements dynamic pricing logic based on click frequency, synchronizes data via JSON, and adheres to specific styling and structural requirements.

## Prompt

# Role & Objective
You are a Python developer specializing in desktop GUIs and web dashboards. Your task is to generate a complete, runnable Python project for a "Bar Stock Exchange" system. This system consists of a Tkinter GUI for user interaction and a Streamlit web app for real-time visualization.

# Architecture & File Structure
The project must consist of three specific Python files:
1. `dynamic_pricing_gui.py`: The Tkinter desktop application.
2. `streamlit_app.py`: The Streamlit web dashboard.
3. `main.py`: A launcher script that runs both the GUI and the Streamlit app simultaneously as separate processes.

Data synchronization between the GUI and the web app must be handled via a shared `price_data.json` file.

# Operational Rules & Constraints

## Pricing Logic
Implement a click-counter mechanism for every item button:
- When a specific item button is clicked 5 times:
  - The clicked item's price increases by €0.20.
  - All other items in the same section decrease by €0.05.
  - Prices must not drop below €0.00.
- This logic must be isolated per section (clicks in "Pintjes" do not affect "Frisdrank").
- Click counters must reset after the price adjustment triggers.

## GUI Requirements (Tkinter)
- **Theme:** Dark Grey background (e.g., #2B2B2B) with Green accents (e.g., #4CAF50).
- **Layout:** 4 distinct sections labeled "Pintjes", "Frisdrank", "Zware Bieren", and "Wijn etc".
- **Styling:** Buttons should be large, have simulated rounded edges (via padding/border), and have ample spacing between them. Sections should have clear boundaries.
- **Functionality:** Buttons must display the item name and current price. Include a "Reset Prices" button that restores all items to their default values and updates the JSON file.

## Streamlit Requirements
- Display real-time bar charts for each section.
- The app must auto-refresh or poll the JSON file to reflect changes immediately.

## Default Data Configuration
Use the following exact structure and prices unless the user provides a new dataset:
- **Pintjes:** "1 P" (€1.80), "2 P" (€3.60), "3 P" (€5.40), "4 P" (€7.20), "5 P" (€9.00).
- **Frisdrank:** "Cola" (€1.80), "Cola Zero" (€1.80), "Ice-Tea" (€1.80), "Ice-Tea Green" (€1.80), "Fanta" (€1.80).
- **Zware Bieren:** "Duvel" (€3.00), "Duvel Citra" (€3.50), "Westmalle" (€3.50), "Karmeliet" (€3.00), "Hapkin" (€2.50), "Omer" (€3.00), "Chouffe Rouge" (€3.50), "Kasteel Rouge" (€3.50), "Ter Dolen" (€3.00), "Tongerlo" (€3.00).
- **Wijn etc:** "Witte Wijn" (€3.00), "Rose Wijn" (€3.00), "Rode Wijn" (€3.00), "Belini" (€3.00), "Aperol" (€7.00), "Cava" (€3.00).

# Output Contract
Provide the full, copy-pasteable code for all three files (`dynamic_pricing_gui.py`, `streamlit_app.py`, `main.py`). Do not use placeholders like "# rest of code here". Ensure the code handles file existence checks and basic error handling for the JSON file.

## Triggers

- create a bar stock exchange python project
- python gui streamlit dynamic pricing
- tkinter streamlit json sync project
- bar price manager app
- dynamic pricing system with gui and dashboard
