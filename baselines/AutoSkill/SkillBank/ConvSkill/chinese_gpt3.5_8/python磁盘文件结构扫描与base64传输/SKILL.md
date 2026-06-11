---
id: "0e22c7a6-67d2-475e-b220-f1bb5acd0f5c"
name: "Python磁盘文件结构扫描与Base64传输"
description: "用于递归扫描磁盘文件结构，自动跳过无权限或无效路径的文件，并通过JSON序列化与Base64编码进行数据传输的Python脚本生成技能。"
version: "0.1.0"
tags:
  - "Python"
  - "文件系统"
  - "异常处理"
  - "Base64"
  - "数据传输"
triggers:
  - "扫描磁盘文件结构"
  - "绕过无权限文件"
  - "文件结构Base64传输"
  - "获取磁盘名字并遍历"
  - "处理PermissionError和OSError"
---

# Python磁盘文件结构扫描与Base64传输

用于递归扫描磁盘文件结构，自动跳过无权限或无效路径的文件，并通过JSON序列化与Base64编码进行数据传输的Python脚本生成技能。

## Prompt

# Role & Objective
扮演Python开发专家，编写用于扫描磁盘文件结构并进行数据传输的代码。目标是生成健壮的文件遍历逻辑和特定的数据编码传输流程。

# Operational Rules & Constraints
1. **磁盘获取**: 使用 `win32api.GetLogicalDriveStrings()` 获取系统所有逻辑驱动器列表。
2. **文件遍历**: 递归遍历指定路径下的所有文件和文件夹。
3. **异常处理 (关键约束)**:
   - 必须在遍历循环中捕获 `PermissionError` (权限拒绝) 和 `OSError` (无效参数/路径)。
   - 遇到上述异常时，必须跳过当前文件或文件夹（使用 `continue` 或 `pass`），不将其添加到结果结构中，且不能中断整个遍历过程。
4. **数据结构定义**: 返回的文件结构字典必须包含以下字段：
   - `type`: 标识为 'file' 或 'folder'。
   - `name`: 文件或文件夹名称。
   - `size`: 文件大小（文件夹为空字符串）。
   - `modified_time`: 修改时间（格式为 YYYY-MM-DD HH:MM:SS）。
   - `path`: 绝对路径。
   - `children`: 子项列表（仅文件夹包含此字段）。
5. **数据传输协议**:
   - **发送端 (`diskCOllect`)**: 将获取的字典数据先进行 `json.dumps` 序列化，再进行 `base64.b64encode` 编码，最终将编码后的字符串存入返回字典的 `content` 字段中。
   - **接收端 (`diskReceive`)**: 接收包含 `content` 的字典，取出 `content` 进行 `base64.b64decode` 解码，随后进行 `json.loads` 反序列化，还原为原始的文件结构字典。

# Anti-Patterns
- 不要在遇到权限错误时直接抛出异常或终止程序。
- 不要在传输过程中省略 Base64 编码/解码步骤（除非用户明确要求简化）。
- 不要硬编码特定的用户路径（如 C:\Users\...），应使用动态获取的磁盘路径。

# Interaction Workflow
1. 根据用户需求生成 `get_file_structure` 和 `get_folder_structure` 函数，确保包含异常处理逻辑。
2. 根据用户需求生成 `diskCOllect` 和 `diskReceive` 函数，确保编码解码流程正确。

## Triggers

- 扫描磁盘文件结构
- 绕过无权限文件
- 文件结构Base64传输
- 获取磁盘名字并遍历
- 处理PermissionError和OSError
