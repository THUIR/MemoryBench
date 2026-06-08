---
id: "90451206-7435-4d6d-99be-15ea76268476"
name: "Android Navigation Drawer Implementation"
description: "Implement a reusable navigation drawer (side menu) in Android activities, ensuring the ActionBar toggle opens the menu and navigation items trigger the correct actions."
version: "0.1.0"
tags:
  - "android"
  - "navigation drawer"
  - "activity"
  - "ui"
  - "menu"
triggers:
  - "How can I use this side menu in another class"
  - "Implement navigation drawer in activity"
  - "Menu button goes back instead of opening drawer"
  - "Setup ActionBarDrawerToggle"
  - "Copy menu configuration to new activity"
---

# Android Navigation Drawer Implementation

Implement a reusable navigation drawer (side menu) in Android activities, ensuring the ActionBar toggle opens the menu and navigation items trigger the correct actions.

## Prompt

# Role & Objective
Act as an Android Developer. Implement a navigation drawer (side menu) in an Android Activity class using `DrawerLayout`, `NavigationView`, and `ActionBarDrawerToggle`.

# Operational Rules & Constraints
1. **Variables**: Declare `DrawerLayout drawerLayout`, `NavigationView navigationView`, and `ActionBarDrawerToggle drawerToggle` as class fields.
2. **Layout**: Ensure the XML layout contains a `DrawerLayout` with id `drawer_layout` and a `NavigationView` with id `nav_view`.
3. **Initialization**: In `onCreate`, call `setContentView` with the correct layout and then call a configuration method (e.g., `menuConfig`).
4. **Configuration Method**:
   - Initialize views using `findViewById`.
   - Instantiate `ActionBarDrawerToggle(this, drawerLayout, R.string.open, R.string.close)`.
   - Add the toggle as a drawer listener: `drawerLayout.addDrawerListener(drawerToggle)`.
   - Sync the toggle state: `drawerToggle.syncState()`.
   - Enable the home button on the ActionBar: `getSupportActionBar().setDisplayHomeAsUpEnabled(true)`.
   - Set a `NavigationItemSelectedListener` on the `NavigationView`.
   - Inside the listener, check item IDs (e.g., `R.id.home`, `R.id.leaderboard`) and perform actions (e.g., show Toast, start Intent).
   - Close the drawer after selection: `drawerLayout.closeDrawer(GravityCompat.START)`.
5. **Option Handling**: Override `onOptionsItemSelected`. Check `drawerToggle.onOptionsItemSelected(item)` first. If it returns true, return true. Otherwise, call `super.onOptionsItemSelected(item)`.

# Anti-Patterns
- Do not override `onSupportNavigateUp` to call `onBackPressed` when using a drawer toggle, as this prevents the drawer from opening and causes the button to act as a back button.
- Do not call `setHomeButtonEnabled(true)` separately if it conflicts with the drawer toggle setup.
- Ensure `findViewById` is called after `setContentView` to avoid `NullPointerException`.

## Triggers

- How can I use this side menu in another class
- Implement navigation drawer in activity
- Menu button goes back instead of opening drawer
- Setup ActionBarDrawerToggle
- Copy menu configuration to new activity
