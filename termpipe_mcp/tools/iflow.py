"""
iFlow AI backend tools for TermPipe MCP Server.
Routes all inference to local omniproxy at 9920 (qwen2.5-coder-7b-instruct).
"""

import asyncio
import concurrent.futures
from typing import Optional

_LOCAL_URL = "http://127.0.0.1:9920/v1/chat/completions"
_MODEL = "qwen2.5-coder-7b-instruct"


async def iflow_query_async(
    prompt: str,
    system: Optional[str] = None,
    model: Optional[str] = None,
    max_tokens: int = 500,
    temperature: float = 0.2,
    timeout: int = 30,
):
    """Async query to local omniproxy at 9920."""
    import aiohttp
    import time

    start = time.time()
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                _LOCAL_URL,
                headers={"Content-Type": "application/json"},
                json={
                    "model": _MODEL,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                },
                timeout=aiohttp.ClientTimeout(total=timeout)
            ) as resp:
                data = await resp.json()
                elapsed = time.time() - start

                if "choices" in data:
                    usage = data.get("usage", {})
                    return {
                        "success": True,
                        "content": data["choices"][0]["message"]["content"],
                        "model": _MODEL,
                        "response_time": elapsed,
                        "tokens_used": usage.get("total_tokens", 0),
                    }
                else:
                    error = data.get("error", {}).get("message", str(data))
                    return {"success": False, "content": "", "error": error}

    except asyncio.TimeoutError:
        return {"success": False, "content": "", "error": f"Timeout after {timeout}s"}
    except Exception as e:
        return {"success": False, "content": "", "error": str(e)}


def iflow_query(prompt: str, **kwargs) -> str:
    """Synchronous wrapper for iFlow query."""
    def run_async():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(iflow_query_async(prompt, **kwargs))
        finally:
            loop.close()
    
    try:
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(run_async)
            result = future.result(timeout=60)
        
        if result["success"]:
            return result["content"]
        else:
            return f"[Error: {result.get('error', 'Unknown error')}]"
    except Exception as e:
        return f"[Error: {str(e)}]"


def register_tools(mcp):
    """Register iFlow tools with the MCP server."""

    @mcp.tool()
    def ifp_send(message: str, model: Optional[str] = None) -> str:
        """Send a prompt to local omniproxy (qwen2.5-coder-7b-instruct)."""
        result = iflow_query(message, max_tokens=1000)
        return result

    @mcp.tool()
    def ifp_model(model_name: str) -> str:
        """No-op: all inference is fixed to qwen2.5-coder-7b-instruct via local omniproxy."""
        return f"ℹ️  Model switching disabled — all calls route to {_MODEL} at {_LOCAL_URL}"

    @mcp.tool()
    def ifp_status() -> str:
        """Get iFlow status and current configuration."""
        import socket as _sock
        with _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM) as s:
            s.settimeout(0.3)
            up = s.connect_ex(("127.0.0.1", 9920)) == 0
        server_status = "✅ Running" if up else "❌ Not running"

        return f"""iFlow Status:
  🌐 Endpoint: {_LOCAL_URL}
  🤖 Model: {_MODEL}

Local omniproxy (port 9920):
  {server_status}"""
