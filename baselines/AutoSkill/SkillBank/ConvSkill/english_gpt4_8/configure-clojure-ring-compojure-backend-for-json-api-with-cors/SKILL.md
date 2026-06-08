---
id: "8c5d7d61-5b31-4033-b8c9-b53ee03bb6b5"
name: "Configure Clojure Ring/Compojure Backend for JSON API with CORS"
description: "Configure a Clojure web server using Ring and Compojure to handle JSON API requests and enable Cross-Origin Resource Sharing (CORS) for frontend communication across different ports or domains."
version: "0.1.0"
tags:
  - "clojure"
  - "ring"
  - "compojure"
  - "cors"
  - "web-development"
  - "api"
triggers:
  - "setup cors in clojure"
  - "configure clojure api"
  - "fix cors preflight error"
  - "clojure ring compojure json"
---

# Configure Clojure Ring/Compojure Backend for JSON API with CORS

Configure a Clojure web server using Ring and Compojure to handle JSON API requests and enable Cross-Origin Resource Sharing (CORS) for frontend communication across different ports or domains.

## Prompt

# Role & Objective
Act as a Clojure backend developer. Configure a Ring/Compojure application to serve JSON API endpoints and handle Cross-Origin Resource Sharing (CORS) for a frontend running on a different origin (port/domain).

# Operational Rules & Constraints
- Use `ring.middleware.cors/wrap-cors` to enable CORS.
- Configure `wrap-cors` with specific allowed origins (regex), methods (including `:options`), and headers (e.g., `Content-Type`, `Authorization`).
- Add a wildcard `(OPTIONS "*")` route in `defroutes` to handle preflight requests, returning an empty map `{}` or a response.
- Ensure the middleware stack order allows `wrap-cors` to intercept requests correctly.
- In API handlers, extract parameters using `(:params request)`.
- Return JSON responses using `(response {:status "success" ...})` and set the `Content-Type` header to `"application/json"`.
# Anti-Patterns
- Do not use wildcard origins (`#".*"`) for production configurations unless explicitly requested for testing.
- Do not omit the `OPTIONS` route if preflight errors occur.

## Triggers

- setup cors in clojure
- configure clojure api
- fix cors preflight error
- clojure ring compojure json
