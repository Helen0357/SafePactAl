"""
Prompt for the IntentRouter — classifies user input into one of 8 intent classes.
Phase 3: full implementation.
"""
from typing import Optional

INTENT_CLASSES = [
    "ask_question",      
    "explain_clause",     
    "generate_message",  
    "summarize_risks",    
    "ask_recommendation",
    "modify_message",     
    "generate_questions",
    "unclear",          
]

INTENT_ROUTER_PROMPT = """\
Classify the user's input into exactly one of these intents:
{intents}

User input: "{user_input}"

Return ONLY a JSON object with this structure:
{{
    "intent": "<one of the intents above>",
    "confidence": <float 0.0–1.0>,
    "target_clause_ids": [],
    "message_type": null,
    "tone": null,
    "format": null
}}

Rules:
- If confidence < 0.6, set intent to "unclear".
- Populate target_clause_ids if the user references specific risks or clauses.
- Populate message_type / tone / format only for generate_message intent.
- Return ONLY the JSON. No explanation.
"""


def build_intent_prompt(user_input: str, active_clause_id: Optional[str] = None) -> str:
    prompt = INTENT_ROUTER_PROMPT.format(
        intents="\n".join(f"  - {i}" for i in INTENT_CLASSES),
        user_input=user_input,
    )
    if active_clause_id:
        prompt += f"\n\nNote: the user is currently focused on clause ID: {active_clause_id}"
    return prompt
