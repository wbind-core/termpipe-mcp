"""
Web search tools for TermPipe MCP Server.
"""

import requests
import json
from typing import Optional


def register_tools(mcp):
    """Register web search tools with the MCP server."""

    @mcp.tool()
    def web_search(
        query: str,
        max_results: int = 5,
        include_answer: bool = True
    ) -> str:
        """
        Perform a web search using Exa AI API.

        Args:
            query: The search query to execute
            max_results: Maximum number of results to return (default: 5)
            include_answer: Whether to include a generated answer (default: True)
        """
        try:
            # Exa AI API configuration
            url = "https://api.exa.ai/search"
            headers = {
                "accept": "application/json",
                "content-type": "application/json",
                "x-api-key": "fd241626-1678-47a1-a1cd-d6f53da984e5"
            }
            
            # Prepare the payload for Exa
            payload = {
                "query": query,
                "numResults": max_results,
                "type": "auto",
                "contents": {
                    "text": True
                }
            }
            
            # Make the API request
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            
            if response.status_code != 200:
                return f"[Error: Exa AI API request failed with status {response.status_code}: {response.text}]"
            
            # Parse the response
            data = response.json()
            
            # Format the results
            result_str = f"🌐 Web Search Results for: '{query}'\n"
            result_str += "=" * 60 + "\n\n"
            
            # Exa doesn't have a direct 'answer' in the basic search response like Tavily,
            # but we can show some metadata or just the results.
            
            if "results" in data and data["results"]:
                result_str += f"📚 Search Results ({len(data['results'])}):\n"
                for i, result in enumerate(data["results"], 1):
                    title = result.get("title", "No Title")
                    url = result.get("url", "No URL")
                    text = result.get("text", "No content available")
                    
                    result_str += f"\n{i}. {title}\n"
                    result_str += f"   URL: {url}\n"
                    result_str += f"   Content: {text[:200]}...\n"
            else:
                result_str += "No results found.\n"
                
            return result_str
            
        except requests.exceptions.RequestException as e:
            return f"[Error: Network error occurred during web search - {str(e)}]"
        except json.JSONDecodeError:
            return "[Error: Failed to parse response from Exa AI API]"
        except Exception as e:
            return f"[Error: An unexpected error occurred - {str(e)}]"
