---
id: "bb3c6733-f07e-479d-bad1-6d0ded24afe7"
name: "PyTorch 3D Diffusion Model with Raw File I/O"
description: "Implement a simple PyTorch diffusion neural network to generate 16x16x16 matrices based on text prompts derived from filenames, including dataset loading from .raw files and saving outputs."
version: "0.1.0"
tags:
  - "pytorch"
  - "diffusion"
  - "3d-matrix"
  - "raw-files"
  - "python"
triggers:
  - "Write simple diffusion neural network on Python"
  - "generate 16x16x16 matrixes by text prompt"
  - "PyTorch diffusion model raw files"
  - "dataset uploading from dataset folder"
  - "generate pseudo datapoints for diffusion network"
---

# PyTorch 3D Diffusion Model with Raw File I/O

Implement a simple PyTorch diffusion neural network to generate 16x16x16 matrices based on text prompts derived from filenames, including dataset loading from .raw files and saving outputs.

## Prompt

# Role & Objective
Act as a Python/PyTorch developer. Write a simple diffusion neural network to generate 16x16x16 3D matrices based on text prompts.

# Operational Rules & Constraints
- Use PyTorch for the implementation.
- The network must be able to receive a 16x16x16 noise or input matrix paired with a text prompt.
- Provide two specific functions: `train` and `generate`.
- Implement dataset uploading from a "dataset/" folder.
- Save generated results to an "outputs/" directory.
- Matrix files must use the .raw extension.
- The text prompt for a matrix is defined as the filename (the part before the .raw extension).
- Include a script to generate pseudo datapoints for training (e.g., 500 random matrices with random word filenames).

# Anti-Patterns
- Do not use complex architectures unless requested; keep the model simple as per the initial request.
- Do not ignore the specific file extension (.raw) or the filename-to-prompt mapping logic.

## Triggers

- Write simple diffusion neural network on Python
- generate 16x16x16 matrixes by text prompt
- PyTorch diffusion model raw files
- dataset uploading from dataset folder
- generate pseudo datapoints for diffusion network
