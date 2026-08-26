import os
import sys
from google import genai
from google.genai import types
from google.genai.errors import APIError
from tenacity import retry, stop_after_attempt, wait_exponential

from config import GEMINI_API_KEY, SYSTEM_PROMPT
from tools import GEMINI_TOOLS_DECLARATION, TOOLS_MAP

# Initialize the official SDK client
client = genai.Client(api_key=GEMINI_API_KEY)


def safe_prepare_pdf_contract(file_path: str):
    """
    בודקת את תקינות קובץ החוזה (קיום, סיומת וגודל).
    אם הכל תקין: מחזירה את אובייקט ה-Part של גוגל.
    אם יש בעיה: מחזירה (None, הודעת שגיאה מפורטת למשתמש).
    """
    MAX_SIZE = 10 * 1024 * 1024  # מגבלה של 10MB לחוזה

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


# Handle rate limits with retry and exponential backoff as required
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
def call_gemini_api(messages, tools):
    """Executes a single API call to Gemini 3.7 Flash with rate-limit retries."""
    return client.models.generate_content(
        model="gemini-3.7-flash",
        contents=messages,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT, tools=tools, temperature=0.1
        ),
    )


def run_agent_loop(
    user_input: str, pdf_path: str = None, max_steps: int = 5
) -> str:
    """
    Main deterministic loop executing the AI Agent task.
    Manages the full tool lifecycle, logs steps, tracks tokens, and applies a safety brake.
    Supports optional PDF file input.
    """
    print(
        f"\n🚀 [AGENT START] Processing request: '{user_input[:50]}...'"
    )

    # Prepare input parts
    input_parts = [types.Part.from_text(text=user_input)]

    # If a PDF path is provided, validate and process it
    if pdf_path:
        print(f"📄 [FILE PROCESS] Loading and validating PDF: {pdf_path}")
        pdf_part, error_message = safe_prepare_pdf_contract(pdf_path)
        if error_message:
            print(f"❌ [VALIDATION ERROR] {error_message}")
            return error_message
        input_parts.append(pdf_part)

    # Initialize messages list manually (managing state)
    messages = [types.Content(role="user", parts=input_parts)]

    step = 0
    total_input_tokens = 0
    total_output_tokens = 0

    while step < max_steps:
        step += 1
        print(f"\n🔄 [STEP {step}/{max_steps}] Calling Gemini 3.7 Flash...")

        try:
            # Call the model
            response = call_gemini_api(messages, GEMINI_TOOLS_DECLARATION)

            # Count tokens consumed in this call if returned by API metadata
            if response.usage_metadata:
                total_input_tokens += (
                    response.usage_metadata.prompt_token_count
                )
                total_output_tokens += (
                    response.usage_metadata.candidates_token_count
                )

            # Extract candidates and messages
            candidate = response.candidates[0] if response.candidates else None
            if not candidate or not candidate.content:
                print("⚠️ [WARN] Empty model response received.")
                break

            model_content = candidate.content
            # Append model's response to maintain chat context
            messages.append(model_content)

            # Check if the model wants to call a tool (Function Calling)
            tool_calls = [
                part.function_call
                for part in model_content.parts
                if part.function_call
            ]

            if not tool_calls:
                print(
                    "🏁 [AGENT CONCLUSION] No more tool calls requested. Returning final answer."
                )
                print(
                    f"📊 [METRICS] Step Steps taken: {step} | Total Input Tokens: {total_input_tokens} | Total Output Tokens: {total_output_tokens}"
                )
                return response.text

            # Execute requested tools (Full cycle)
            tool_response_parts = []
            for call in tool_calls:
                tool_name = call.name
                tool_args = call.args
                print(
                    f"🛠️ [TOOL CALL] Model requested tool '{tool_name}' with parameters: {tool_args}"
                )

                if tool_name in TOOLS_MAP:
                    # Execute tool safely
                    tool_function = TOOLS_MAP[tool_name]
                    # Unpack keyword arguments dynamically
                    result_string = tool_function(**tool_args)
                    print(
                        f"📥 [TOOL RESULT] Tool '{tool_name}' returned: {result_string}"
                    )

                    # Create a specific Tool Response part to feed back to the model
                    tool_response_parts.append(
                        types.Part.from_function_response(
                            name=tool_name, response={"result": result_string}
                        )
                    )
                else:
                    print(
                        f"❌ [ERROR] Model requested an unknown tool: '{tool_name}'"
                    )
                    tool_response_parts.append(
                        types.Part.from_function_response(
                            name=tool_name,
                            response={"result": "Error: Tool not found."},
                        )
                    )

            # Append the execution outputs back into the conversation history as a 'tool' role
            messages.append(
                types.Content(role="tool", parts=tool_response_parts)
            )

        except APIError as api_err:
            print(
                f"❌ [CRITICAL API ERROR] Gemini API call failed: {str(api_err)}"
            )
            return "מצטער, חלה שגיאת תקשורת עם שרת ה-AI במהלך ניתוח המסמך."
        except Exception as e:
            print(f"❌ [CRITICAL SYSTEM ERROR] Internal loop crash: {str(e)}")
            return "חלה שגיאה פנימית במערכת הניתוח."

    # If the code reaches here, the safety brake was pulled
    print(
        f"\n🛑 [SAFETY BRAKE] Agent reached maximum allowed steps ({max_steps}) without finishing."
    )
    return "האייגנט הגיע למגבלת הצעדים המקסימלית מבלי להשלים את המשימה."


if __name__ == "__main__":
    # דוגמה ראשונה: הרצה עם טקסט בלבד (כמו בקוד 1 המקורי)
    sample_lease_problem = """
    שכר הדירה שלי הוא 5,000 ש"ח לחודש. בעל הדירה רשם בחוזה שעלי להפקיד ערבות בנקאית של 22,000 ש"ח.
    בנוסף, הוא הכניס סעיף שאומר 'השוכר מתחייב לתקן על חשבונו כל תקלה במזגן או באינסטלציה של הדירה'. 
    האם החוזה תקין וחוקי?
    """
    print("=== הרצה 1: טקסט בלבד ===")
    final_output_text = run_agent_loop(sample_lease_problem)
    print("\n================ FINAL USER OUTPUT (TEXT) ================")
    print(final_output_text)

    # דוגמה שנייה: הרצה עם קובץ PDF (התוספת החדשה)
    print("\n=== הרצה 2: שילוב קובץ PDF ===")
    sample_pdf_path = "contract.pdf"  # שנה לנתיב של קובץ אמיתי אצלך במחשב כדי לבדוק
    user_instruction = "אנא נתח את חוזה השכירות המצורף, סכם אותו, והצבע על נורות אדומות וליקויים."

    final_output_pdf = run_agent_loop(
        user_input=user_instruction, pdf_path=sample_pdf_path
    )
    print("\n================ FINAL USER OUTPUT (PDF) ================")
    print(final_output_pdf)
