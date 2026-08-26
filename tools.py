import json
from datetime import datetime
from duckduckgo_search import DDGS

# Tool 1: Mathematical Calculation Tool
def calculate_legal_guarantee(monthly_rent: float, lease_duration_months: float, requested_guarantee: float) -> str:
    """
    Calculates if the requested guarantee/security deposit is legal under the Israeli Fair Lease Law.
    The law strictly limits cash/bank guarantees to the LOWER of either 3 months of rent OR one-third of the total lease period.
    """
    try:
        # Option A: 3 months of rent
        option_a = monthly_rent * 3
        
        # Option B: One-third of the total lease duration
        option_b = monthly_rent * (lease_duration_months / 3)
        
        # Legal ceiling is the minimum of the two options
        max_allowed = min(option_a, option_b)
        
        if requested_guarantee > max_allowed:
            return json.dumps({
                "status": "VIOLATION",
                "message": f"Illegal guarantee requested. Max allowed is {max_allowed:.2f} NIS (lower of 3 months rent or 1/3 of lease duration), but {requested_guarantee:.2f} NIS was requested.",
                "excess_amount": requested_guarantee - max_allowed
            })
        return json.dumps({
            "status": "VALID",
            "message": f"The requested guarantee of {requested_guarantee:.2f} NIS is within the legal limit (Max allowed: {max_allowed:.2f} NIS)."
        })
    except Exception as e:
        return json.dumps({
            "status": "ERROR", 
            "error": f"Failed to calculate guarantee: {str(e)}"
        })

# Tool 2: External API / Internet Lookup Tool
def search_israeli_housing_laws(query: str) -> str:
    """
    Searches Israeli official government, legal, and major municipal databases 
    (gov.il, kolzchut, nevo, muni.org.il) to find specific housing laws or local regulations.
    """
    search_query = f"(site:gov.il OR site:kolzchut.org.il OR site:nevo.co.il OR site:muni.org.il) שכירות {query}"
    try:
        with DDGS() as ddgs:
            results = [r for r in ddgs.text(search_query, max_results=4)]
        if not results:
            return json.dumps({
                "status": "NO_RESULTS", 
                "message": "No specific laws or municipal regulations found for the given query."
            })
        
        formatted_results = [{"title": r["title"], "snippet": r["body"]} for r in results]
        return json.dumps({
            "status": "SUCCESS", 
            "results": formatted_results
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({
            "status": "ERROR", 
            "error": f"Search failed securely: {str(e)}"
        })

# Tool 3: Date and Notice Period Calculation Tool
def calculate_days_between_dates(start_date_str: str, end_date_str: str) -> str:
    """
    Calculates the exact number of days between two dates (Format: YYYY-MM-DD).
    Crucial for verifying notice periods (e.g., if a landlord gave notice 90 days before lease termination as required by law).
    """
    try:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
        
        # Calculate difference
        delta = end_date - start_date
        days_diff = delta.days
        
        return json.dumps({
            "status": "SUCCESS",
            "start_date": start_date_str,
            "end_date": end_date_str,
            "days_between": days_diff,
            "message": f"There are exactly {days_diff} days between the provided dates."
        })
    except ValueError:
        return json.dumps({
            "status": "ERROR",
            "error": "Invalid date format. Please use 'YYYY-MM-DD' format (e.g., '2026-08-25')."
        })
    except Exception as e:
        return json.dumps({
            "status": "ERROR",
            "error": f"Failed to calculate days: {str(e)}"
        })

# Tool Definitions Map for the manual loop dispatcher
TOOLS_MAP = {
    "calculate_legal_guarantee": calculate_legal_guarantee,
    "search_israeli_housing_laws": search_israeli_housing_laws,
    "calculate_days_between_dates": calculate_days_between_dates
}

# Declarations to send to the Gemini API (Schema format)
GEMINI_TOOLS_DECLARATION = [
    {
        "function_declarations": [
            {
                "name": "calculate_legal_guarantee",
                "description": "Calculates if the requested lease guarantee complies with Israeli Fair Lease Law limits (the lower of 3 months rent or 1/3 of the total lease period).",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "monthly_rent": {"type": "NUMBER", "description": "The monthly rent amount in NIS."},
                        "lease_duration_months": {"type": "NUMBER", "description": "The total duration of the lease agreement in months (e.g., 12 for a standard one-year lease)."},
                        "requested_guarantee": {"type": "NUMBER", "description": "The total financial guarantee, bank guarantee, or cash deposit requested by the landlord in NIS."}
                    },
                    "required": ["monthly_rent", "lease_duration_months", "requested_guarantee"]
                }
            },
            {
                "name": "search_israeli_housing_laws",
                "description": "Searches official Israeli housing laws, regulations, and municipal rules across gov.il, Kol Zchut, Nevo, and muni.org.il websites to clarify clauses or user queries.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "query": {"type": "STRING", "description": "Search keyword in Hebrew, e.g., 'ארנונה', 'תיקון מזגן בשכירות'."}
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "calculate_days_between_dates",
                "description": "Calculates the exact number of days between two dates in 'YYYY-MM-DD' format. Use this tool whenever you need to check if a termination notice period or lease extension window complies with Israeli law.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "start_date_str": {"type": "STRING", "description": "The starting date in 'YYYY-MM-DD' format."},
                        "end_date_str": {"type": "STRING", "description": "The ending date in 'YYYY-MM-DD' format."}
                    },
                    "required": ["start_date_str", "end_date_str"]
                }
            }
        ]
    }
]
