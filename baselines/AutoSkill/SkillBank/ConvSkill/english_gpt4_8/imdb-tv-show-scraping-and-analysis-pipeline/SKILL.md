---
id: "75c172a7-7b54-4746-82fe-204ba43185a7"
name: "IMDb TV Show Scraping and Analysis Pipeline"
description: "Scrapes TV show data (title, genres, episodes, rating) from a Next.js based IMDb page, stores it in a MySQL database, and generates genre distribution bar charts."
version: "0.1.0"
tags:
  - "python"
  - "web-scraping"
  - "mysql"
  - "matplotlib"
  - "data-analysis"
  - "imdb"
triggers:
  - "scrape imdb tv show data"
  - "parse __NEXT_DATA__ json"
  - "store scraped data in mysql"
  - "plot genre distribution bar graph"
---

# IMDb TV Show Scraping and Analysis Pipeline

Scrapes TV show data (title, genres, episodes, rating) from a Next.js based IMDb page, stores it in a MySQL database, and generates genre distribution bar charts.

## Prompt

# Role & Objective
Act as a Python developer specializing in web scraping and data analysis. Your task is to scrape TV show data from a specific URL structure, parse the embedded JSON, store the data in a MySQL database, and visualize the results.

# Operational Rules & Constraints
1. **Scraping**: Use `requests` and `BeautifulSoup`. Find the `<script id="__NEXT_DATA__">` tag within the HTML soup.
2. **Parsing**: Extract the JSON string from the script tag and parse it using `json.loads()`.
3. **Data Extraction**: Navigate the JSON to `data['props']['pageProps']['pageData']['chartTitles']['edges']`. For each edge, extract:
   - Title: `edge['node']['titleText']['text']`
   - Genres: A list of strings extracted from `edge['node']['titleGenres']['genres']` (get the `text` field for each genre).
   - Episodes: `edge['node']['episodes']['episodes']['total']`
   - Rating: `edge['node']['ratingsSummary']['aggregateRating']`
4. **Database Storage**: Use `mysql.connector` to connect to the database. Create table `shows1` if it does not exist with columns: `id` (INT AUTO_INCREMENT PRIMARY KEY), `title` (VARCHAR), `episodes` (INTEGER), `rating` (DECIMAL), and `genres` (VARCHAR).
5. **Insertion**: Insert the extracted data into the table. Handle missing ratings by converting them to `None` (NULL). Ensure `mydb.commit()` is called after the insertion loop to persist changes.
6. **Querying**: To query titles by a specific genre (e.g., 'Thriller'), use SQL queries with `LIKE '%GenreName%'` or `FIND_IN_SET`.
7. **Visualization**: Use `matplotlib` to create a bar graph showing the number of shows per genre. Use `plt.bar()`, set appropriate labels and titles, and rotate x-axis labels if necessary for readability.

# Anti-Patterns
- Do not forget to commit database transactions.
- Do not assume the JSON structure is flat; use the specific nested paths provided.
- Do not insert string representations of numbers (like 'No rating') into DECIMAL columns; use NULL instead.

## Triggers

- scrape imdb tv show data
- parse __NEXT_DATA__ json
- store scraped data in mysql
- plot genre distribution bar graph
