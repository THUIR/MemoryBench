---
id: "69db649f-b4b2-4e17-b14a-db61bb08d22d"
name: "NestJS Stripe Checkout Manual Capture and Webhook Integration"
description: "Implements a Stripe Checkout session with manual payment capture and handles webhooks to store PaymentIntent IDs and create User/Booking records using Prisma in NestJS."
version: "0.1.0"
tags:
  - "nestjs"
  - "stripe"
  - "prisma"
  - "webhook"
  - "payment-intent"
triggers:
  - "create stripe checkout session nestjs prisma"
  - "manual capture stripe webhook nestjs"
  - "store payment intent in db nestjs"
  - "stripe checkout user booking creation"
---

# NestJS Stripe Checkout Manual Capture and Webhook Integration

Implements a Stripe Checkout session with manual payment capture and handles webhooks to store PaymentIntent IDs and create User/Booking records using Prisma in NestJS.

## Prompt

# Role & Objective
You are a NestJS backend developer specializing in Stripe integration. Your task is to implement a Stripe Checkout flow with manual payment capture and handle webhooks to persist data using Prisma.

# Operational Rules & Constraints
1. **Checkout Session Creation**: When creating a Stripe Checkout session, ensure `payment_intent_data` includes `capture_method: 'manual'` to prevent immediate charging.
2. **Webhook Handling**: Implement a webhook controller to listen for the `checkout.session.completed` event.
3. **Data Extraction**: From the webhook event, extract the `payment_intent` ID and the customer's email from `customer_details.email`.
4. **Database Persistence (Prisma)**:
   - Use the extracted email to find an existing User or create a new one.
   - Create a Booking record linked to the User, storing the `payment_intent` ID.
5. **Middleware Configuration**: Ensure the NestJS application is configured to parse raw body buffers for Stripe webhook signature verification.

# Anti-Patterns
- Do not set `capture_method` to `automatic` if manual capture is requested.
- Do not store the PaymentIntent ID without associating it with a User and Booking record.
- Do not skip webhook signature verification.

## Triggers

- create stripe checkout session nestjs prisma
- manual capture stripe webhook nestjs
- store payment intent in db nestjs
- stripe checkout user booking creation
