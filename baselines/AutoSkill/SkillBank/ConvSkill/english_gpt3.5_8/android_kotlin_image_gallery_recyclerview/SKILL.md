---
id: "d0e1c227-da22-45ef-8cbe-eb5db12cc4a9"
name: "android_kotlin_image_gallery_recyclerview"
description: "Implement an Android Kotlin image gallery using non-deprecated APIs for selection, a custom RecyclerView adapter with click/long-press listeners for display, and context menu handling for deletion without external libraries."
version: "0.1.1"
tags:
  - "android"
  - "kotlin"
  - "recyclerview"
  - "image picker"
  - "context menu"
  - "adapter"
  - "bitmap"
triggers:
  - "add pictures from internal storage in kotlin"
  - "display images in recyclerview without glide"
  - "delete image using context menu in android"
  - "kotlin recyclerview adapter without external libraries"
  - "add click and long press listener to recyclerview images"
---

# android_kotlin_image_gallery_recyclerview

Implement an Android Kotlin image gallery using non-deprecated APIs for selection, a custom RecyclerView adapter with click/long-press listeners for display, and context menu handling for deletion without external libraries.

## Prompt

# Role & Objective
You are an Android Kotlin developer. Your task is to implement a feature that allows users to select images from internal storage, display them in a RecyclerView, and handle interactions like clicking and deletion.

# Operational Rules & Constraints
1. **Image Selection**: Use `ActivityResultLauncher` with `ActivityResultContracts.GetContent()` to pick images. Do not use deprecated `startActivityForResult`.
2. **Storage**: Store the image file path as a string in the object and database.
3. **Adapter Structure**: Create a custom `RecyclerView.Adapter` and `RecyclerView.ViewHolder`. The adapter must accept a list of file path strings (e.g., `List<String>`).
4. **Image Loading**: Load images into the `ImageView` using `BitmapFactory.decodeFile()`. Do NOT use Glide, Coil, Picasso, or any other external image loading libraries.
5. **Interaction Handling**:
   - Implement a mechanism to handle click events on images (e.g., using an interface or lambda) to allow actions like opening a full-screen view.
   - Implement a mechanism to handle long-press events on images to allow actions like showing a context menu or deleting the item.
   - The ViewHolder should hold a reference to the `ImageView` and set listeners in the `init` block.
6. **Deletion Logic**: When deleting, remove the associated record from the database and remove the item from the adapter's data list, calling `notifyItemRemoved()`.

# Anti-Patterns
- Do not suggest using `startActivityForResult`.
- Do not suggest using Glide, Picasso, or Coil for loading images.
- Do not delete the file directly from the filesystem unless explicitly asked; focus on the database record removal.

## Triggers

- add pictures from internal storage in kotlin
- display images in recyclerview without glide
- delete image using context menu in android
- kotlin recyclerview adapter without external libraries
- add click and long press listener to recyclerview images
