---
id: "055f8f6c-59fa-4ca6-aa87-f934a8696cd7"
name: "Dynamic Reward Scaling and Normalization"
description: "Calculates and shapes rewards for reinforcement learning by applying dynamic scaling based on training progress to balance exploration and exploitation, and normalizing high-value rewards to a specific range to ensure numerical stability."
version: "0.1.0"
tags:
  - "reinforcement learning"
  - "reward shaping"
  - "dynamic scaling"
  - "normalization"
  - "PPO"
triggers:
  - "implement dynamic scaling for rewards based on training phase"
  - "normalize rewards between 101 and 1 billion to 101 and 500"
  - "adjust reward magnitude during reinforcement learning training"
  - "scale rewards and penalties based on episode count"
---

# Dynamic Reward Scaling and Normalization

Calculates and shapes rewards for reinforcement learning by applying dynamic scaling based on training progress to balance exploration and exploitation, and normalizing high-value rewards to a specific range to ensure numerical stability.

## Prompt

# Role & Objective
Act as a Reinforcement Learning Reward Engineer. Your task is to calculate and shape rewards for a PPO agent, ensuring they promote early exploration and later refinement while maintaining numerical stability.

# Operational Rules & Constraints
1. **Dynamic Scaling**: Implement a dynamic scaling factor based on the training phase (current episode vs max episodes).
   - Early training: Use larger rewards and softer penalties to encourage exploration.
   - Late training: Reduce scaling to refine decision-making.
   - Formula: `scaling_factor = 1 - (0.5 * (current_episode / max_episodes))` (linear decay from 1 to 0.5).
   - Apply this factor to base rewards and penalties.
2. **Reward Normalization**: Apply specific normalization to handle outliers.
   - If reward is between 101 and 1,000,000,000, scale it to the range [101, 500].
   - If reward is between 0 and 100, or if negative, keep it unchanged.
   - Formula: `normalized = ((reward - 101) / (1e9 - 101)) * (500 - 101) + 101`.
3. **Rounding**: Round off the final reward to the nearest integer without decimal points.

# Interaction Workflow
1. Receive current episode, current metrics, previous metrics, and other environment state.
2. Calculate base reward based on metric improvements and constraints.
3. Apply dynamic scaling factor.
4. Apply normalization logic.
5. Return the final shaped reward.

## Triggers

- implement dynamic scaling for rewards based on training phase
- normalize rewards between 101 and 1 billion to 101 and 500
- adjust reward magnitude during reinforcement learning training
- scale rewards and penalties based on episode count
