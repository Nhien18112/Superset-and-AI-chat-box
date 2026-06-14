# VDT Data Platform (Phase 2) - AI Agent Instructions

## 1. Project Overview
This project is an Enterprise Data Platform for Viettel Software featuring an **Agentic Text-to-SQL Chatbot**. 
The core objective is to allow users to query stock market data via natural language while STRICTLY enforcing Row-Level Security (RLS). 

**CRITICAL:** This is NOT a Retrieval-Augmented Generation (RAG) system. Do not suggest or implement Vector Databases (Pinecone, Milvus, etc.) or text chunking. This is a purely Structured Data (Text-to-SQL and Data-to-Text) architecture.

## 2. Tech Stack & Architecture
- **Database:** PostgreSQL 15 (`vdt_db`)
- **Data Engine & RLS:** Apache Superset (Dockerized, Port 8088)
- **Backend Core:** Spring Boot 3 (Java 17, MVC Architecture)
- **Frontend:** Angular 17+
- **LLM Provider:** Groq API (using Llama 3 / Mixtral for Text-to-SQL)
- **Python Worker:** FastAPI (Microservice for automated Dashboard-as-Code)
- **Deployment:** Docker Compose

## 3. Database Schema (Mock Stock Market)
The system uses a Star Schema in PostgreSQL. All generated SQL MUST strictly adhere to these tables:
- `dim_tickers` (ticker_id, company_name, industry)
- `dim_brokers` (broker_id, broker_name)
- `dim_investors` (investor_id, investor_name, broker_id)
- `fact_orders` (order_id, investor_id, ticker_id, order_date, order_type, volume, price, status)

## 4. Core Workflows (Do not deviate from these paths)

### Workflow A: The Text-to-SQL Chat (Spring Boot)
1. User sends a natural language question via Angular UI to Spring Boot.
2. Spring Boot calls Groq API (LLM) with the DB Schema.
3. LLM returns a GENERIC SQL query (e.g., `SELECT * FROM fact_orders`).
4. Spring Boot intercepts the SQL and sends it to the Superset API.
5. **IMPERSONATION:** Spring Boot executes the query on Superset *under the context of the specific user*. Superset's internal engine injects RLS filters automatically.
6. Spring Boot returns the secure JSON data to Angular.

### Workflow B: Dashboard Automation (FastAPI Worker)
1. Spring Boot sends a POST request (`dataset_id`, `dashboard_title`) to the FastAPI worker.
2. FastAPI uses the `requests` library to authenticate with the Superset REST API.
3. FastAPI creates Charts (Slices) and embeds them into a new Dashboard.
4. FastAPI returns the generated `dashboard_id` to Spring Boot.

## 5. Strict AI Guidelines (The "Never" Rules)
- **NEVER let the LLM handle RLS:** Do not instruct the AI to write `WHERE user_id = X` in its SQL prompt. The LLM must remain blind to RLS. Superset handles RLS natively.
- **NEVER mix languages in code:** All variables, function names, class names, file names, and code comments MUST be in English.
- **NEVER bloat the Spring Boot container:** Do not suggest installing Python inside the Java Docker image. Python scripts must remain isolated in the `python-workers` FastAPI service.
- **NEVER bypass DTOs:** Frontend and Backend must communicate strictly through structured DTOs (Data Transfer Objects), never direct Entities.

## 6. Your Role as the Coding Agent
When asked to write code for this project:
1. Always confirm you have read `instruction.md`.
2. Ensure the code fits into the MVC pattern (for Java) or the designated microservice.
3. Write clean, production-ready code with proper error handling (GlobalExceptionHandler in Spring Boot, HTTPException in FastAPI).