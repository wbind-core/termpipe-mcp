"""
TermPipe FastAPI Server - Minimal backend for MCP command execution and NLP.
"""

import asyncio
import subprocess
import time
from typing import Optional, List, Dict, Any
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from termpipe_mcp.config import config


# =============================================================================
# Request/Response Models
# =============================================================================

class CommandRequest(BaseModel):
    """Request model for command execution"""
    command: str = Field(..., description="Command name (usually 'exec')")
    args: List[str] = Field(default=[], description="Command arguments")
    raw_command: Optional[str] = Field(None, description="Raw command string")
    timeout: Optional[int] = Field(None, description="Timeout in seconds")


class NLPRequest(BaseModel):
    """Request model for NLP queries"""
    query: str = Field(..., description="Natural language query")
    execute: bool = Field(True, description="Execute resulting command")


class CommandResponse(BaseModel):
    """Response model for command execution"""
    success: bool
    output: str = ""
    error: Optional[str] = None
    exit_code: int = 0
    duration: float = 0.0
    metadata: Dict[str, Any] = {}
    suggestions: List[str] = []


class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    uptime: float
    version: str = "2.0.0"


# =============================================================================
# Application Setup
# =============================================================================

start_time = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    print("🚀 TermPipe FastAPI Server starting...")
    print(f"   Config: {config.config_file}")
    yield
    print("👋 TermPipe FastAPI Server shutting down...")


app = FastAPI(
    title="TermPipe MCP Backend",
    description="Minimal FastAPI backend for TermPipe MCP server",
    version="2.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# API Endpoints
# =============================================================================

@app.get("/", tags=["General"])
async def root():
    """Root endpoint"""
    return {
        "service": "TermPipe MCP Backend",
        "version": "2.0.0",
        "endpoints": {
            "health": "GET /health",
            "execute": "POST /exec",
            "nlp": "POST /nlp"
        }
    }


@app.get("/health", response_model=HealthResponse, tags=["General"])
async def health_check():
    """Health check endpoint"""
    return HealthResponse(
        status="healthy",
        uptime=time.time() - start_time
    )


@app.post("/exec", response_model=CommandResponse, tags=["Commands"])
async def execute_command(request: CommandRequest):
    """
    Execute a shell command.
    
    Supports:
    - Direct command execution via raw_command
    - Argument list via args
    - Timeout configuration
    """
    start = time.time()
    
    try:
        # Determine command to execute
        if request.command == "exec":
            if request.raw_command:
                cmd = request.raw_command
            elif request.args:
                cmd = " ".join(request.args)
            else:
                return CommandResponse(
                    success=False,
                    error="No command provided",
                    exit_code=1,
                    duration=time.time() - start
                )
        else:
            # Other commands (ls, pwd, cat, etc.)
            cmd = f"{request.command} {' '.join(request.args)}"
        
        # Execute with timeout
        timeout = request.timeout or 60
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), 
                timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            return CommandResponse(
                success=False,
                error=f"Command timed out after {timeout}s",
                exit_code=124,
                duration=time.time() - start
            )
        
        return CommandResponse(
            success=proc.returncode == 0,
            output=stdout.decode() if stdout else "",
            error=stderr.decode() if stderr else None,
            exit_code=proc.returncode or 0,
            duration=time.time() - start
        )
        
    except Exception as e:
        return CommandResponse(
            success=False,
            error=str(e),
            exit_code=1,
            duration=time.time() - start
        )


@app.post("/nlp", response_model=CommandResponse, tags=["NLP"])
async def nlp_query(request: NLPRequest):
    """
    Process a natural language query and optionally execute the command.
    
    Uses iFlow API to translate natural language to shell commands.
    """
    start = time.time()
    
    try:
        # Get iFlow credentials
        try:
            api_key, api_base = config.get_iflow_credentials()
        except ValueError as e:
            return CommandResponse(
                success=False,
                error=str(e),
                exit_code=1,
                duration=time.time() - start
            )
        
        # Call iFlow to translate query to command
        import httpx
        
        system_prompt = """You are a Linux shell command expert. Convert natural language queries to precise shell commands.
Rules:
- Output ONLY the command, no explanation
- Use standard Linux utilities (ls, grep, find, awk, sed, etc.)
- Prioritize readability and safety
- Use absolute paths when possible
"""
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{api_base}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": config.get("default_model", "qwen3-coder-plus"),
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": request.query}
                    ],
                    "temperature": 0.1,
                    "max_tokens": 500
                },
                timeout=30.0
            )
            
            if response.status_code != 200:
                return CommandResponse(
                    success=False,
                    error=f"iFlow API error: HTTP {response.status_code}",
                    exit_code=1,
                    duration=time.time() - start
                )
            
            data = response.json()
            command = data["choices"][0]["message"]["content"].strip()
            
            # Clean up command (remove markdown code blocks if present)
            if command.startswith("```"):
                lines = command.split("\n")
                command = "\n".join(lines[1:-1]) if len(lines) > 2 else command
                command = command.strip()
        
        # Execute if requested
        if request.execute:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
            
            return CommandResponse(
                success=proc.returncode == 0,
                output=stdout.decode() if stdout else "",
                error=stderr.decode() if stderr else None,
                exit_code=proc.returncode or 0,
                duration=time.time() - start,
                metadata={"command_executed": command}
            )
        else:
            # Just return the suggested command
            return CommandResponse(
                success=True,
                output=command,
                duration=time.time() - start,
                metadata={"suggested_command": command}
            )
        
    except Exception as e:
        return CommandResponse(
            success=False,
            error=str(e),
            exit_code=1,
            duration=time.time() - start
        )
