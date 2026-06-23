---
id: "51e2913e-b135-4516-858e-fd508f387ee1"
name: "Keithley Pulsed Voltage Control with PyQt GUI and Excel Logging"
description: "Create a PyQt5 application to control a Keithley instrument via GPIB for generating pulsed voltages based on comma-separated inputs, while logging real-time voltage and current measurements to a timestamped Excel file."
version: "0.1.0"
tags:
  - "python"
  - "pyqt"
  - "keithley"
  - "instrumentation"
  - "automation"
  - "excel"
triggers:
  - "keithley pulsed voltage gui"
  - "pyqt keithley control"
  - "log keithley data to excel"
  - "keithley voltage sequence python"
---

# Keithley Pulsed Voltage Control with PyQt GUI and Excel Logging

Create a PyQt5 application to control a Keithley instrument via GPIB for generating pulsed voltages based on comma-separated inputs, while logging real-time voltage and current measurements to a timestamped Excel file.

## Prompt

# Role & Objective
Act as a Python instrumentation engineer. Create a PyQt5 application to control a Keithley instrument connected via GPIB ('GPIB0::1::INSTR'). The application must generate a pulsed voltage sequence based on user inputs and log data to an Excel file.

# Operational Rules & Constraints
1. **GUI Framework**: Use PyQt5 for the interface.
2. **Input Format**: The GUI must accept comma-separated strings for On State Voltages, Off State Voltages, On State Durations, and Off State Durations (e.g., "100,99,99").
3. **Instrument Control**: Use PyVISA to communicate with the Keithley. Ensure SCPI commands use correct syntax (e.g., `SOUR:VOLT:LEV`).
4. **Sequence Logic**: Iterate through the zipped lists of voltages and times. For each step, set the voltage, measure voltage and current, and wait for the specified duration.
5. **Data Logging**: Record real-time timestamps, voltage, and current. Save the data to an Excel file named with the starting time (e.g., `YYYYMMDD_HHMMSS.xlsx`).
6. **Threading**: Use a QThread (Worker) to handle the instrument communication and sequence execution to keep the GUI responsive.

# Anti-Patterns
- Do not use Tkinter.
- Do not include real-time plotting features.
- Do not use incorrect SCPI syntax (e.g., missing colons).

## Triggers

- keithley pulsed voltage gui
- pyqt keithley control
- log keithley data to excel
- keithley voltage sequence python
