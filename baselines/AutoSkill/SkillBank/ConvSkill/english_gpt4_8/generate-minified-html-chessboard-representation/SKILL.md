---
id: "26e2e694-d130-4c70-8e91-5c358a918658"
name: "Generate Minified HTML Chessboard Representation"
description: "Generates a highly minified HTML/CSS string for a chessboard position using specific tags and placement rules within a strict character limit."
version: "0.1.0"
tags:
  - "html"
  - "css"
  - "chess"
  - "minification"
  - "code-golf"
triggers:
  - "generate minified chessboard"
  - "arrange pieces for famous game"
  - "create leet chessboard"
  - "minify chess html code"
---

# Generate Minified HTML Chessboard Representation

Generates a highly minified HTML/CSS string for a chessboard position using specific tags and placement rules within a strict character limit.

## Prompt

# Role & Objective
Generate a minified HTML/CSS representation of a chessboard for a specific game or position requested by the user.

# Operational Rules & Constraints
1. **Base Format**: Use the structure `<style>p{color:#862}b{position:absolute}</style><p>...</p>`.
2. **Tag Selection**: Use `p` for the container and `b` for piece tags to minimize character count.
3. **Piece Placement**: Place piece tags (`<b>piece</b>`) immediately before the cell character (`⬛` or `⬜`) they occupy.
4. **Board Integrity**: Maintain the 8x8 grid using `⬛` and `⬜` for cells and `<br>` for row breaks. Do not alter the cell sequence.
5. **Minification**: Ensure the total code length is minimized (aiming for ~409 characters or less).
6. **Scope**: Only modify the position of pieces; keep the board field solid and intact.

## Triggers

- generate minified chessboard
- arrange pieces for famous game
- create leet chessboard
- minify chess html code
