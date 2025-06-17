#!/usr/bin/env python3
"""
Mystic Server for Docker Sidecar
Runs the Gnosis Mystic server in a containerized environment.
"""
import os
import sys
import json
import logging
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Configure logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("mystic_server")

# Initialize FastAPI app
app = FastAPI(
    title="Gnosis Mystic Server",
    description="Function hijacking and debugging service",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global state
hijacked_functions = {}
function_metrics = {}
project_root = Path(os.getenv("PROJECT_ROOT", "/app"))


class HijackRequest(BaseModel):
    """Request model for function hijacking."""
    function: str
    strategy: str = "analyze"
    options: Dict[str, Any] = {}


class InspectRequest(BaseModel):
    """Request model for function inspection."""
    function: str
    include_source: bool = True
    include_dependencies: bool = True


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "gnosis-mystic",
        "project_root": str(project_root),
        "hijacked_functions": len(hijacked_functions)
    }


@app.get("/api/status")
async def get_status():
    """Get server status and configuration."""
    return {
        "status": "running",
        "project_root": str(project_root),
        "hijacked_functions": len(hijacked_functions),
        "total_metrics": len(function_metrics),
        "config": {
            "host": os.getenv("MYSTIC_HOST", "0.0.0.0"),
            "port": os.getenv("MYSTIC_PORT", "8899"),
            "mode": os.getenv("MYSTIC_MODE", "server")
        }
    }


@app.post("/api/functions/hijack")
async def hijack_function(request: HijackRequest):
    """Hijack a function with specified strategy."""
    try:
        function_name = request.function
        strategy = request.strategy
        options = request.options
        
        logger.info(f"Hijacking function: {function_name} with strategy: {strategy}")
        
        # Import and hijack the function dynamically
        # This is a simplified version - real implementation would be more complex
        if strategy == "cache":
            duration = options.get("duration", "1h")
            hijacked_functions[function_name] = {
                "strategy": "cache",
                "duration": duration,
                "cache": {},
                "hits": 0,
                "misses": 0
            }
        elif strategy == "mock":
            mock_data = options.get("mock_data", None)
            hijacked_functions[function_name] = {
                "strategy": "mock",
                "mock_data": mock_data,
                "call_count": 0
            }
        elif strategy == "block":
            message = options.get("message", "Function blocked by Mystic")
            hijacked_functions[function_name] = {
                "strategy": "block",
                "message": message,
                "blocked_calls": 0
            }
        elif strategy == "analyze":
            hijacked_functions[function_name] = {
                "strategy": "analyze",
                "call_count": 0,
                "total_time": 0,
                "min_time": float('inf'),
                "max_time": 0,
                "errors": 0
            }
        else:
            raise ValueError(f"Unknown strategy: {strategy}")
        
        # Initialize metrics
        if function_name not in function_metrics:
            function_metrics[function_name] = {
                "total_calls": 0,
                "total_time": 0,
                "errors": 0,
                "last_called": None
            }
        
        return {
            "success": True,
            "function": function_name,
            "strategy": strategy,
            "message": f"Successfully hijacked {function_name} with {strategy} strategy"
        }
        
    except Exception as e:
        logger.error(f"Failed to hijack function: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/functions/unhijack")
async def unhijack_function(function_name: str):
    """Remove hijacking from a function."""
    try:
        if function_name not in hijacked_functions:
            raise ValueError(f"Function {function_name} is not hijacked")
        
        # Get final metrics before removing
        final_metrics = hijacked_functions.get(function_name, {})
        
        # Remove hijacking
        del hijacked_functions[function_name]
        
        return {
            "success": True,
            "function": function_name,
            "message": f"Successfully unhijacked {function_name}",
            "metrics": final_metrics
        }
        
    except Exception as e:
        logger.error(f"Failed to unhijack function: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/functions/inspect")
async def inspect_function(request: InspectRequest):
    """Inspect a function to get detailed information."""
    try:
        function_name = request.function
        
        # Parse function name
        parts = function_name.split('.')
        module_path = '.'.join(parts[:-1])
        func_name = parts[-1]
        
        # This is a simplified inspection - real implementation would
        # actually import and inspect the function
        inspection_result = {
            "name": func_name,
            "module": module_path,
            "full_name": function_name,
            "signature": "(args, kwargs)",  # Placeholder
            "docstring": "Function docstring would be here",
            "file": f"/app/{module_path.replace('.', '/')}.py",
            "line": 1,
            "is_hijacked": function_name in hijacked_functions
        }
        
        if function_name in hijacked_functions:
            inspection_result["hijack_info"] = hijacked_functions[function_name]
        
        if function_name in function_metrics:
            inspection_result["metrics"] = function_metrics[function_name]
        
        return {
            "success": True,
            "function": function_name,
            "inspection": inspection_result
        }
        
    except Exception as e:
        logger.error(f"Failed to inspect function: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/hijacked")
async def list_hijacked():
    """List all currently hijacked functions."""
    hijacked_list = []
    
    for func_name, info in hijacked_functions.items():
        metrics = function_metrics.get(func_name, {})
        hijacked_list.append({
            "function": func_name,
            "strategy": info.get("strategy"),
            "info": info,
            "metrics": metrics
        })
    
    return {
        "success": True,
        "count": len(hijacked_list),
        "functions": hijacked_list
    }


@app.get("/api/metrics")
async def get_metrics(function_name: Optional[str] = None):
    """Get performance metrics for functions."""
    if function_name:
        if function_name not in function_metrics:
            raise HTTPException(status_code=404, detail=f"No metrics for {function_name}")
        return {
            "success": True,
            "function": function_name,
            "metrics": function_metrics[function_name]
        }
    else:
        return {
            "success": True,
            "count": len(function_metrics),
            "metrics": function_metrics
        }


@app.post("/api/init")
async def initialize_project():
    """Initialize Mystic for the project."""
    try:
        mystic_dir = project_root / ".mystic"
        mystic_dir.mkdir(exist_ok=True)
        
        config_file = mystic_dir / "config.json"
        config = {
            "project_name": project_root.name,
            "project_root": str(project_root),
            "ignore_patterns": [
                "*.pyc", "__pycache__", ".git", ".venv", "venv", "env",
                ".pytest_cache", ".mypy_cache"
            ],
            "auto_discover": True,
            "mcp_enabled": True
        }
        
        with open(config_file, 'w') as f:
            json.dump(config, f, indent=2)
        
        return {
            "success": True,
            "message": f"Initialized Mystic for project: {project_root}",
            "config": config
        }
        
    except Exception as e:
        logger.error(f"Failed to initialize project: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def main():
    """Main entry point."""
    host = os.getenv("MYSTIC_HOST", "0.0.0.0")
    port = int(os.getenv("MYSTIC_PORT", "8899"))
    
    logger.info(f"Starting Gnosis Mystic Server on {host}:{port}")
    logger.info(f"Project root: {project_root}")
    
    # Run the server
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level=os.getenv("LOG_LEVEL", "info").lower()
    )


if __name__ == "__main__":
    main()
