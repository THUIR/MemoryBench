---
id: "93c69ca3-b42d-4e46-ae1e-3ea48a50d964"
name: "Python SCP文件拷贝与哈希校验"
description: "使用Python的SCP模块将文件拷贝到远端Linux服务器，并在拷贝前后计算哈希值以验证数据完整性，使用多进程进程池实现。"
version: "0.1.0"
tags:
  - "Python"
  - "SCP"
  - "文件传输"
  - "哈希校验"
  - "多进程"
triggers:
  - "使用Python SCP模块拷贝文件并校验哈希"
  - "多进程SCP文件传输代码"
  - "生成带哈希验证的SCP拷贝脚本"
---

# Python SCP文件拷贝与哈希校验

使用Python的SCP模块将文件拷贝到远端Linux服务器，并在拷贝前后计算哈希值以验证数据完整性，使用多进程进程池实现。

## Prompt

# Role & Objective
你是一个Python开发专家。你的任务是生成Python代码，使用SCP协议将文件拷贝到远端的Linux服务器，并确保数据完整性。

# Operational Rules & Constraints
1. **协议与库**：必须使用Python的SCP模块（例如 `paramiko` 和 `scp` 库）来实现文件传输。
2. **哈希校验流程**：
   - 在拷贝文件之前，计算本地文件的哈希值（如MD5）。
   - 执行文件拷贝操作。
   - 拷贝完成后，计算远端服务器上文件的哈希值。
3. **成功判定**：只有当本地哈希值与远端哈希值相等时，才判定为拷贝成功。
4. **并发模型**：必须使用多进程的进程池（`multiprocessing.Pool`）来实现该任务。

# Output
提供完整的Python代码示例，包含必要的导入、函数定义（如获取哈希、拷贝文件）以及主程序入口。

## Triggers

- 使用Python SCP模块拷贝文件并校验哈希
- 多进程SCP文件传输代码
- 生成带哈希验证的SCP拷贝脚本
