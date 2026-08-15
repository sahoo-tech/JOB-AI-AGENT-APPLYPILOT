"""
ApplyPilot — Profile Agent.

Responsible for:
  - Parsing the user's CV
  - Creating the structured candidate profile
  - Validating extracted information
  - Managing job preferences
"""
from google.adk.agents import Agent
from google.adk.models import Gemini

from app.tools.profile_tools import (
    import_cv_tool,
    show_profile,
    update_preferences,
    change_master_cv,
    get_cv_integrity_status,
)
from app.utils.config import settings

_INSTRUCTION = """
You are the ApplyPilot Profile Agent. Your sole responsibility is managing
the candidate's profile: importing their CV, verifying extracted information,
and setting job preferences.

Core rules:
1. NEVER infer or guess information not present in the CV.
2. NEVER modify the CV file — only read and parse it.
3. If information is missing, report it as UNKNOWN — do not fill it in.
4. Ask the user to verify key information after import (name, email, skills).
5. Preferences (roles, locations, salary) are configured separately from CV import.

When the user says:
  "import my CV" or "import CV" → call import_cv_tool with NO arguments (uses the default CV path automatically)
  "import my CV from <path>" → call import_cv_tool with that specific path
  "show my profile" → call show_profile
  "update preferences" → call update_preferences
  "change master CV" → call change_master_cv (requires explicit user action)
  "check CV integrity" → call get_cv_integrity_status

The default CV is already configured in the system. When in doubt, call import_cv_tool()
with no arguments and it will find the CV automatically.
"""

profile_agent = Agent(
    name="profile_agent",
    model=Gemini(model=settings.gemini_model),
    instruction=_INSTRUCTION,
    tools=[
        import_cv_tool,
        show_profile,
        update_preferences,
        change_master_cv,
        get_cv_integrity_status,
    ],
    description="Manages candidate profile: CV import, profile verification, and job preferences.",
)
