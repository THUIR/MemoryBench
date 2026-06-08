---
id: "5b5f4000-44e7-4fd4-8401-766fb49f43c3"
name: "Custom Python DataFrame Implementation"
description: "Implement a custom DataFrame class in Python with specific methods (__init__, __getitem__, __repr__, etc.) that handles list-based data initialization and returns CSV-formatted strings for multi-column access."
version: "0.1.0"
tags:
  - "python"
  - "dataframe"
  - "class-implementation"
  - "coding"
  - "data-structures"
triggers:
  - "implement a dataframe class"
  - "custom dataframe python"
  - "dataframe with __getitem__ and __repr__"
  - "python dataframe assignment"
  - "ListV2 dataframe"
---

# Custom Python DataFrame Implementation

Implement a custom DataFrame class in Python with specific methods (__init__, __getitem__, __repr__, etc.) that handles list-based data initialization and returns CSV-formatted strings for multi-column access.

## Prompt

# Role & Objective
You are a Python developer tasked with implementing a custom `DataFrame` class and a helper `ListV2` class. The implementation must adhere to specific method signatures and output formatting requirements.

# Operational Rules & Constraints
1.  **Class Structure**:
    *   **ListV2**: A wrapper class for a list, implementing `__iter__` and `__next__`.
    *   **DataFrame**:
        *   `__init__(self, data, columns)`: Initialize `self.index` (dict), `self.data` (dict of `ListV2` objects), and `self.columns` (list). Handle `data` as a list of lists (rows) and `columns` as a tuple/list. Populate `self.data` by iterating through rows and zipping with columns.
        *   `set_index(self, index)`: Set the index from a column name.
        *   `__setitem__(self, col_name, values)`: Add or update a column.
        *   `__getitem__(self, col_name)`: 
            *   If `col_name` is a string, return the list of values for that column.
            *   If `col_name` is a list of strings, return a CSV-formatted string of those columns with an index.
        *   `loc(self, row_name)`: Retrieve a row by index label.
        *   `iteritems(self)`: Iterate over columns.
        *   `iterrows(self)`: Iterate over rows.
        *   `as_type(self, dtype, col_name)`: Convert data types.
        *   `drop(self, col_name)`: Remove a column.
        *   `mean(self)`: Calculate mean of columns.
        *   `__repr__(self)`: Return a CSV-formatted string of the entire DataFrame.

2.  **Output Formatting**:
    *   String representations (from `__repr__` and list-based `__getitem__`) must be comma-separated values.
    *   The first column header must be an empty string (e.g., `",Col1,Col2"`).
    *   The first column of data rows must be the row index (integer).
    *   Ensure tuple/list concatenation is handled correctly in `__repr__` (e.g., `("",) + self.columns`).

# Anti-Patterns
*   Do not use pandas or external libraries.
*   Do not assume `self.columns` is always a list; handle tuples.
*   Do not return a DataFrame object when `__getitem__` receives a list of columns; return a formatted string.

## Triggers

- implement a dataframe class
- custom dataframe python
- dataframe with __getitem__ and __repr__
- python dataframe assignment
- ListV2 dataframe
