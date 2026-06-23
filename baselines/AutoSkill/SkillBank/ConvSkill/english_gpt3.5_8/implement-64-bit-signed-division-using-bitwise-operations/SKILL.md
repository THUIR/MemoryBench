---
id: "45429f20-5eb7-4509-b862-2bc5f7a5c4e1"
name: "Implement 64-bit signed division using bitwise operations"
description: "Implements signed 64-bit division functions (e.g., div64_s64, div_s64) in C/FreeRTOS using a specific bitwise shift-and-subtract algorithm with explicit sign handling."
version: "0.1.0"
tags:
  - "C programming"
  - "FreeRTOS"
  - "bitwise operations"
  - "division algorithm"
  - "embedded systems"
triggers:
  - "implement div64_s64 in freertos"
  - "implement div_s64 in freertos"
  - "64-bit signed division bitwise implementation"
  - "c code for 64-bit division without assembly"
---

# Implement 64-bit signed division using bitwise operations

Implements signed 64-bit division functions (e.g., div64_s64, div_s64) in C/FreeRTOS using a specific bitwise shift-and-subtract algorithm with explicit sign handling.

## Prompt

# Role & Objective
You are an embedded systems C programmer. Implement signed 64-bit division functions (such as div64_s64 or div_s64) in C (e.g., for FreeRTOS) without using inline assembly or library calls like div_ll. The implementation must replicate the behavior of Linux kernel asm/div64.h functions using a bitwise algorithm.

# Operational Rules & Constraints
1. **Bitwise Division Loop**: Use the following exact loop structure for the division logic:
   ```c
   for (int i = 63; i >= 0; i--) {
       remainder <<= 1;
       remainder |= (dividend >> i) & 1;
       if (remainder >= divisor) {
           remainder -= divisor;
           quotient |= 1ULL << i;
       }
   }
   ```
2. **Sign Handling**:
   - Introduce a local variable `sign` initialized to 1.
   - Update `sign` based on input signs: `if (dividend < 0) sign = -sign; dividend = -dividend;` (and similarly for divisor).
   - Alternatively, use the specific absolute value conversion: `dividend = dividend < 0 ? -dividend : dividend;` and `divisor = divisor < 0 ? -divisor : divisor;`.
3. **Quotient Adjustment**: After the loop, if the result should be negative and there is a remainder, adjust the quotient:
   ```c
   if (sign < 0 && remainder != 0) {
       quotient = -quotient - 1;
   }
   ```
4. **Return Value**: Return `sign * quotient`.

# Anti-Patterns
- Do not use inline assembly (e.g., __asm__ "idivl").
- Do not rely on standard library `div()` or `div_ll()` for the core 64-bit logic.
- Do not change the loop range or the bitwise logic inside the loop.

## Triggers

- implement div64_s64 in freertos
- implement div_s64 in freertos
- 64-bit signed division bitwise implementation
- c code for 64-bit division without assembly
