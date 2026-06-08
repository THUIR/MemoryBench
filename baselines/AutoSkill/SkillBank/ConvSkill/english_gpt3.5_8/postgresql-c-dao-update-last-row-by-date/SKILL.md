---
id: "9dcee155-3386-42df-9b0c-bfbaeda74795"
name: "PostgreSQL C# DAO Update Last Row by Date"
description: "Generates SQL update scripts using Common Table Expressions (CTE) and corresponding C# DAO code using IDbConnection to update the runId of the most recent record for a specific user, including logic for filtering by Unix timestamp dates."
version: "0.1.0"
tags:
  - "postgresql"
  - "c#"
  - "dao"
  - "sql-update"
  - "unix-timestamp"
triggers:
  - "update last row postgresql c#"
  - "generate dao update script"
  - "sql cte update latest record"
  - "idbconnection postgres update"
---

# PostgreSQL C# DAO Update Last Row by Date

Generates SQL update scripts using Common Table Expressions (CTE) and corresponding C# DAO code using IDbConnection to update the runId of the most recent record for a specific user, including logic for filtering by Unix timestamp dates.

## Prompt

# Role & Objective
Act as a C# and PostgreSQL developer. Generate SQL update scripts and C# DAO code to update the 'runId' of the most recent row for a specific user in a PostgreSQL table.

# Operational Rules & Constraints
1. **SQL Structure**: Use a Common Table Expression (CTE) to identify the row to update.
   - The CTE must select the row where "user" matches the input and "runId" IS NULL.
   - Order by `date` DESC and LIMIT 1 to get the last row.
   - The UPDATE statement must join the target table with the CTE on the `id` column.
   - Example SQL structure:
     ```sql
     WITH cte_table AS (
         SELECT *
         FROM public."TableName"
         WHERE "user" = @user AND "runId" IS NULL
         ORDER BY date DESC
         LIMIT 1
     )
     UPDATE public."TableName"
     SET "runId" = @newRunId
     FROM cte_table
     WHERE public."TableName".id = cte_table.id;
     ```
2. **Identifier Quoting**: Always use standard double quotes (") for table and column names, never smart quotes.
3. **C# Implementation**: Use `IDbConnection` and `IDbCommand` interfaces.
   - Use parameterized queries (`@parameterName`) to prevent SQL injection.
   - Ensure connection is opened and disposed properly (using `using` blocks or try/finally).
4. **Unix Time Filtering**: When filtering by a Unix timestamp integer column to match "today", convert the database integer to a timestamp and compare only the date part, ignoring time components (e.g., using `TO_TIMESTAMP` and casting to date).

# Interaction Workflow
1. Receive the table name and parameters (user, new runId).
2. Generate the SQL script following the CTE pattern.
3. Generate the C# method implementing the query using `IDbConnection`.

## Triggers

- update last row postgresql c#
- generate dao update script
- sql cte update latest record
- idbconnection postgres update
