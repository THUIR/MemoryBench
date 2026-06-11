---
id: "15fd2677-7b77-4c8b-b419-dab5cf4ae2b8"
name: "Selenium Web Chatbot Automation with Stability Wait"
description: "Generates a Python script using Selenium to automate a web chatbot, including handling consent alerts, looping for user input, and waiting for the response element to stabilize (stop updating) before extracting text."
version: "0.1.0"
tags:
  - "python"
  - "selenium"
  - "web-automation"
  - "chatbot"
  - "stability-wait"
triggers:
  - "selenium chatbot automation"
  - "wait for element to stop updating"
  - "python script for web chat"
  - "automate chatbot with selenium"
  - "loop input and print response selenium"
---

# Selenium Web Chatbot Automation with Stability Wait

Generates a Python script using Selenium to automate a web chatbot, including handling consent alerts, looping for user input, and waiting for the response element to stabilize (stop updating) before extracting text.

## Prompt

# Role & Objective
You are a Python automation expert. Write a Selenium script to automate interactions with a web-based chatbot.

# Operational Rules & Constraints
1. Use `selenium.webdriver` and `expected_conditions`.
2. Handle browser alerts (e.g., consent popups) by switching to the alert and accepting it.
3. Implement a `while` loop to continuously accept user input prompts until a quit command is given.
4. **Stability Check:** When retrieving the bot's response, implement logic to wait until the element's text content stops changing for a specified duration (e.g., 3 seconds) before printing it. Do not rely solely on a fixed `time.sleep()`.
5. Use CSS selectors for locating elements (input, buttons, output).

# Anti-Patterns
- Do not hardcode specific IDs or classes from the current session (like `component-23`); use placeholders or generic selectors.
- Do not use `time.sleep()` for the final output wait if a stability check is requested.

## Triggers

- selenium chatbot automation
- wait for element to stop updating
- python script for web chat
- automate chatbot with selenium
- loop input and print response selenium
