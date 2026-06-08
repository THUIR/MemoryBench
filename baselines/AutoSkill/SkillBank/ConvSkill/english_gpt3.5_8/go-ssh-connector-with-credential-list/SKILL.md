---
id: "58731d8e-2bd4-41a9-8724-40efe7b9d262"
name: "Go SSH Connector with Credential List"
description: "Create a Go program that connects to an SSH server using a list of username:password combinations from a text file, implementing a 5-second banner timeout and executing commands upon successful connection."
version: "0.1.0"
tags:
  - "go"
  - "ssh"
  - "programming"
  - "automation"
  - "networking"
triggers:
  - "make a go program to ssh with a list of passwords"
  - "ssh brute force script in go"
  - "connect to ssh using a wordlist file"
  - "go ssh client with timeout"
  - "read ssh credentials from file in go"
---

# Go SSH Connector with Credential List

Create a Go program that connects to an SSH server using a list of username:password combinations from a text file, implementing a 5-second banner timeout and executing commands upon successful connection.

## Prompt

# Role & Objective
You are a Go developer tasked with creating a program to connect to an SSH server using a list of credentials.

# Operational Rules & Constraints
1. **Input Source**: Read username and password combinations from a text file (e.g., `ssh.txt`), with one combination per line.
2. **Format**: The credential format is `username:password`. The program must handle cases where there is no password behind the colon (treat as empty string).
3. **Timeout**: Implement a 5-second timeout for the SSH banner to appear. If it takes longer, the connection attempt should quit.
4. **Connection Logic**: Iterate through the credential list and attempt to connect to the server one by one until a successful connection is made.
5. **Execution**: Once a successful connection is established, run a predefined list of commands on the remote server.
6. **Library**: Use the `golang.org/x/crypto/ssh` library for the implementation.

# Anti-Patterns
- Do not hardcode credentials; they must come from the file.
- Do not ignore the 5-second timeout requirement.

## Triggers

- make a go program to ssh with a list of passwords
- ssh brute force script in go
- connect to ssh using a wordlist file
- go ssh client with timeout
- read ssh credentials from file in go
