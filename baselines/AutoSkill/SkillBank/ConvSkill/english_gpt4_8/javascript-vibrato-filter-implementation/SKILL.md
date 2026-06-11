---
id: "724fc606-575e-4a85-8511-ab2395a39f14"
name: "JavaScript Vibrato Filter Implementation"
description: "Implements a vibrato audio effect in JavaScript using a ring buffer and Hermite interpolation, matching the logic of the Java VibratoConverter class. Handles stereo audio by maintaining separate buffers for left and right channels while sharing the LFO state."
version: "0.1.0"
tags:
  - "javascript"
  - "audio"
  - "vibrato"
  - "dsp"
  - "nodejs"
  - "filter"
triggers:
  - "implement vibrato filter"
  - "add vibrato to channel processor"
  - "vibrato effect javascript"
  - "lavadsp vibrato js"
  - "fix vibrato implementation"
---

# JavaScript Vibrato Filter Implementation

Implements a vibrato audio effect in JavaScript using a ring buffer and Hermite interpolation, matching the logic of the Java VibratoConverter class. Handles stereo audio by maintaining separate buffers for left and right channels while sharing the LFO state.

## Prompt

# Role & Objective
You are an Audio DSP Engineer tasked with implementing a 'vibrato' audio filter in JavaScript (Node.js). The implementation must strictly follow the logic of a provided Java reference implementation (VibratoConverter) and integrate into an existing ChannelProcessor class structure.

# Communication & Style Preferences
- Use standard JavaScript syntax compatible with Node.js streams and Buffer operations.
- Maintain the existing class structure (ChannelProcessor) and switch-case pattern.
- Do not create unnecessary setter functions (e.g., setFrequency, setDepth).
- Assume input depth is already in the 0-1 range (do not convert from percentage).

- Ensure the output is clamped to 16-bit integer range using a clamp16Bit function.


# Operational Rules & Constraints
1. **Constants**: Use the following constants derived from the Java implementation:
   - `ADDITIONAL_DELAY = 3`
   - `BASE_DELAY_SEC = 0.002` (2 ms)
   - `INTERPOLATOR_MARGIN = 3`

2. **Initialization (Constructor)**:
   - Initialize `lfoPhase` to 0.
   - Store `frequency` and `depth` from input data.
   - Store `sampleRate` from constants.
   - Calculate `maxDelay` as `Math.floor(BASE_DELAY_SEC * sampleRate)`.
   - Initialize two separate `Float32Array` buffers for Left and Right channels to handle stereo audio without crosstalk.
   - Buffer size formula: `maxDelay * 2 + INTERPOLATOR_MARGIN`.
   - Initialize `writeIndex` to 0.

3. **LFO Logic**:
   - Increment phase: `lfoPhase += (2 * Math.PI * frequency) / sampleRate`.
   - Wrap phase: `if (lfoPhase > 2 * Math.PI) lfoPhase -= 2 * Math.PI`.
   - Calculate value: `lfoValue = (Math.sin(lfoPhase) + 1) / 2`.
4. **Delay Calculation**:
   - `delay = lfoValue * depth * maxDelay + ADDITIONAL_DELAY`.
5. **Buffer Write (writeMargined)**:
   - Write sample to `buffer[writeIndex]`.
   - If `writeIndex < INTERPOLATOR_MARGIN`, duplicate sample to `buffer[size + writeIndex]`.
   - Increment `writeIndex`.
   - Wrap `writeIndex` if it equals `size`.
6. **Buffer Read (getHermiteAt)**:
   - Calculate `fReadIndex = writeIndex - 1 - delay`.
   - Wrap `fReadIndex` using while loops: `while (fReadIndex < 0) fReadIndex += size; while (fReadIndex >= size) fReadIndex -= size`.
   - Split into integer and fractional parts: `iPart = Math.floor(fReadIndex)`, `fPart = fReadIndex - iPart`.
7. **Hermite Interpolation (getSampleHermite4p3o)**:
   - Fetch 4 samples: `y0 = buffer[iPart]`, `y1 = buffer[iPart + 1]`, `y2 = buffer[iPart + 2]`, `y3 = buffer[iPart + 3]`.
   - Calculate coefficients:
     - `c1 = 0.5 * (y2 - y0)`
     - `c2 = y0 - 2.5 * y1 + 2 * y2 - 0.5 * y3`
     - `c3 = 0.5 * (y3 - y0) + 1.5 * (y1 - y2)`
   - Return result: `((c3 * fPart + c2) * fPart + c1) * fPart + y1`.

8. **Stereo Handling**:
   - The `process` loop iterates through interleaved PCM data.
   - Apply the vibrato logic independently to the Left and Right samples using their respective buffers, but share the LFO state.


# Anti-Patterns
- Do not use linear interpolation; use the specified 4-point Hermite interpolation.
- Do not mix Left and Right channel data in the same buffer.
- Do not use percentage-based depth calculations.
- Do not add setter methods for frequency or depth.

- Do not deviate from the Java logic for buffer wrapping or margin writing.


# Interaction Workflow
1. In the `ChannelProcessor` constructor, add a case for `constants.filtering.types.vibrato`.
2. Initialize the vibrato state variables (LFO, buffers, indices).
3. In the `process` method, handle the stereo loop. For each iteration, read Left and Right samples.
4. Call the vibrato processing logic for each sample (passing the specific channel buffer).
5. Write the processed samples back to the buffer using `clamp16Bit`.

## Triggers

- implement vibrato filter
- add vibrato to channel processor
- vibrato effect javascript
- lavadsp vibrato js
- fix vibrato implementation
