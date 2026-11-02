import json
import urllib.request
from typing import Dict, Any, List, Optional
from omgr.config import ProviderConfig

class SecondOpinionReviewer:
    def __init__(self, config: ProviderConfig):
        self.config = config

    def request_review(self, tool_name: str, proposed_args: Dict[str, Any], history: List[Dict[str, Any]], intent: str) -> Optional[Dict[str, Any]]:
        """
        Sends the proposed tool call to GLM for pre-commit review.
        Returns the finalized arguments (which could be the same, modified, or None if failed).
        """
        if not self.config.api_key or not self.config.base_url:
            return proposed_args

        # Construct the context payload for GLM
        history_str = json.dumps(history[-2:] if len(history) >= 2 else history, indent=2)
        args_str = json.dumps(proposed_args, indent=2)

        system_msg = (
            "You are an expert pre-commit reviewer. The primary model is about to execute a tool. "
            "You must review the proposed arguments. If they are correct and safe, return them unchanged. "
            "If they contain mistakes (e.g. bad syntax, incorrect lines, unsafe operations), FIX THEM. "
            "You must respond with ONLY valid JSON representing the finalized arguments. No markdown formatting, no explanations."
        )

        user_msg = f"""
[CONTEXT: RECENT HISTORY]
{history_str}

[PRIMARY MODEL INTENT]
{intent}

[PROPOSED TOOL EXECUTION]
Tool: {tool_name}
Arguments:
{args_str}

Return ONLY a JSON object with the finalized arguments for `{tool_name}`.
"""

        payload = {
            "model": self.config.default_model,
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg}
            ],
            "temperature": 0.1
        }

        try:
            req = urllib.request.Request(
                f"{self.config.base_url}/chat/completions",
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.config.api_key}"
                }
            )

            with urllib.request.urlopen(req, timeout=30) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
                content = res_data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()

                # Clean up potential markdown formatting
                if content.startswith("```json"):
                    content = content[7:]
                if content.startswith("```"):
                    content = content[3:]
                if content.endswith("```"):
                    content = content[:-3]

                finalized_args = json.loads(content.strip())
                return finalized_args

        except Exception as e:
            print(f"\n⚠️  [Second Opinion Reviewer Failed: {e}]. Proceeding with original arguments.")
            return proposed_args
