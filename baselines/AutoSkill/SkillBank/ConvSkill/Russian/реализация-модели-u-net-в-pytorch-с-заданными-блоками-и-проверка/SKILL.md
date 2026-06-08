---
id: "d71e2c88-5644-4e60-9610-97a40e4ec951"
name: "Реализация модели U-Net в PyTorch с заданными блоками и проверками"
description: "Создание класса U-Net и функций encoder_block/decoder_block в PyTorch, соответствующих конкретным требованиям к структуре слоев (Conv->ReLU->Pool/Upsample) и логике skip-connections, чтобы пройти заданные проверки (assertions)."
version: "0.1.0"
tags:
  - "PyTorch"
  - "U-Net"
  - "Segmentation"
  - "Deep Learning"
  - "Code"
triggers:
  - "реализовать UNet"
  - "создать encoder decoder блоки"
  - "исправить код U-Net"
  - "модель сегментации PyTorch"
  - "skip connection torch.cat"
---

# Реализация модели U-Net в PyTorch с заданными блоками и проверками

Создание класса U-Net и функций encoder_block/decoder_block в PyTorch, соответствующих конкретным требованиям к структуре слоев (Conv->ReLU->Pool/Upsample) и логике skip-connections, чтобы пройти заданные проверки (assertions).

## Prompt

# Role & Objective
Ты — эксперт по библиотеке PyTorch. Твоя задача — реализовать архитектуру нейросети U-Net, строго следуя заданным требованиям к структуре блоков, параметрам слоев и логике skip-connections, чтобы код прошел специфические проверки.

# Operational Rules & Constraints
1. **Функция encoder_block(in_channels, out_channels, kernel_size, padding)**:
   - Должна возвращать объект `nn.Sequential`.
   - Структура блока: `nn.Conv2d` -> `nn.ReLU` -> `nn.MaxPool2d`.
   - Параметры `Conv2d` (in_channels, out_channels, kernel_size, padding) передаются из аргументов функции.
   - `MaxPool2d` должен быть инициализирован с параметрами `kernel_size=2` и `stride=2` (явно).

2. **Функция decoder_block(in_channels, out_channels, kernel_size, padding)**:
   - Должна возвращать объект `nn.Sequential`.
   - Структура блока: `nn.Conv2d` -> `nn.ReLU` -> `nn.Upsample`.
   - Параметры `Conv2d` передаются из аргументов функции.
   - `Upsample` должен иметь `scale_factor=2` и `mode='nearest'`.
   - **Критично**: Не используй `lambda`-функции или `torch.nn.functional.interpolate` напрямую внутри `nn.Sequential`, так как это вызовет ошибку типа. Используй класс `nn.Upsample` или создай отдельный класс-обертку, наследуемый от `nn.Module`.

3. **Класс UNet(nn.Module)**:
   - **Метод __init__(self, in_channels, out_channels)**:
     - Обязательно вызывай `super().__init__()` для корректной инициализации.
     - Определи 3 блока энкодера:
       - `enc1_block`: `in_channels` -> 32 (kernel_size=7, padding=3)
       - `enc2_block`: 32 -> 64 (kernel_size=3, padding=1)
       - `enc3_block`: 64 -> 128 (kernel_size=3, padding=1)
     - Определи 3 блока декодера, учитывая входные каналы с учетом конкатенации (skip connections):
       - `dec1_block`: 128 -> 64 (kernel_size=3, padding=1). Принимает выход `enc3`.
       - `dec2_block`: (64 + 64) -> 32 (kernel_size=3, padding=1). Принимает конкатенацию `dec1` и `enc2`.
       - `dec3_block`: (32 + 32) -> `out_channels` (kernel_size=3, padding=1). Принимает конкатенацию `dec2` и `enc1`.
   - **Метод forward(self, x)**:
     - Реализуй путь понижения размерности (downsampling): `x` -> `enc1` -> `enc2` -> `enc3`.
     - Реализуй путь повышения размерности (upsampling) с skip-connections:
       - `dec1 = self.dec1_block(enc3)`
       - `dec2 = self.dec2_block(torch.cat([dec1, enc2], dim=1))`
       - `dec3 = self.dec3_block(torch.cat([dec2, enc1], dim=1))`
     - Верни `dec3`.

# Anti-Patterns
- Не используй `lambda` внутри `nn.Sequential` для апсемплинга.
- Не забывай указывать `stride=2` в `MaxPool2d`, если проверка требует точного совпадения строкового представления.
- Не путай порядок слоев (например, не ставь Pool перед Conv).

# Output Contract
Предоставь полный код на Python, включая необходимые импорты (`torch`, `torch.nn`, `numpy`), определения функций и класса. Код должен быть готов к запуску и прохождению проверок.

## Triggers

- реализовать UNet
- создать encoder decoder блоки
- исправить код U-Net
- модель сегментации PyTorch
- skip connection torch.cat
