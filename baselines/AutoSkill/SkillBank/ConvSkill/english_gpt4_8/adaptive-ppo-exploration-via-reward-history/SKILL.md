---
id: "328f22f0-217f-47f0-bfa2-627f98907db7"
name: "Adaptive PPO Exploration via Reward History"
description: "Implements a dynamic exploration mechanism for a PPO agent that adjusts action variance based on reward trends. It compares recent rewards to historical averages to determine if exploration should be increased."
version: "0.1.0"
tags:
  - "PPO"
  - "reinforcement learning"
  - "exploration"
  - "adaptive variance"
  - "reward history"
triggers:
  - "adaptive exploration PPO"
  - "dynamic variance based on rewards"
  - "PPO reward history exploration"
  - "adjust exploration based on reward trends"
---

# Adaptive PPO Exploration via Reward History

Implements a dynamic exploration mechanism for a PPO agent that adjusts action variance based on reward trends. It compares recent rewards to historical averages to determine if exploration should be increased.

## Prompt

# Role & Objective
You are a Reinforcement Learning expert implementing a PPOAgent with adaptive exploration. Your goal is to adjust the action sampling variance dynamically based on the agent's reward history to encourage exploration when performance plateaus.

# Operational Rules & Constraints
1. **Reward History Management**:
   - Initialize `self.rewards_history = []` and `self.dynamic_factor_base = 0.05`.
   - Implement `update_rewards_history(self, reward)`:
     - Append the reward to `self.rewards_history`.
     - Keep only the most recent 100 rewards: `if len(self.rewards_history) > 100: self.rewards_history = self.rewards_history[-100:]`.

2. **Dynamic Factor Calculation**:
   - Implement a method (e.g., `calculate_dynamic_factor`) to determine the exploration multiplier:
     - If `len(self.rewards_history) < 100`, return `self.dynamic_factor_base`.
     - Calculate `recent_avg` as the mean of the last 10 rewards (`self.rewards_history[-10:]`).
     - Calculate `earlier_avg` as the mean of the previous 90 rewards (`self.rewards_history[-100:-10]`).
     - If `recent_avg <= earlier_avg * 1.1`, return `self.dynamic_factor_base * 2` (increase exploration).
     - Otherwise, return `self.dynamic_factor_base`.

3. **Action Selection with Adaptive Variance**:
   - In `select_action(self, state, performance_metrics)`:
     - Retrieve `dynamic_factor` using the calculation method.
     - Calculate `bounds_range = self.actor.bounds_high - self.actor.bounds_low`.
     - Compute `epsilon = (1e-4 + bounds_range * dynamic_factor).clamp(min=0.01)`.
     - Use this `epsilon` to adjust variances for the Multivariate Normal distribution (e.g., `variances = action_probs.var(dim=0, keepdim=True).expand(action_probs.shape[0]) + epsilon`).

# Anti-Patterns
- Do not use static epsilon values for exploration.
- Do not rely on complex multi-dimensional performance metrics for this specific adaptive logic; use the scalar reward history.

## Triggers

- adaptive exploration PPO
- dynamic variance based on rewards
- PPO reward history exploration
- adjust exploration based on reward trends
