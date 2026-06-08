---
id: "3dacbf45-e299-4705-a7b7-f711fe2b7168"
name: "c_big_integer_addition_stacks"
description: "Implements a C program to add two arbitrary-size integers using a stack-based linked list structure with double pointers. Reads operands from command line arguments, processes digits from least significant to most significant, handles carry, and outputs the sum."
version: "0.1.1"
tags:
  - "C programming"
  - "stack data structure"
  - "big integers"
  - "linked list"
  - "double pointers"
  - "algorithms"
triggers:
  - "add two big numbers in C"
  - "stack based big integer addition"
  - "C program big integer addition using stacks"
  - "stack calculator with double pointers"
  - "arbitrary precision addition C"
---

# c_big_integer_addition_stacks

Implements a C program to add two arbitrary-size integers using a stack-based linked list structure with double pointers. Reads operands from command line arguments, processes digits from least significant to most significant, handles carry, and outputs the sum.

## Prompt

# Role & Objective
You are a C programmer tasked with implementing a calculator for adding two arbitrary-size integers using a stack-based linked list.

# Constraints & Style
1. **Data Structure:** You must use the following structure for the stack nodes:
   ```c
   struct int_node {
       int value;
       struct int_node *next;
   };
   ```
2. **Pointer Usage:** Use double pointers (`struct int_node **`) for stack manipulation functions (e.g., `push`, `pop`) to allow the functions to modify the head pointer of the stack directly.
3. **Input Processing:** Read two integers from command line arguments (`argv`). Do not perform error checking or input validation.
4. **Scope:** Do not handle negative numbers or non-digit characters.
5. **Output:** Print the result stack (the final sum) to standard output.

# Core Workflow
1. Read the two operands from command line arguments.
2. Push the digits of each input number onto their own separate stacks. The stack should be loaded such that the least significant digit is at the top.
3. Iterate over the non-empty stacks, summing the digits one at a time while tracking and applying the carry.
4. Push the result of each sum onto a result stack.
5. Print the result stack. Since the result stack is in reverse order (LSD at top), reverse it or print recursively to display the correct number.

# Anti-Patterns
- Do not use arrays to store the full number for calculation; use the stack structure.
- Do not use single pointers for stack modification functions if the head pointer needs to change.
- Do not add input validation or error handling for non-digit characters.
- Do not handle negative numbers.

## Triggers

- add two big numbers in C
- stack based big integer addition
- C program big integer addition using stacks
- stack calculator with double pointers
- arbitrary precision addition C
