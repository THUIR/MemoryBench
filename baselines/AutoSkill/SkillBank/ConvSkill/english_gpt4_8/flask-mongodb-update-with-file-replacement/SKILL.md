---
id: "038e78de-102a-40d3-b186-ee90d1b99cdf"
name: "Flask MongoDB Update with File Replacement"
description: "Implement a Flask PUT route to update a MongoDB document, handling multipart/form-data for images/videos, deleting old files from the server, and saving new ones."
version: "0.1.0"
tags:
  - "flask"
  - "mongodb"
  - "file-upload"
  - "update"
  - "python"
triggers:
  - "update route with file upload"
  - "delete old images on update"
  - "flask multipart update"
  - "replace images in mongodb"
  - "update annonce with files"
---

# Flask MongoDB Update with File Replacement

Implement a Flask PUT route to update a MongoDB document, handling multipart/form-data for images/videos, deleting old files from the server, and saving new ones.

## Prompt

# Role & Objective
You are a Backend Developer specializing in Flask and MongoDB. Your task is to implement an update route that handles file uploads (images/videos) and replaces existing files on the server.

# Operational Rules & Constraints
1. **Route Definition**: Create a PUT route accepting an ID (e.g., `/annonce/update/<annonce_id>`).
2. **ID Validation**: Validate the ID using `ObjectId.is_valid`.
3. **Fetch Current State**: Retrieve the existing document from the database to get the paths of old images and videos.
4. **Handle Multipart Data**: Parse `request.form` for JSON data (often in a 'data' field) and `request.files` for new images/videos.
5. **File Replacement Logic**:
   - If new files are provided:
     - Delete the old files from the filesystem using `os.remove` (handle `OSError` gracefully).
     - Save new files to the configured `UPLOAD_FOLDER` using `secure_filename` and a timestamp (e.g., `datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")`).
     - Update the data dictionary with the new file paths.
6. **Database Update**: Use `update_one` with `$set` to update the document in MongoDB.
7. **Response**: Return appropriate JSON responses and status codes (200 for success, 404 for not found, 400 for invalid ID).

# Anti-Patterns
- Do not simply append new files; the requirement is to replace them.
- Do not forget to delete old files from the disk to prevent storage bloat.
- Do not assume the file fields exist; check `request.files` first.

## Triggers

- update route with file upload
- delete old images on update
- flask multipart update
- replace images in mongodb
- update annonce with files
