"""
iFlow AI backend tools for TermPipe MCP Server.
"""

import asyncio
import concurrent.futures
from typing import Optional
from termpipe_mcp.helpers import api_get, get_iflow_credentials

# Global model state
_iflow_model = "qwen3-coder-plus"


async def iflow_query_async(
    prompt: str,
    system: Optional[str] = None,
    model: Optional[str] = None,
    max_tokens: int = 500,
    temperature: float = 0.2,
    timeout: int = 30,
):
    """Direct async query to iFlow API."""
    import aiohttp
    import time
    
    global _iflow_model
    start = time.time()
    
    try:
        api_key, api_base = get_iflow_credentials()
    except FileNotFoundError as e:
        return {"success": False, "content": "", "error": str(e)}
    
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    
    use_model = model or _iflow_model
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{api_base}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": use_model,
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
                        "model": use_model,
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
    global _iflow_model
    
    @mcp.tool()
    def ifp_send(message: str, model: Optional[str] = None) -> str:
        """
        Send task to iFlow (MiniMax-M2, Qwen3, Kimi-K2, etc).
        
        Available models (all FREE):
        - qwen3-coder-plus: FASTEST - Best for commands
        - deepseek-v3.2: Good balance
        - kimi-k2: Best quality for complex tasks
        - glm-4.6: General purpose
        """
        global _iflow_model
        
        try:
            import sys
            sys.path.insert(0, str(__file__).rsplit('/', 3)[0])
            from iflow_backend import IFlowBackend
            
            use_model = model or _iflow_model
            
            def run_async():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    async def _query():
                        backend = IFlowBackend(model=use_model)
                        try:
                            result = await backend.query(message)
                            if result.success:
                                return f"{result.content}\n\n[{result.model} | {result.response_time:.2f}s | {result.tokens_used} tokens]"
                            else:
                                return f"Error: {result.error}"
                        finally:
                            await backend.close()
                    return loop.run_until_complete(_query())
                finally:
                    loop.close()
            
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(run_async)
                return future.result(timeout=60)
            
        except ImportError:
            result = iflow_query(message, model=model, max_tokens=1000)
            return result

    @mcp.tool()
    def ifp_model(model_name: str) -> str:
        """
        Switch iFlow to a different model.
        
        Available: qwen3-coder-plus, deepseek-v3.2, kimi-k2, glm-4.6
        """
        global _iflow_model
        _iflow_model = model_name
        return f"✅ Switched to model: {model_name}"

    @mcp.tool()
    def ifp_status() -> str:
        """Get iFlow status and current configuration."""
        global _iflow_model
        
        try:
            api_key, api_base = get_iflow_credentials()
            has_key = True
            key_preview = f"{api_key[:8]}...{api_key[-4:]}" if len(api_key) > 12 else "***"
        except:
            has_key = False
            api_base = "https://apis.iflow.cn/v1"
            key_preview = "Not configured"
        
        health = api_get("/health")
        server_status = "✅ Running" if health.get("status") == "healthy" else "❌ Not running"
        
        return f"""iFlow Status:
  ✅ API configured: {has_key}
  🔑 Key: {key_preview}
  🌐 API base: {api_base}
  🤖 Current model: {_iflow_model}
  
FastAPI Server:
  {server_status}
  Intelligence: {'✅' if health.get('intelligence_available') else '❌'}
  Uptime: {health.get('uptime', 0):.1f}s"""
