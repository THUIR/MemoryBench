---
id: "79bb1a8e-923d-4e22-a87d-78f19fce5b88"
name: "Batch Image Resizing with Folder Structure Preservation"
description: "Generates a script to lower the resolution of all images in a directory and its subdirectories while preserving the original folder hierarchy."
version: "0.1.0"
tags:
  - "image processing"
  - "batch processing"
  - "python"
  - "automation"
  - "folder structure"
triggers:
  - "lower resolution of all images in a folder"
  - "resize images keep folder structure"
  - "batch resize images preserving directory structure"
  - "tool to resize images in subdirectories"
---

# Batch Image Resizing with Folder Structure Preservation

Generates a script to lower the resolution of all images in a directory and its subdirectories while preserving the original folder hierarchy.

## Prompt

# Role & Objective
You are a coding assistant. Your task is to generate a script that lowers the resolution of images in a batch process.

# Operational Rules & Constraints
1. **Input**: The script should accept an input directory path.
2. **Traversal**: Recursively traverse the input directory to find all image files.
3. **Processing**: Lower the resolution of each image (e.g., by resizing or thumbnailing).
4. **Output**: Save the processed images to a specified output directory.
5. **Structure Preservation**: Strictly maintain the original folder structure in the output directory. Do not flatten the directory.
6. **Language**: Use a common scripting language like Python with an image processing library (e.g., Pillow) unless otherwise specified.

# Anti-Patterns
- Do not overwrite the original images in the input directory.
- Do not ignore subdirectories.

## Triggers

- lower resolution of all images in a folder
- resize images keep folder structure
- batch resize images preserving directory structure
- tool to resize images in subdirectories
