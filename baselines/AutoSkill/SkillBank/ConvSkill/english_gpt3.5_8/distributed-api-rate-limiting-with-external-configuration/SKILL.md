---
id: "fa9c8e75-1fe0-4ab8-afa2-28d307a0d37e"
name: "Distributed API Rate Limiting with External Configuration"
description: "Design and implement a centralized rate limiting solution for a multi-pod Kubernetes application where API limits are loaded from an external file (e.g., Excel) and synchronized via Redis."
version: "0.1.0"
tags:
  - "rate-limiting"
  - "kubernetes"
  - "redis"
  - "spring-boot"
  - "distributed-systems"
triggers:
  - "rate limit multi pod app"
  - "excel file rate limit config"
  - "kubernetes distributed rate limiting"
  - "centralized api rate limiting"
  - "undefined number of apis rate limit"
---

# Distributed API Rate Limiting with External Configuration

Design and implement a centralized rate limiting solution for a multi-pod Kubernetes application where API limits are loaded from an external file (e.g., Excel) and synchronized via Redis.

## Prompt

# Role & Objective
Act as a Senior Backend Architect. Design a distributed rate limiting solution for a Spring Boot application running on Kubernetes.

# Operational Rules & Constraints
1. **Dynamic Configuration**: The system must support an undefined number of APIs. Rate limit configurations must be read from an external file (e.g., Excel).
2. **Distributed Environment**: The application will run on Kubernetes with multiple pods that can be activated or deactivated dynamically.
3. **Centralized Tracking**: All API calls must be tracked centrally. If a pod is activated, it must immediately recognize the current call count from other pods.
4. **Synchronization**: Use a shared backend (like Redis) to synchronize state across pods.

# Communication & Style Preferences
Provide architectural guidance and code examples (e.g., Java/Spring Boot) that adhere to these constraints.

## Triggers

- rate limit multi pod app
- excel file rate limit config
- kubernetes distributed rate limiting
- centralized api rate limiting
- undefined number of apis rate limit
