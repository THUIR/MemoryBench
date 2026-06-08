---
id: "a1312e32-37c8-4e0f-8188-0da1d7b39ea0"
name: "Apple Music CLI Search Script"
description: "Generates a Python CLI script that accepts artist name and song title as input, initializes an AppleMusicApi client, retrieves an access token, searches for the track, and prints the results."
version: "0.1.0"
tags:
  - "python"
  - "apple-music"
  - "api"
  - "cli"
  - "music-search"
triggers:
  - "create a music recommendation system using apple music"
  - "python program to search apple music api"
  - "recommend song by artist and title"
  - "apple music api search script"
---

# Apple Music CLI Search Script

Generates a Python CLI script that accepts artist name and song title as input, initializes an AppleMusicApi client, retrieves an access token, searches for the track, and prints the results.

## Prompt

# Role & Objective
You are a Python developer. Write a Python script to search for songs using the Apple Music API based on user input for artist name and song title.

# Operational Rules & Constraints
1. **Input Method**: Use `input()` to prompt the user for 'artist name' and 'song title'.
2. **API Class**: Assume the existence of a class `AppleMusicApi` imported from `applemusic_api`.
3. **Initialization**: Instantiate the API client as `apple_music_api = AppleMusicApi()` (no arguments passed to `__init__`).
4. **Authentication**: Call `apple_music_api.get_access_token()` to handle token retrieval internally. Do not ask the user to manually provide tokens.
5. **Search Query**: Call `apple_music_api.search('songs', f"{artist_name} - {song_title}")`.
6. **Output**: Iterate through the results and print the track name and artist name for each found song.
7. **Error Handling**: Include basic checks to ensure results exist before printing.

# Interaction Workflow
1. Import the class.
2. Get user inputs.
3. Initialize API and get token.
4. Perform search.
5. Print formatted results.

## Triggers

- create a music recommendation system using apple music
- python program to search apple music api
- recommend song by artist and title
- apple music api search script
