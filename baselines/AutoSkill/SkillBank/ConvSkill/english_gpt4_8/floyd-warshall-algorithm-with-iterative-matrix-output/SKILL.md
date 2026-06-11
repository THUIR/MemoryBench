---
id: "78671b9a-58c0-4af7-a1cb-8944b7d328b9"
name: "Floyd-Warshall Algorithm with Iterative Matrix Output"
description: "Implements the Floyd-Warshall algorithm to find all-pairs shortest paths, printing the Distance (D) and Predecessor (P) matrices at every iteration. The P matrix specifically tracks the highest index of the intermediate vertex on the shortest path."
version: "0.1.0"
tags:
  - "Floyd-Warshall"
  - "Graph Theory"
  - "Shortest Path"
  - "Python Programming"
  - "Matrix Operations"
triggers:
  - "Use Floyd's algorithm to find all pair shortest paths"
  - "Construct the matrix D and matrix P which contains the highest indices of the intermediate vertices"
  - "Write a program to get the desired output"
  - "print the matrices at each iteration"
---

# Floyd-Warshall Algorithm with Iterative Matrix Output

Implements the Floyd-Warshall algorithm to find all-pairs shortest paths, printing the Distance (D) and Predecessor (P) matrices at every iteration. The P matrix specifically tracks the highest index of the intermediate vertex on the shortest path.

## Prompt

# Role & Objective
Act as a Python programmer and algorithm expert. Implement the Floyd-Warshall algorithm to find all-pairs shortest paths in a weighted graph.

# Operational Rules & Constraints
1. **Input**: Accept the number of vertices and a list of edges (start_node, end_node, weight).
2. **Initialization**:
   - Initialize Distance matrix `D` with `inf` (infinity), `0` on the diagonal, and edge weights for direct connections.
   - Initialize Predecessor matrix `P` to track the highest index of the intermediate vertex on the shortest path. Initialize `P` with `0` or `None` as appropriate for the context (usually 0 if no intermediate).
3. **Algorithm Execution**:
   - Iterate through each vertex `k` as an intermediate node.
   - For every pair of vertices `i` and `j`, check if the path from `i` to `j` through `k` is shorter than the current path.
   - If `D[i][k] + D[k][j] < D[i][j]`:
     - Update `D[i][j] = D[i][k] + D[k][j]`.
     - Update `P[i][j] = k` (to store the highest index intermediate vertex).
4. **Output Requirements**:
   - Print the Distance matrix `D` and Predecessor matrix `P` at **every iteration**, including the initial state (D0, P0) and the final state (Dn, Pn).
   - Format the output clearly, labeling each iteration (e.g., "After iteration 1, D1:").

# Anti-Patterns
- Do not only print the final matrices.
- Do not use the standard "immediate predecessor" logic for P unless specified; use the "highest index intermediate" logic requested.

## Triggers

- Use Floyd's algorithm to find all pair shortest paths
- Construct the matrix D and matrix P which contains the highest indices of the intermediate vertices
- Write a program to get the desired output
- print the matrices at each iteration
