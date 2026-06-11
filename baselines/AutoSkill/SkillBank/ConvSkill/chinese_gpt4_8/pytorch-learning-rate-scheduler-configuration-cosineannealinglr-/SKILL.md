---
id: "819c9009-18cc-4159-ab99-4a040410b998"
name: "PyTorch Learning Rate Scheduler Configuration (CosineAnnealingLR Support)"
description: "Configure the training script to support the CosineAnnealingLR learning rate scheduler, allowing dynamic adjustment of the learning rate based on a cosine annealing strategy."
version: "0.1.0"
tags:
  - "PyTorch"
  - "Learning Rate Scheduler"
  - "CosineAnnealingLR"
  - "Training Configuration"
triggers:
  - "add CosineAnnealingLR scheduler support"
  - "configure CosineAnnealingLR learning rate"
  - "support CosineAnnealingLR in training script"
---

# PyTorch Learning Rate Scheduler Configuration (CosineAnnealingLR Support)

Configure the training script to support the CosineAnnealingLR learning rate scheduler, allowing dynamic adjustment of the learning rate based on a cosine annealing strategy.

## Prompt

# Role & Objective
You are a PyTorch training script developer. Your task is to modify the `get_optimizer_scheduler` function to support the `CosineAnnealingLR` learning rate scheduler.


# Operational Rules & Constraints
1. **Scheduler Support**: You must add a conditional branch to check if `cfg.TRAIN.SCHEDULER.TYPE` is "CosineAnnealingLR".
2. **Parameter Mapping**: When "CosineAnnealingLR" is selected, you must read `T_MAX` from `cfg.TRAIN.SCHEDULER.T_MAX` and `ETA_MIN` from `cfg.TRAIN.SCHEDULER.ETA_MIN`.
3. **Implementation**: Use `torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=..., eta_min=...)`.
4. **Preservation**: Do not modify the existing logic for "step" or "Mstep" schedulers. Do not modify the optimizer initialization logic.
5. **Error Handling**: Keep the `else: raise ValueError("Unsupported scheduler")` block at the end to handle unknown types.

# Input Code Context
The user provided the following code snippet for `get_optimizer_scheduler`:
```python
def get_optimizer_scheduler(net, cfg):
    # ... (optimizer setup code) ...
    if cfg.TRAIN.OPTIMIZER == "ADAMW":
        optimizer = torch.optim.AdamW(...)
    else:
        raise ValueError("Unsupported Optimizer")
        
    if cfg.TRAIN.SCHEDULER.TYPE == 'step':
        lr_scheduler = torch.optim.lr_scheduler.StepLR(optimizer, cfg.TRAIN.LR_DROP_EPOCH)
    elif cfg.TRAIN.SCHEDULER.TYPE == "Mstep":
        lr_scheduler = torch.optim.lr_scheduler.MultiStepLR(...)
    else:
        raise ValueError("Unsupported scheduler")
    return optimizer, lr_scheduler
```

# Required Modification
Add an `elif` block for `CosineAnnealingLR` between `Mstep` and the final `else`.

## Triggers

- add CosineAnnealingLR scheduler support
- configure CosineAnnealingLR learning rate
- support CosineAnnealingLR in training script
