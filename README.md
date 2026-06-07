# ProtectMe AI

> **Understand before you sign. Ask before you agree.**

## Problem to solve

Navigating complex legal contracts is a daunting task. Individuals and businesses often sign agreements without fully understanding hidden clauses, financial penalties, or legal traps. There is a critical need for a fast, accessible, and bilingual tool to analyze these documents instantly before signing.

## Our solution

We built a real-time, bilingual (Arabic & English) AI voice agent that acts as a smart legal assistant. Users can upload contracts in **PDF, DOCX, or TXT** formats. The agent instantly analyzes the text to detect loopholes, unfair clauses, and hidden risks, providing **sub-second conversational voice responses**.

Furthermore, users can extract and download a comprehensive **PDF Scan Report** detailing the agent's findings for offline use, documentation, or sharing with legal counsel.

## Technologies used

- **Gemini 3.5 Flash:** Powers the core LLM for ultra-fast, advanced logical reasoning and precise contract analysis without compromising latency.
- **Google Cloud TTS:** Provides natural, human-like voice synthesis for both Arabic and English real-time interactions.
- **React (Light Theme):** Delivers a clean, trustworthy user interface.
- **FastAPI & WebSockets:** Ensures a seamless backend architecture for real-time voice streaming with sub-second latency.

## Data sources

User-uploaded legal and contractual documents (PDF, DOCX, TXT).

## Findings and learnings

We discovered that achieving sub-second latency for a conversational voice agent depends heavily on the LLM's Time-to-First-Token (TTFT). Choosing **Gemini 3.5 Flash** provided the perfect balance: deep analytical reasoning for complex legal text combined with the blazing speed required for natural voice interactions. We also learned that users value actionable outputs just as much as the conversation, making the **PDF Report Export** feature a critical addition for real-world utility.

## Third-party integrations (if applicable)

N/A — The core intelligence and voice capabilities are entirely built utilizing the Google Cloud and Gemini ecosystem.
