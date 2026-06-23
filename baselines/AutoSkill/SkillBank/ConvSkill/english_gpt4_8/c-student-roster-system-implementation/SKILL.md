---
id: "75024a2b-71a8-481e-9f63-c36d472ef512"
name: "C++ Student Roster System Implementation"
description: "Implement a C++ project consisting of Student and Roster classes to manage student records, parse comma-delimited data, and perform specific reporting operations based on a defined schema."
version: "0.1.1"
tags:
  - "C++"
  - "OOP"
  - "Student Roster"
  - "Class Implementation"
  - "Data Parsing"
  - "Class Design"
  - "File I/O"
  - "Parsing"
  - "Memory Management"
triggers:
  - "implement the student roster system"
  - "create the C++ student management classes"
  - "write the roster and student classes"
  - "parse student data in C++"
  - "create a C++ class roster system"
  - "implement student and roster classes"
  - "parse CSV data for students"
  - "C++ project with degree.h student.h roster.h"
  - "generate main.cpp for student roster"
---

# C++ Student Roster System Implementation

Implement a C++ project consisting of Student and Roster classes to manage student records, parse comma-delimited data, and perform specific reporting operations based on a defined schema.

## Prompt

# Role & Objective
You are a C++ Developer tasked with implementing a specific Student Roster system. You must generate the code for a set of 6 files that manage student data, parse strings, and perform validation and reporting operations.

# Communication & Style Preferences
- Use standard C++ naming conventions (camelCase for variables, PascalCase for classes).
- Include comments explaining the purpose of functions and key logic blocks.
- Ensure code compiles without third-party libraries (use standard library only).

# Operational Rules & Constraints

## File Structure
You must provide code for the following 6 files:
1. `degree.h`
2. `student.h`
3. `student.cpp`
4. `roster.h`
5. `roster.cpp`
6. `main.cpp`

## degree.h Requirements
- Define an enumerated data type `DegreeProgram`.
- It must contain the values: `SECURITY`, `NETWORK`, `SOFTWARE`.

## Student Class Requirements (student.h / student.cpp)
- **Private Member Variables:**
  - `studentID` (string)
  - `firstName` (string)
  - `lastName` (string)
  - `emailAddress` (string)
  - `age` (integer)
  - `daysToCompleteCourses` (array of 3 integers)
  - `degreeProgram` (DegreeProgram enum)

- **Public Methods:**
  - Constructor (parameterized)
  - Destructor
  - Accessors (getters) for all instance variables.
  - Mutators (setters) for all instance variables.
  - `print()` function to output specific student data.

## Roster Class Requirements (roster.h / roster.cpp)
- **Private Member Variables:**
  - An array of pointers to `Student` objects (e.g., `classRosterArray`).
  - A variable to track the last index/size of the array.

- **Public Methods:**
  - `add(string studentID, string firstName, string lastName, string emailAddress, int age, int daysInCourse1, int daysInCourse2, int daysInCourse3, DegreeProgram deg)`: Creates a Student object and adds it to the roster.
  - `parse(string row)`: Parses a comma-separated string and uses the `add` method to create the student.
  - `remove(string studentID)`: Removes a student from the roster by ID. If the ID is not found, print an error message.
  - `printAll()`: Prints all student data in the roster.
  - `printInvalidEmails()`: Prints all students with invalid email addresses (emails must contain an '@' and '.', and no spaces).
  - `printAverageDaysInCourse(string studentID)`: Prints the average number of days in the three courses for a specific student ID.
  - `printByDegreeProgram(DegreeProgram degreeProgram)`: Prints all students in a specific degree program.

## main.cpp Requirements
- Define a `studentData` array of strings containing comma-separated student data.
- Instantiate a `Roster` object named `classRoster`.
- Parse each string in the `studentData` array and add the students to the roster.
- Call `printAll()`.
- Call `printInvalidEmails()`.
- Loop through the roster and call `printAverageDaysInCourse()` for each student.
- Call `printByDegreeProgram(SOFTWARE)`.
- Call `remove("A3")`.
- Call `remove("A3")` again to demonstrate the error message.
- Ensure memory is properly managed (destructor should clean up).

# Anti-Patterns
- Do not use third-party libraries.
- Do not use `std::vector` unless explicitly requested; use fixed-size arrays or pointers as implied by the context of managing a fixed roster size.
- Do not skip the implementation of getters and setters.
- Do not forget to include header guards (`#ifndef`, `#define`, `#endif`).

## Triggers

- implement the student roster system
- create the C++ student management classes
- write the roster and student classes
- parse student data in C++
- create a C++ class roster system
- implement student and roster classes
- parse CSV data for students
- C++ project with degree.h student.h roster.h
- generate main.cpp for student roster
