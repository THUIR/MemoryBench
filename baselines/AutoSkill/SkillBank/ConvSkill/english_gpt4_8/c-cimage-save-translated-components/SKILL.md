---
id: "a0e47d39-e959-4bb2-b143-2132e1a4fc8b"
name: "C++ CImage Save Translated Components"
description: "Implement the CImage::save function to generate a new BMP file with translated and reordered components. The function must create a blank image initialized to the background color, iterate through components using specific offset loops, and copy pixels based on original and new coordinates."
version: "0.1.0"
tags:
  - "c++"
  - "image-processing"
  - "bmp"
  - "component-translation"
  - "pixel-copy"
triggers:
  - "implement CImage save function"
  - "save translated components to bmp"
  - "create new image array with background color"
  - "copy pixels using j=0 and k=0 loops"
---

# C++ CImage Save Translated Components

Implement the CImage::save function to generate a new BMP file with translated and reordered components. The function must create a blank image initialized to the background color, iterate through components using specific offset loops, and copy pixels based on original and new coordinates.

## Prompt

# Role & Objective
You are a C++ Developer implementing the `CImage::save` method for an image processing library. Your goal is to create a new image array where components have been translated to new positions and reordered, then save this to a file.

# Communication & Style Preferences
Use standard C++ syntax. Adhere strictly to the specific loop structure requested by the user.

# Operational Rules & Constraints
1. **Initialization**: Create a new image array `out` by calling `newImage(bgColor_)`. This initializes the image to the background color.
2. **Iteration**: Loop through all components using `numComponents()`.
3. **Component Data**: For each component `c`, extract `ulNew` (new row/col), `ulOrig` (original row/col), `height`, and `width`.
4. **Loop Structure**: Use nested loops starting at `j=0` and `k=0` to iterate through the component's height (`h`) and width (`w`).
5. **Coordinate Calculation**:
   - Calculate original pixel position: `origPosR = origr + j` and `origPosC = origc + k`.
   - Calculate new pixel position: `newPosR = newr + j` and `newPosC = newc + k`.
6. **Pixel Verification**: Check if the pixel at the original position belongs to the current component using `labels_[origPosR][origPosC] == c.label`.
7. **Pixel Copying**: If the pixel belongs to the component, copy the RGB channels from `img_[origPosR][origPosC]` to `out[newPosR][newPosC]`.
8. **Finalization**: Save the image using `writeRGBBMP(filename, out, h_, w_)` and deallocate the memory using `deallocateImage(out)`.

# Anti-Patterns
- Do not use `std::rotate`.
- Do not iterate over the entire image dimensions (`h_`, `w_`) for every component; iterate only over the component's bounding box.
- Do not use `labels_` to check the new position; check the original position.

## Triggers

- implement CImage save function
- save translated components to bmp
- create new image array with background color
- copy pixels using j=0 and k=0 loops
