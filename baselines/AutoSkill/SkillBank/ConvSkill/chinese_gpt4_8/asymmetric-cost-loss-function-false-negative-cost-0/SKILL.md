---
id: "5839394e-59fb-4edf-8d15-b11a4cb09436"
name: "Asymmetric Cost Loss Function (False Negative Cost = 0)"
description: "Defines a custom loss function in TensorFlow/Keras where predicting 1 as 0 (False Negative) has zero cost, while predicting 0 as 1 (False Positive) has a cost of 1."
version: "0.1.0"
tags:
  - "tensorflow"
  - "keras"
  - "loss function"
  - "asymmetric cost"
  - "imbalanced data"
  - "machine learning"
triggers:
  - "自定义一个评估标准，把1预测成0不算错"
  - "自定义loss函数"
  - "把1预测成0不算错"
---

# Asymmetric Cost Loss Function (False Negative Cost = 0)

Defines a custom loss function in TensorFlow/Keras where predicting 1 as 0 (False Negative) has zero cost, while predicting 0 as 1 (False Positive) has a cost of 1.

## Prompt

Define a custom loss function in TensorFlow/Keras. The loss function must implement the logic where the cost of False Negatives (predicting 1 as 0) is 0. The cost of False Positives (predicting 0 as 1) is 1. Ensure type casting to float32 to avoid type mismatch errors.

## Triggers

- 自定义一个评估标准，把1预测成0不算错
- 自定义loss函数
- 把1预测成0不算错
