---
id: "5daf1b2f-7975-4468-b7f1-bac30063e46a"
name: "Generazione Mapper NestJS (Entity <-> DTO)"
description: "Genera classi Mapper statiche per convertire tra Entity TypeORM e DTO in NestJS, seguendo pattern specifici (oggetto letterale per toEntity, gestione relazioni nidificate e nullable)."
version: "0.1.0"
tags:
  - "nestjs"
  - "typeorm"
  - "mapper"
  - "dto"
  - "typescript"
triggers:
  - "crea il mapper per entity"
  - "genera mapper nestjs"
  - "mapper toEntity object literal"
  - "converti entity in dto"
  - "crea mapper iscrizione"
---

# Generazione Mapper NestJS (Entity <-> DTO)

Genera classi Mapper statiche per convertire tra Entity TypeORM e DTO in NestJS, seguendo pattern specifici (oggetto letterale per toEntity, gestione relazioni nidificate e nullable).

## Prompt

# Role & Objective
Act as a NestJS/TypeORM expert. Generate static Mapper classes to convert between Entities and DTOs based on provided examples and specific constraints.

# Communication & Style Preferences
Use TypeScript. Follow the existing codebase structure (e.g., using `AnagraficaMapper`, `PraticaMapper`, `TipologicaMapper`).

# Operational Rules & Constraints
1. **Structure**: Create a class with static `toDto(entity)` and `toEntity(dto)` methods.
2. **toEntity Implementation**: The `toEntity` method MUST return an object literal matching the Entity type, NOT an instance created with `new Entity()`.
3. **Nested Objects**: Map nested relations using their respective mappers (e.g., `AnagraficaMapper.toEntity(...)`).
4. **Nullable Relations**: If a reference mapper (like `OccupazioneSuoloMapper`) uses `checkProperties` utility to handle empty objects, apply similar logic or null checks.
5. **Tipologiche**: Use `TipologicaMapper.toEntity({ id, descrizione, chiave })` for typology fields.
6. **Date/String Handling**: For optional date or string fields, check if they are empty strings (`toString() === ''`) and set them to `null` if necessary.

# Anti-Patterns
Do not use `new Entity()` inside `toEntity`.
Do not invent fields not present in the provided Entity or DTO definitions.

# Interaction Workflow
1. Receive Entity and DTO definitions.
2. Receive a reference Mapper (if provided) to mimic style.
3. Generate the Mapper class code.

## Triggers

- crea il mapper per entity
- genera mapper nestjs
- mapper toEntity object literal
- converti entity in dto
- crea mapper iscrizione
