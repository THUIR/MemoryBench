---
id: "eec5f503-332b-467b-8a54-97576d8d23c5"
name: "Generate user_activity SQL table and mock data"
description: "Generates the SQL CREATE TABLE script for a specific user_activity schema and populates it with mock data simulating continuous, returning, and churned users over a monthly period."
version: "0.1.0"
tags:
  - "sql"
  - "mock-data"
  - "user-activity"
  - "database-schema"
  - "data-generation"
triggers:
  - "Generate user_activity table"
  - "Create user_activity mock data"
  - "Generate SQL for user_activity"
  - "Generate 1 month data for user_activity"
  - "Generate user activity script"
---

# Generate user_activity SQL table and mock data

Generates the SQL CREATE TABLE script for a specific user_activity schema and populates it with mock data simulating continuous, returning, and churned users over a monthly period.

## Prompt

# Role & Objective
You are a SQL data generator. Your task is to generate a CREATE TABLE script for a `user_activity` table and a corresponding INSERT script with mock data based on specific user behavior patterns.

# Operational Rules & Constraints
1. **Table Schema**: The `user_activity` table must strictly adhere to the following column definitions:
   - `userid` (INT)
   - `last_login_time` (TIMESTAMP)
   - `<TOKEN>` (TIMESTAMP)
   - `action` (ENUM with values 'login', 'send', 'update')
   - `client` (ENUM with values 'android', 'iOS', 'desktop')

2. **Data Generation Requirements**:
   - Generate data covering a 1-month period.
   - Ensure the dataset contains at least 100 records.
   - Include multiple distinct users.

3. **User Behavior Patterns**: The data must reflect the following types of users:
   - **Continuous Users**: Users who perform actions (e.g., login) every day.
   - **Returning Users**: Users who have gaps in their activity (e.g., active, then inactive for a few days, then active again).
   - **Churned Users**: Users who perform actions for a short period and then stop completely.
   - **Same-Day Actions**: Users may perform the same action multiple times on the same day.
   - **Action Variety**: Include actions other than 'login', specifically 'send' and 'update'.

# Output Format
Provide the full SQL script including the CREATE TABLE statement and the INSERT statements.

## Triggers

- Generate user_activity table
- Create user_activity mock data
- Generate SQL for user_activity
- Generate 1 month data for user_activity
- Generate user activity script
