import os
from google import genai
from google.genai import types

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
    if ext != '.pdf':
        return None, "סוג קובץ לא נתמך. המערכת מקבלת חוזי שכירות בפורמט PDF בלבד."
        
    try:
        with open(file_path, "rb") as f:
            file_bytes = f.read()
        pdf_part = types.Part.from_bytes(data=file_bytes, mime_type='application/pdf')
        return pdf_part, None
    except Exception:
        return None, "חלה שגיאה פנימית בקריאת קובץ ה-PDF במחשב."

# הנחיה קבועה מראש לאייגנט - נשארת קבועה בתוך ה-config
SYSTEM_INSTRUCTION = (
    "אתה אייגנט מומחה לניתוח חוזי שכירות בישראל. "
    "עליך לקרוא את חוזה השכירות המצורף ב-PDF, לבצע לו סיכום ברור של התנאים המרכזיים "
    "(כמו דמי שכירות, תקופה, ערבויות), להשתמש בכלים שברשותך כדי לבדוק אם הוא כתוב נכון, "
    "ולאתר 'נורות אדומות', ליקויים או סעיפים שיש בהם ניצול לרעה מול החוק והאתרים הרשמיים."
)

def run_rental_contract_agent(pdf_path: str, max_steps: int = 5):
    # 1. אתחול הלקוח של גוגל
    client = genai.Client()
    
    # 2. הכנת קובץ ה-PDF בצורה בטוחה
    pdf_part, error_message = safe_prepare_pdf_contract(pdf_path)
    if error_message:
        return error_message

    # 3. הגדרת הקונפיגורציה הקבועה (הנחיות מערכת וכלים) - לא משתנה במהלך הלולאה
    agent_config = types.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTION,
        tools=gemini_tools
    )

    # 4. יצירת מערך ההיסטוריה הידני (ההודעה הראשונה של המשתמש + קובץ ה-PDF)
    user_instruction = "אנא נתח את חוזה השכירות המצורף, סכם אותו, והצבע על נורות אדומות וליקויים."
    
    messages = [
        types.Content(
            role="user", 
            parts=[types.Part.from_text(text=user_instruction), pdf_part]
        )
    ]

    # 5. לולאת האג'נט (ReAct)
    for _ in range(max_steps):
        try:
            # שולחים את ההיסטוריה הנוכחית (messages) יחד עם הקונפיגורציה הקבועה
            response = client.models.generate_content(
                model='gemini-3.7-flash', # עודכן לגרסה העדכנית ביותר
                contents=messages,
                config=agent_config
            )
        except Exception as e:
            return f"מצטער, חלה שגיאה זמנית בתקשורת עם שרת הבינה המלאכותית: {e}"

        # הוספת התשובה של המודל (או בקשת הכלי שלו) להיסטוריה הידנית
        # response.candidates[0].content מכיל את המבנה המדויק של תשובת המודל
        messages.append(response.candidates[0].content)

        # בדיקה האם המודל ביקש להפעיל כלי (פונקציה)
        if response.function_calls:
            # מערך זמני שיכיל את כל התשובות של הכלים בסיבוב הנוכחי
            tool_parts = []
            
            for call in response.function_calls:
                if call.name not in available_tools:
                    continue

                try:
                    fn = available_tools[call.name]
                    tool_result = fn(**call.args)
                except Exception as e:
                    tool_result = f"הכלי נכשל בהרצה: {e}"

                # יצירת חלק התשובה עבור הכלי הספציפי
                tool_parts.append(
                    types.Part.from_function_response(
                        name=call.name, 
                        response={"result": tool_result}
                    )
                )
            
            # הוספת כל תשובות הכלים כהודעה אחת מסוג "tool" למערך ההיסטוריה הידני
            messages.append(
                types.Content(
                    role="tool",
                    parts=tool_parts
                )
            )
            continue # ממשיך לצעד הבא בלולאה כדי לקבל את תגובת המודל לתשובות הכלים
            
        # אם אין דרישה לכלי - המודל החזיר תשובה טקסטואלית סופית
        return response.text

    return "האייגנט לא הצליח לסיים את הניתוח במסגרת מספר הצעדים המותר."


if __name__ == "__main__":
    
