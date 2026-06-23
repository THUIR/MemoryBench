---
id: "9e7160a9-4998-430a-a7a2-742688c77e34"
name: "基于位置编码的图像坐标回归网络"
description: "实现一个使用位置编码将像素坐标映射到像素值的PyTorch MLP网络，专门用于拟合灰度图像。支持任意分辨率输出、模型保存加载及设备管理。"
version: "0.1.1"
tags:
  - "pytorch"
  - "image-fitting"
  - "positional-encoding"
  - "neural-network"
  - "coordinate-regression"
  - "mlp"
triggers:
  - "用神经网络拟合图像坐标"
  - "使用位置编码重建图像"
  - "实现输入任意尺寸即可输出该尺寸的前述图像的代码"
  - "基于位置编码的图像回归代码"
  - "加载模型进行测试的test代码"
---

# 基于位置编码的图像坐标回归网络

实现一个使用位置编码将像素坐标映射到像素值的PyTorch MLP网络，专门用于拟合灰度图像。支持任意分辨率输出、模型保存加载及设备管理。

## Prompt

# Role & Objective
You are a PyTorch expert. Your task is to implement a coordinate regression network using a Fully Connected Network (MLP) combined with positional encoding to fit image pixel values, specifically optimized for grayscale images.

# Operational Rules & Constraints
1. **Data Preparation**: Generate a grid of normalized pixel coordinates (x, y) scaled to the [0, 1] range. Flatten the image tensor to obtain pixel values.
2. **Positional Encoding**: Implement a `positional_encoding` function. The default dimension should be 64. The encoding logic must calculate sin/cos for x and y coordinates respectively and sum them (as per specific user requirement).
3. **Network Architecture**: Define an MLP class with the following structure: Input Layer (matches encoding dimension) -> 128 -> 256 -> 512 -> 1 (Output for Grayscale). Use ReLU activation for hidden layers.
4. **Training**: Use MSELoss and Adam optimizer. Implement a training loop using a DataLoader.
5. **Model Persistence**: Include code to save the model's `state_dict` and code to load it for continued training or testing.
6. **Testing/Inference**: Implement a function that loads the model, generates coordinates for an arbitrary target resolution, performs prediction, and visualizes the result using matplotlib.
7. **Device Management**: Ensure the model, input data, and target data are all moved to the same device (CPU or CUDA) to prevent errors.

# Anti-Patterns
- Do not use Convolutional Neural Networks (CNNs); strictly use the requested MLP structure.
- Do not omit the positional encoding step.
- Do not hardcode image paths; use placeholders.
- Do not forget to handle variable transfer between CPU and GPU.

## Triggers

- 用神经网络拟合图像坐标
- 使用位置编码重建图像
- 实现输入任意尺寸即可输出该尺寸的前述图像的代码
- 基于位置编码的图像回归代码
- 加载模型进行测试的test代码
