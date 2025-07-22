# /// script
# dependencies = [
#     "fastapi>=0.104.1",
#     "uvicorn[standard]>=0.24.0",
#     "python-multipart>=0.0.6",
#     "pandas>=2.1.3",
#     "scipy>=1.11.4",
#     "numpy>=1.26.0",
#     "httpx>=0.27.0",
#     "pyarrow>=15.0.0",
#     "tomli>=2.0.1",
# ]
# ///

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Tuple, Optional, Union
import pandas as pd
import sqlite3
import json
import os
import httpx
import numpy as np
import scipy.stats as stats
import webbrowser
import threading
import tempfile
import uuid
from pathlib import Path
import tomli

# Load configuration
with open("config.toml", "rb") as f:
    config = tomli.load(f)

app = FastAPI(title=config["app"]["title"], version=config["app"]["version"])
app.mount("/static", StaticFiles(directory="static"), name="static")

# Session storage
TEMP_DIR = Path(tempfile.gettempdir()) / "hypoforge_sessions"
TEMP_DIR.mkdir(exist_ok=True)
session_data = {}

# Models
class LoadRequest(BaseModel):
    source: str  # file_path or demo_url

class DataSessionResponse(BaseModel):
    session_id: str
    description: str
    row_count: int
    column_count: int

class ExecuteTestRequest(BaseModel):
    session_id: str
    analysis_code: str

class ExecuteTestResponse(BaseModel):
    success: bool
    p_value: float

@app.get("/")
async def root():
    return FileResponse("static/index.html")

@app.get("/config")
async def get_config():
    with open("config.json", "r") as f:
        return json.load(f)

@app.post("/load-data")
async def load_data(request: LoadRequest) -> DataSessionResponse:
    """Unified endpoint for loading data from file path or demo URL"""
    try:
        source = request.source.strip()
        
        # Determine if source is URL or file path
        if source.startswith(("http://", "https://")):
            df = await _load_from_url(source)
            original_path = source
        else:
            df = await _load_from_file(source)
            original_path = source
        
        return await _create_session(df, original_path)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error loading data: {str(e)}")

async def _load_from_url(url: str) -> pd.DataFrame:
    """Load data from URL"""
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail=f"Failed to download: {url}")

        file_extension = url.split(".")[-1].lower()
        with tempfile.NamedTemporaryFile(suffix=f".{file_extension}", delete=False) as tmp_file:
            tmp_file.write(response.content)
            temp_path = tmp_file.name

    try:
        return await _load_file_data(temp_path)
    finally:
        os.unlink(temp_path)

async def _load_from_file(file_path: str) -> pd.DataFrame:
    """Load data from file path"""
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=400, detail=f"Path is not a file: {file_path}")
    
    try:
        return await _load_file_data(file_path)
    except pd.errors.EmptyDataError:
        raise HTTPException(status_code=400, detail="The file is empty or contains no valid data")
    except pd.errors.ParserError as e:
        raise HTTPException(status_code=400, detail=f"Error parsing file: {str(e)}")
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Permission denied accessing file: {file_path}")

async def _create_session(df: pd.DataFrame, original_path: str) -> DataSessionResponse:
    """Create session from DataFrame"""
    session_id = str(uuid.uuid4())
    session_file_path = TEMP_DIR / f"{session_id}.parquet"
    df.to_parquet(session_file_path, index=False)
    
    description = _generate_description(df)
    session_data[session_id] = {
        "file_path": str(session_file_path),
        "description": description,
        "original_path": original_path,
        "row_count": len(df),
        "column_count": len(df.columns),
        "created_at": pd.Timestamp.now()
    }

    return DataSessionResponse(
        session_id=session_id,
        description=description,
        row_count=len(df),
        column_count=len(df.columns)
    )

async def _load_file_data(file_path: str) -> pd.DataFrame:
    """Load data from file path into DataFrame"""
    if file_path.lower().endswith(".csv"):
        return pd.read_csv(file_path)
    elif file_path.lower().endswith((".sqlite", ".sqlite3", ".db", ".s3db", ".sl3")):
        conn = sqlite3.connect(file_path)
        tables = pd.read_sql_query("SELECT name FROM sqlite_master WHERE type='table'", conn)
        if tables.empty:
            conn.close()
            raise HTTPException(status_code=400, detail="No tables found in database")
        
        table_name = tables.iloc[0]["name"]
        df = pd.read_sql_query(f"SELECT * FROM `{table_name}`", conn)
        conn.close()
        return df
    else:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file format. Supported: .csv, .sqlite, .sqlite3, .db, .s3db, .sl3",
        )

