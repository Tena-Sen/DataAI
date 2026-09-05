# DataAI

**Language:** [简体中文](README.md) | English

## English Overview

> **A local, governed workspace for conversational data analysis**

DataAI combines DeepAnalyze’s autonomous data-science capabilities with WrenAI’s semantic layer and text-to-SQL workflow in one local environment. Users can ask questions in natural language and move from data querying and exploration to code execution, visualization, and report generation. Accounts, sessions, and model settings are persisted with per-user isolation.

This repository brings together three components to provide an end-to-end workflow from natural-language questions to reproducible analytical results:

- **[DeepAnalyze](https://github.com/ruc-datalab/DeepAnalyze)** — RUC-DataLab’s open-source autonomous data-science agent ([paper](https://arxiv.org/abs/2510.16872) / [model](https://huggingface.co/RUC-DataLab/DeepAnalyze-8B)) for automated data exploration, code execution, visualization, and report generation.
- **[WrenAI](https://github.com/Canner/WrenAI)** — Canner’s open-source GenBI engine, providing governed text-to-SQL and a semantic layer (MDL). Its upstream source is included under **`WrenAI/`** for local reference, integration, and Wren CLI builds.
- **Core workspace** — `DeepAnalyze/demo/chat_v2/`, an out-of-the-box conversational analytics application that connects DeepAnalyze and WrenAI with user authentication, isolated sessions, automatic semantic-layer construction, sandboxed code execution, and persistent model settings.

Supported sources include CSV, Excel, and SQLite files uploaded within a session. DataAI automatically builds DuckDB and a dynamic MDL, exposes them through the WrenAI semantic layer, and enables governed SQL queries through the injected `wren_query()` function.

***
