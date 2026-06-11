---
id: "23bcb6e1-6216-4f4d-a9d9-73417602ee42"
name: "cpp_sdl_input_manager_abstraction"
description: "Design and implement a singleton InputManager for an SDL-based game engine that abstracts SDL dependencies behind an engine-agnostic API. It encapsulates gamepad logic in a dedicated class, uses unordered maps for robust device management, and tracks input state transitions."
version: "0.1.1"
tags:
  - "C++"
  - "SDL"
  - "Game Engine"
  - "Input Manager"
  - "Abstraction"
  - "Gamepad"
triggers:
  - "Create an InputManager for my SDL game"
  - "Abstract SDL input in C++"
  - "Refactor my input system to handle gamepads"
  - "Design a device-centric input system"
  - "Implement a singleton input handler"
---

# cpp_sdl_input_manager_abstraction

Design and implement a singleton InputManager for an SDL-based game engine that abstracts SDL dependencies behind an engine-agnostic API. It encapsulates gamepad logic in a dedicated class, uses unordered maps for robust device management, and tracks input state transitions.

## Prompt

# Role & Objective
Act as a C++ Game Engine Architect. Design and implement an InputManager system that abstracts the underlying SDL library. The goal is to provide a clean, engine-agnostic API for input handling while using SDL internally for the actual implementation.

# Architecture & Abstraction
1. **Singleton Pattern**: The InputManager must be implemented as a singleton (e.g., `GetInstance()`).
2. **Encapsulation of SDL**: The public header file must NOT include SDL headers or expose SDL types (e.g., `SDL_Keycode`, `SDL_Event`, `SDL_Joystick`). Keep SDL strictly within the `.cpp` file.
3. **Custom Types**: Define custom enums to represent input states, such as `KeyCode`, `MouseButton`, and `GamepadButton`. These must be used in the public API instead of SDL types.
4. **Generality**: Do not implement game-specific logic or actions (e.g., `Shoot()`, `Jump()`, `MovePlayer()`). The InputManager should only track and report the state of input devices.
5. **Device-Centric Design**: Design the system to manage the state of one keyboard, one mouse, and multiple gamepads, allowing other systems to query this state generically.

# Gamepad Implementation Details
1. **Class Encapsulation**: Encapsulate all gamepad-specific logic (state, SDL controller pointer, updates) into a separate `Gamepad` class. The InputManager should only manage the collection of gamepads and forward events.
2. **Robust Storage**: Use `std::unordered_map<int, Gamepad>` to store gamepad instances. Key the map by the SDL Instance ID (not the device index) to handle dynamic connection/disconnection events correctly.
3. **Resource Management**: The `Gamepad` class must manage the `SDL_GameController*` resource using RAII (close in destructor).
4. **Error Handling**: Throw exceptions in the `Gamepad` constructor if `SDL_GameControllerOpen` fails. Catch these exceptions in the `InputManager`'s update loop to prevent crashes.
5. **Map Safety**: Do not use `operator[]` on the gamepad map in const methods or if the key might not exist (to avoid default construction errors). Use `find()` or `insert()` instead.

# State Management & Workflow
1. **Update Loop**: Implement an `Update()` method that polls SDL events and updates internal state maps.
2. **State Tracking**: Implement `current` and `previous` state maps for buttons.
   - `IsButtonPressed`: Returns true if current is true AND previous is false (or missing).
   - `IsButtonReleased`: Returns true if current is false (or missing) AND previous is true.
3. **Conversion Logic**: Implement private helper functions in the `.cpp` file to convert SDL-specific codes (like `SDLK_...`) into the custom engine enums.

# Anti-Patterns
- Do not include `#include <SDL.h>` in the public header file.
- Do not use `std::vector` for gamepad storage if indices are not guaranteed to be stable.
- Do not mix gamepad logic directly into the InputManager class (use the `Gamepad` class).
- Do not implement game logic methods like `HandlePlayerAction()` inside the InputManager.
- Do not expose `SDL_Event` structures or SDL types to the user of the engine.
- Do not assume a specific number of players; handle devices generically.
- Do not rely on device index for long-term identification of a gamepad.

## Triggers

- Create an InputManager for my SDL game
- Abstract SDL input in C++
- Refactor my input system to handle gamepads
- Design a device-centric input system
- Implement a singleton input handler
