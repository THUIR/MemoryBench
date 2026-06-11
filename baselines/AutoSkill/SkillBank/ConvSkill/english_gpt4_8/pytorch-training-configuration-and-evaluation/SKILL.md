---
id: "c045a98f-05c3-4889-a95e-8c1452fb4c20"
name: "PyTorch Training Configuration and Evaluation"
description: "Configure PyTorch training scripts with specific evaluation metrics (Precision, Recall, F1), tunable hyperparameters (batch size, warmup, optimizer type, weight decay, attention dropout), and a custom GELU activation function."
version: "0.1.0"
tags:
  - "pytorch"
  - "training"
  - "evaluation"
  - "hyperparameters"
  - "gelu"
triggers:
  - "modify evaluation function"
  - "add hyperparameters"
  - "compute F1 score"
  - "add gelu_new"
  - "tune batch size"
---

# PyTorch Training Configuration and Evaluation

Configure PyTorch training scripts with specific evaluation metrics (Precision, Recall, F1), tunable hyperparameters (batch size, warmup, optimizer type, weight decay, attention dropout), and a custom GELU activation function.

## Prompt

# Role & Objective
Configure PyTorch training scripts to include specific evaluation metrics, tunable hyperparameters, and a custom GELU activation function.

# Operational Rules & Constraints
1. **Evaluation Metrics**: Modify the evaluation function to compute Precision, Recall, and F1 score using `sklearn.metrics` with `average='macro'`.
2. **Hyperparameters**: Define and utilize the following variables for tuning:
   - `batch_size`
   - `warmup_steps`
   - `optimizer_type` (e.g., "AdamW", "SGD")
   - `weight_decay`
   - `attention_dropout_rate`
3. **Activation Function**: Implement the `gelu_new` activation function using the formula: `0.5 * x * (1 + torch.tanh(torch.sqrt(2 / torch.pi) * (x + 0.044715 * torch.pow(x, 3))))`.
4. **Model Configuration**: Apply `attention_dropout_rate` to the `nn.TransformerEncoderLayer` and use `optimizer_type` to configure the optimizer (AdamW or SGD).

# Anti-Patterns
- Do not use the default accuracy metric alone; always include Precision, Recall, and F1.
- Do not hardcode hyperparameters; use the specified variables.

## Triggers

- modify evaluation function
- add hyperparameters
- compute F1 score
- add gelu_new
- tune batch size
