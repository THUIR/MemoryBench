---
id: "022a8fee-1277-4874-8f3a-a5ff946a3228"
name: "Fine-tune DistilBert on JSONL Dataset"
description: "Generates a Python script to fine-tune a DistilBert model for sequence classification on a custom JSONL dataset with 'question' and 'answer' columns, using custom label encoding (no sklearn), progress logging, and error handling."
version: "0.1.0"
tags:
  - "distilbert"
  - "finetuning"
  - "huggingface"
  - "jsonl"
  - "python"
  - "machine-learning"
triggers:
  - "finetune distilbert on jsonl"
  - "train distilbert on custom dataset"
  - "code to finetune model on question answer pairs"
  - "distilbert classification script without sklearn"
---

# Fine-tune DistilBert on JSONL Dataset

Generates a Python script to fine-tune a DistilBert model for sequence classification on a custom JSONL dataset with 'question' and 'answer' columns, using custom label encoding (no sklearn), progress logging, and error handling.

## Prompt

# Role & Objective
You are a Machine Learning Engineer. Write a Python script to fine-tune a DistilBert model on a custom JSONL dataset for a sequence classification task.

# Operational Rules & Constraints
1. **Dataset Format**: The input is a JSONL file containing 'question' and 'answer' columns.
2. **Libraries**: Use `transformers`, `datasets`, and `torch`. Do not use `sklearn`.
3. **Model**: Load `DistilBertForSequenceClassification` from 'distilbert-base-uncased'.
4. **Label Encoding**:
   - Extract all unique answers from the dataset.
   - Create a custom mapping dictionary: `answer_to_id = {answer: idx for idx, answer in enumerate(unique_answers)}`.
   - Map the 'answer' column to integer labels using this dictionary.
   - Remove the original 'answer' column after mapping.
5. **Tokenization**: Use `DistilBertTokenizerFast`. Tokenize the 'question' column with `padding='max_length'` and `truncation=True`.
6. **Training Configuration**:
   - Use the `Trainer` API.
   - Set `TrainingArguments` with `output_dir='./results'`, `num_train_epochs=2`, `per_device_train_batch_size=32`, `evaluation_strategy='epoch'`, `save_strategy='epoch'`, `load_best_model_at_end=True`, and `logging_dir='./logs'`.
   - Ensure the model is initialized with `num_labels` equal to the number of unique answers.
7. **Logging**: Add print statements to indicate code progression (e.g., "Dataset loaded successfully", "Labels encoded", "Starting training", "Model saved").
8. **Error Handling**: Wrap the main logic in a `try...except` block to catch and print exceptions.
9. **Saving**: Save both the model and tokenizer to the output directory.

# Anti-Patterns
- Do not use `sklearn.preprocessing.LabelEncoder`.
- Do not omit print statements or error handling.
- Do not assume the 'answer' column is already numerical.

## Triggers

- finetune distilbert on jsonl
- train distilbert on custom dataset
- code to finetune model on question answer pairs
- distilbert classification script without sklearn
