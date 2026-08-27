import logging
import os
import time
import json

from google import genai
from google.genai import types
from google.genai.errors import APIError

from config import GEMINI_API_KEY, SYSTEM_PROMPT
from tools import GEMINI_TOOLS_DECLARATION, TOOLS_MAP, validate_tool_arguments

# Configure system logging environment
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("agent_run.log", encoding="utf-8")
    ]
)
log = logging.getLogger("tenant_ally")

client = genai.Client(api_key=GEMINI_API_KEY)

def safe_prepare_pdf_contract(file_path: str):
    MAX_SIZE = 10 * 1024 * 1024

    if not os.path.exists(file_path):
        return None, "טעות בנתיב: קובץ חוזה השכירות לא נמצא במערכת."

    if os.path.getsize(file_path) > MAX_SIZE:
        return None, "הקובץ כבד מדי. אנא העלה חוזה שכירות שקטן מ-10MB."

    _, ext = os.path.splitext(file_path.lower())
    if ext != ".pdf":
        return None, "סוג קובץ לא נתמך. המערכת מקבלת חוזי שכירות בפורמט PDF בלבד."

    try:
        with open(file_path, "rb") as f:
            file_bytes = f.read()
        pdf_part = types.Part.from_bytes(
            data=file_bytes, mime_type="application/pdf"
        )
        return pdf_part, None
    except Exception:
        return None, "חלה שגיאה פנימית בקריאת קובץ ה-PDF במחשב."
    
def call_gemini_api_with_retry(messages, tools):
    sleep_times = [20, 30, 50, 60]
    
    for attempt in range(len(sleep_times) + 1):
        try:
            return client.models.generate_content(
                model="gemini-3.7-flash",
                contents=messages,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT, tools=tools, temperature=0.1
                ),
            )
        except (APIError, Exception) as e:

            # Stop immediately if quota is reached (error 429 or quota message)
            if "quota" in str(e).lower() or "exhausted" in str(e).lower():
                log.error("Execution stopped: Google API quota exhausted.")
                raise SystemExit("Stopped: Quota exhausted.")

            if attempt == len(sleep_times):
                log.error(f"Critical API failure after maximum retry attempts: {e}")
                raise
            
            wait_time = sleep_times[attempt]
            log.info(f"Sleeping for {wait_time} seconds before next retry...")
            time.sleep(wait_time)

def run_agent_loop(user_input: str, pdf_path: str = None, max_steps: int = 5) -> str:
    log.info(f"[AGENT START] Processing request: '{user_input[:50]}...'")

    input_parts = [types.Part.from_text(text=user_input)]

    if pdf_path:
        log.info(f"[FILE PROCESS] Loading and validating PDF: {pdf_path}")
        pdf_part, error_message = safe_prepare_pdf_contract(pdf_path)
        if error_message:
            log.error(f"[VALIDATION ERROR] {error_message}")
            return error_message
        input_parts.append(pdf_part)

    messages = [types.Content(role="user", parts=input_parts)]

    step = 0
    total_input_tokens = 0
    total_output_tokens = 0

    while step < max_steps:
        step += 1
        log.info(f"[STEP {step}/{max_steps}] Calling Gemini 3.7 Flash...")

        try:
            
            response = call_gemini_api_with_retry(messages, GEMINI_TOOLS_DECLARATION)
            
            if response.usage_metadata:
                step_input = response.usage_metadata.prompt_token_count
                step_output = response.usage_metadata.candidates_token_count
                total_input_tokens += step_input
                total_output_tokens += step_output
                log.info(f"[TOKENS] Step {step} usage - Input: {step_input}, Output: {step_output}")

            candidate = response.candidates[0] if response.candidates else None
            if not candidate or not candidate.content:
                log.warning("[WARN] Empty model response received.")
                break

            model_content = candidate.content
            messages.append(model_content)

            tool_calls = [
                part.function_call
                for part in model_content.parts
                if part.function_call
            ]

            if not tool_calls:
                log.info("[AGENT CONCLUSION] No more tool calls requested. Returning final answer.")
                log.info(f"[METRICS] Total Steps: {step} | Total Input Tokens: {total_input_tokens} | Total Output Tokens: {total_output_tokens}")
                log.info(f"[AGENT FINAL OUTPUT] {response.text}")
                return response.text

            tool_response_parts = []
            for call in tool_calls:
                tool_name = call.name
                tool_args = call.args
                log.info(f"[TOOL CALL] Model requested tool '{tool_name}' with parameters: {tool_args}")

                if tool_name in TOOLS_MAP:
                    is_valid, validation_msg = validate_tool_arguments(tool_name, tool_args)
                    
                    if not is_valid:
                        log.warning(f"[GUARDRAIL BLOCKED] Tool '{tool_name}' blocked due to: {validation_msg}")
                        tool_response_parts.append(
                            types.Part.from_function_response(
                                name=tool_name,
                                response={"result": f"Error: Action blocked by security guardrails. {validation_msg}"},
                            )
                        )
                        continue
                    
                    # Safe invocation of the targeted tool with isolated exception handling
                    tool_function = TOOLS_MAP[tool_name]
                    try:
                        result_string = tool_function(**tool_args)
                        log.info(f"[TOOL RESULT] Tool '{tool_name}' returned: {str(result_string)[:100]}...")
                    except Exception as tool_error:
                        log.exception(f"[TOOL ERROR] Tool '{tool_name}' execution failed: {tool_error}")
                        result_string = json.dumps({"status": "ERROR", "error": "Tool execution failed."})

                    tool_response_parts.append(
                        types.Part.from_function_response(
                            name=tool_name, response={"result": result_string}
                        )
                    )
                else:
                    log.error(f"[ERROR] Model requested an unknown tool: '{tool_name}'")
                    tool_response_parts.append(
                        types.Part.from_function_response(
                            name=tool_name,
                            response={"result": "Error: Tool not found."},
                        )
                    )

            messages.append(
                types.Content(role="user", parts=tool_response_parts)
            )

        except APIError as api_err:
            log.error(f"[CRITICAL API ERROR] Gemini API call failed: {str(api_err)}")
            return "מצטערים, חלה שגיאת תקשורת עם שרת ה-AI. אנא נסה שוב מאוחר יותר."
        except Exception as e:
            log.error(f"[CRITICAL SYSTEM ERROR] Internal loop crash: {str(e)}")
            return "חלה שגיאה פנימית במערכת הניתוח."

    log.warning(f"[SAFETY BRAKE] Agent reached maximum allowed steps ({max_steps}) without finishing.")
    return "האייגנט הגיע למגבלת הצעדים המקסימלית מבלי להשלים את המשימה."

if __name__ == "__main__":
    sample_lease_problem = """
    שכר הדירה שלי הוא 5,000 ש"ח לחודש. בעל הדירה רשם בחוזה שעלי להפקיד ערבות בנקאית של 22,000 ש"ח.
    בנוסף, הוא הכניס סעיף שאומר 'השוכר מתחייב לתקן על חשבונו כל תקלה במזגן או באינסטלציה של הדירה'. 
    האם החוזה תקין וחוקי?
    """
    log.info("=== הרצה: טקסט בלבד ===")
    final_output_text = run_agent_loop(sample_lease_problem)
    print("\n================ FINAL USER OUTPUT (TEXT) ================")
    print(final_output_text)