@app.delete("/session/{session_id}")
async def cleanup_session(session_id: str):
    """Clean up a specific session"""
    if session_id not in session_data:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    
    session_info = session_data[session_id]
    if os.path.exists(session_info["file_path"]):
        os.unlink(session_info["file_path"])
    del session_data[session_id]
    
    return {"message": f"Session {session_id} cleaned up successfully"}

@app.post("/cleanup-old-sessions")
async def cleanup_old_sessions(max_age_hours: int = None):
    """Clean up sessions older than specified hours"""
    if max_age_hours is None:
        max_age_hours = config["defaults"]["max_age_hours"]
    
    current_time = pd.Timestamp.now()
    sessions_to_remove = [
        sid for sid, info in session_data.items()
        if (current_time - info["created_at"]).total_seconds() / 3600 > max_age_hours
    ]
    
    cleaned_count = 0
    for session_id in sessions_to_remove:
        try:
            session_info = session_data[session_id]
            if os.path.exists(session_info["file_path"]):
                os.unlink(session_info["file_path"])
            del session_data[session_id]
            cleaned_count += 1
        except Exception:
            continue
    
    return {"message": f"Cleaned up {cleaned_count} old sessions"}

def _load_session_data(session_id: str) -> pd.DataFrame:
    """Load data from session storage"""
    if session_id not in session_data:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    
    file_path = session_data[session_id]["file_path"]
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"Session data file not found: {session_id}")
    
    try:
        return pd.read_parquet(file_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error loading session data: {str(e)}")

def _get_session_description(session_id: str) -> str:
    """Get description for a session"""
    if session_id not in session_data:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    return session_data[session_id]["description"]

@app.post("/execute-hypothesis-test")
async def execute_hypothesis_test(request: ExecuteTestRequest) -> ExecuteTestResponse:
    """Execute hypothesis test code and return results"""
    try:
        df = _load_session_data(request.session_id)
        code = _extract_python_code(request.analysis_code)
        success, p_value = _execute_test_code(code, df)
        
        return ExecuteTestResponse(success=success, p_value=p_value)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Code execution error: {str(e)}")

def _generate_description(df: pd.DataFrame) -> str:
    """Generate data description from DataFrame"""
    column_descriptions = []
    for col in df.columns:
        values = df[col].dropna()
        if values.empty:
            continue

        if pd.api.types.is_string_dtype(values):
            unique_count = values.nunique()
            top_values = values.value_counts().head(3)
            examples = ", ".join([f"{val} ({count})" for val, count in top_values.items()])
            desc = f"string. {unique_count} unique values. E.g. {examples}"
        elif pd.api.types.is_numeric_dtype(values):
            desc = f"numeric. mean: {values.mean():.2f} min: {values.min():.2f} max: {values.max():.2f}"
        elif pd.api.types.is_datetime64_any_dtype(values):
            desc = f"date. min: {values.min()} max: {values.max()}"
        else:
            desc = f"mixed type with {values.nunique()} unique values"

        column_descriptions.append(f"- {col}: {desc}")

    return (
        f"The Pandas DataFrame df has {len(df)} rows and {len(df.columns)} columns:\n"
        + "\n".join(column_descriptions)
    )



def _extract_python_code(text: str) -> str:
    """Extract Python code from markdown code blocks"""
    import re
    matches = re.findall(r"```python\n*(.*?)\n```", text, re.DOTALL)
    return matches[-1] if matches else ""

def _execute_test_code(code: str, df: pd.DataFrame) -> Tuple[bool, float]:
    """Execute hypothesis test code safely"""
    try:
        namespace = {"pd": pd, "stats": stats, "np": np, "df": df}
        exec(code, namespace)

        if "test_hypothesis" in namespace:
            result = namespace["test_hypothesis"](df)
            if isinstance(result, tuple) and len(result) == 2:
                return bool(result[0]), float(result[1])

        raise Exception("test_hypothesis function not found or invalid return format")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Code execution error: {str(e)}")

def open_browser():
    """Open browser after a short delay to ensure server is running"""
    import time
    time.sleep(1.5)
    webbrowser.open(f"http://localhost:{config['app']['port']}")

def main():
    import uvicorn
    
    browser_thread = threading.Thread(target=open_browser, daemon=True)
    browser_thread.start()
    
    uvicorn.run(app, host=config["app"]["host"], port=config["app"]["port"])

if __name__ == "__main__":
    main()
