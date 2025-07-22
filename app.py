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
# ]
# ///

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Tuple, Optional
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
import shutil
from pathlib import Path

app = FastAPI(title="Hypothesis Forge", version="1.0.0")

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Session storage for data files
TEMP_DIR = Path(tempfile.gettempdir()) / "hypoforge_sessions"
TEMP_DIR.mkdir(exist_ok=True)
session_data = {}  # In-memory storage for session metadata

# Models
class HypothesisRequest(BaseModel):
    system_prompt: str
    description: str
    api_base_url: str
    api_key: str
    model_name: str


class HypothesisResponse(BaseModel):
    hypotheses: List[Dict[str, str]]


class TestRequest(BaseModel):
    hypothesis: str
    session_id: str
    analysis_prompt: str
    api_base_url: str
    api_key: str
    model_name: str


class TestResponse(BaseModel):
    success: bool
    p_value: float
    analysis: str
    summary: str


class SynthesisRequest(BaseModel):
    hypotheses: List[Dict[str, str]]
    api_base_url: str
    api_key: str
    model_name: str


class LoadFileRequest(BaseModel):
    file_path: str


class LoadDemoRequest(BaseModel):
    demo_url: str


class DataSessionResponse(BaseModel):
    session_id: str
    description: str
    row_count: int
    column_count: int


@app.get("/")
async def root():
    """Serve the main HTML page"""
    return FileResponse("static/index.html")


@app.get("/config")
async def get_config():
    """Get configuration including demos"""
    with open("config.json", "r") as f:
        return json.load(f)


@app.post("/load-file")
async def load_file(request: LoadFileRequest) -> DataSessionResponse:
    """Load file from filesystem path, save to temporary storage, and return session ID"""
    try:
        file_path = request.file_path.strip()

        # Security: Basic path validation
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail=f"File not found: {file_path}")

        if not os.path.isfile(file_path):
            raise HTTPException(status_code=400, detail=f"Path is not a file: {file_path}")

        df = await _load_file_data(file_path)
        
        # Generate session ID and save data
        session_id = str(uuid.uuid4())
        session_file_path = TEMP_DIR / f"{session_id}.parquet"
        
        # Save DataFrame to parquet for efficient storage and loading
        df.to_parquet(session_file_path, index=False)
        
        # Generate description
        description = _generate_description(df)
        
        # Store session metadata
        session_data[session_id] = {
            "file_path": str(session_file_path),
            "description": description,
            "original_path": file_path,
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

    except pd.errors.EmptyDataError:
        raise HTTPException(status_code=400, detail="The file is empty or contains no valid data")
    except pd.errors.ParserError as e:
        raise HTTPException(status_code=400, detail=f"Error parsing file: {str(e)}")
    except PermissionError:
        raise HTTPException(
            status_code=403, detail=f"Permission denied accessing file: {file_path}"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error loading file: {str(e)}")


@app.post("/load-demo")
async def load_demo(request: LoadDemoRequest) -> DataSessionResponse:
    """Load demo file from URL, save to temporary storage, and return session ID"""
    try:
        demo_url = request.demo_url.strip()

        # Download file to temporary location
        async with httpx.AsyncClient() as client:
            response = await client.get(demo_url)
            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to download demo file: {demo_url}",
                )

            # Create temporary file with correct extension
            file_extension = demo_url.split(".")[-1].lower()
            with tempfile.NamedTemporaryFile(
                suffix=f".{file_extension}", delete=False
            ) as tmp_file:
                tmp_file.write(response.content)
                temp_path = tmp_file.name

        try:
            df = await _load_file_data(temp_path)
            
            # Generate session ID and save data
            session_id = str(uuid.uuid4())
            session_file_path = TEMP_DIR / f"{session_id}.parquet"
            
            # Save DataFrame to parquet for efficient storage and loading
            df.to_parquet(session_file_path, index=False)
            
            # Generate description
            description = _generate_description(df)
            
            # Store session metadata
            session_data[session_id] = {
                "file_path": str(session_file_path),
                "description": description,
                "original_path": demo_url,
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
            
        finally:
            # Clean up temporary download file
            os.unlink(temp_path)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error loading demo: {str(e)}")


async def _load_file_data(file_path: str) -> pd.DataFrame:
    """Load data from file path into DataFrame"""
    # Load based on file extension
    if file_path.lower().endswith(".csv"):
        df = pd.read_csv(file_path)
    elif file_path.lower().endswith((".sqlite", ".sqlite3", ".db", ".s3db", ".sl3")):
        conn = sqlite3.connect(file_path)
        tables = pd.read_sql_query("SELECT name FROM sqlite_master WHERE type='table'", conn)
        if tables.empty:
            conn.close()
            raise HTTPException(status_code=400, detail="No tables found in database")

        table_name = tables.iloc[0]["name"]
        df = pd.read_sql_query(f"SELECT * FROM `{table_name}`", conn)
        conn.close()
    else:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file format. Supported: .csv, .sqlite, .sqlite3, .db, .s3db, .sl3",
        )

    return df


@app.delete("/session/{session_id}")
async def cleanup_session(session_id: str):
    """Clean up a specific session"""
    if session_id not in session_data:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    
    session_info = session_data[session_id]
    file_path = session_info["file_path"]
    
    # Remove file if it exists
    if os.path.exists(file_path):
        os.unlink(file_path)
    
    # Remove from session data
    del session_data[session_id]
    
    return {"message": f"Session {session_id} cleaned up successfully"}


@app.post("/cleanup-old-sessions")
async def cleanup_old_sessions(max_age_hours: int = 24):
    """Clean up sessions older than specified hours"""
    current_time = pd.Timestamp.now()
    sessions_to_remove = []
    
    for session_id, session_info in session_data.items():
        age_hours = (current_time - session_info["created_at"]).total_seconds() / 3600
        if age_hours > max_age_hours:
            sessions_to_remove.append(session_id)
    
    cleaned_count = 0
    for session_id in sessions_to_remove:
        try:
            session_info = session_data[session_id]
            file_path = session_info["file_path"]
            
            # Remove file if it exists
            if os.path.exists(file_path):
                os.unlink(file_path)
            
            # Remove from session data
            del session_data[session_id]
            cleaned_count += 1
        except Exception:
            continue  # Skip errors and continue cleanup
    
    return {"message": f"Cleaned up {cleaned_count} old sessions"}


def _load_session_data(session_id: str) -> pd.DataFrame:
    """Load data from session storage"""
    if session_id not in session_data:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    
    session_info = session_data[session_id]
    file_path = session_info["file_path"]
    
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


@app.post("/generate-hypotheses")
async def generate_hypotheses(request: HypothesisRequest):
    """Generate hypotheses using LLM with streaming"""
    try:

        async def generate():
            async for content in _call_llm_stream(
                request.system_prompt,
                request.description,
                request.api_base_url,
                request.api_key,
                request.model_name,
                use_schema=True,
            ):
                yield f"data: {json.dumps({'content': content})}\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/test-hypothesis")
async def test_hypothesis(request: TestRequest):
    """Test a hypothesis using Python code execution with streaming"""
    try:
        # Load data from session storage
        df = _load_session_data(request.session_id)
        description = _get_session_description(request.session_id)

        async def generate():
            # Stream analysis generation
            full_analysis = ""
            async for content in _call_llm_stream(
                request.analysis_prompt,
                f"Hypothesis: {request.hypothesis}\n\n{description}",
                request.api_base_url,
                request.api_key,
                request.model_name,
            ):
                full_analysis = content
                yield f"data: {json.dumps({'type': 'analysis', 'content': content})}\n\n"

            # Extract and execute code
            code = _extract_python_code(full_analysis)
            success, p_value = _execute_test_code(code, df)

            # Stream summary generation
            async for content in _call_llm_stream(
                "You are an expert data analyst.\nGiven a hypothesis and its outcome, provide a plain English summary of the findings as a crisp H5 heading (#####), followed by 1-2 concise supporting sentences.\nHighlight in **bold** the keywords in the supporting statements.\nDo not mention the p-value but _interpret_ it to support the conclusion quantitatively.",
                f"Hypothesis: {request.hypothesis}\n\n{description}\n\nResult: {success}. p-value: {p_value:.6f}",
                request.api_base_url,
                request.api_key,
                request.model_name,
            ):
                yield f"data: {json.dumps({'type': 'summary', 'content': content, 'success': success, 'p_value': p_value})}\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/synthesize")
async def synthesize_results(request: SynthesisRequest):
    """Synthesize hypothesis test results with streaming"""
    try:
        user_content = "\n\n".join(
            [
                f"Hypothesis: {h['title']}\nBenefit: {h['benefit']}\nResult: {h['outcome']}"
                for h in request.hypotheses
                if h.get("outcome")
            ]
        )

        system_prompt = """Given the below hypotheses and results, summarize the key takeaways and actions in Markdown.
Begin with the hypotheses with lowest p-values AND highest business impact. Ignore results with errors.
Use action titles has H5 (#####). Just reading titles should tell the audience EXACTLY what to do.
Below each, add supporting bullet points that
  - PROVE the action title, mentioning which hypotheses led to this conclusion.
  - Do not mention the p-value but _interpret_ it to support the action
  - Highlight key phrases in **bold**.
Finally, after a break (---) add a 1-paragraph executive summary section (H5) summarizing these actions."""

        async def generate():
            async for content in _call_llm_stream(
                system_prompt,
                user_content,
                request.api_base_url,
                request.api_key,
                request.model_name,
            ):
                yield f"data: {json.dumps({'content': content})}\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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


async def _call_llm_stream(
    system_prompt: str,
    user_content: str,
    api_base_url: str,
    api_key: str,
    model_name: str,
    use_schema: bool = False,
):
    """Call LLM API with streaming support"""
    if not api_key:
        raise HTTPException(status_code=400, detail="API key is required")

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    body = {
        "model": model_name,
        "messages": messages,
        "stream": True,
        "stream_options": {"include_usage": True},
        "temperature": 0,
    }

    if use_schema:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "HypothesesResponse",
                "schema": {
                    "type": "object",
                    "properties": {
                        "hypotheses": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "hypothesis": {"type": "string"},
                                    "benefit": {"type": "string"},
                                },
                                "required": ["hypothesis", "benefit"],
                            },
                        }
                    },
                    "required": ["hypotheses"],
                },
            },
        }

    api_url = f"{api_base_url}/chat/completions"

    async with httpx.AsyncClient() as client:
        async with client.stream(
            "POST",
            api_url,
            json=body,
            headers={
                "Authorization": f"Bearer {api_key}:hypoforge",
                "Content-Type": "application/json",
            },
        ) as response:
            if response.status_code != 200:
                error_text = await response.aread()
                raise HTTPException(
                    status_code=response.status_code, detail=f"LLM API error: {error_text.decode()}"
                )

            full_content = ""
            async for line in response.aiter_lines():
                if line:
                    line_str = line.strip()
                    if line_str.startswith("data: "):
                        data_str = line_str[6:]
                        if data_str and data_str != "[DONE]":
                            try:
                                chunk = json.loads(data_str)
                                choices = chunk.get("choices", [])
                                if choices and len(choices) > 0:
                                    delta = choices[0].get("delta", {})
                                    if delta.get("content"):
                                        content = delta["content"]
                                        full_content += content
                                        yield full_content
                            except json.JSONDecodeError:
                                continue


async def _call_llm(
    system_prompt: str,
    user_content: str,
    api_base_url: str,
    api_key: str,
    model_name: str,
    use_schema: bool = False,
) -> str:
    """Call LLM API"""
    if not api_key:
        raise HTTPException(status_code=400, detail="API key is required")

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    body = {"model": model_name, "messages": messages, "temperature": 0}

    if use_schema:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "HypothesesResponse",
                "schema": {
                    "type": "object",
                    "properties": {
                        "hypotheses": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "hypothesis": {"type": "string"},
                                    "benefit": {"type": "string"},
                                },
                                "required": ["hypothesis", "benefit"],
                            },
                        }
                    },
                    "required": ["hypotheses"],
                },
            },
        }

    api_url = f"{api_base_url}/chat/completions"

    async with httpx.AsyncClient() as client:
        response = await client.post(
            api_url,
            json=body,
            headers={
                "Authorization": f"Bearer {api_key}:hypoforge",
                "Content-Type": "application/json",
            },
        )
        if response.status_code != 200:
            error_text = response.text
            raise HTTPException(
                status_code=response.status_code, detail=f"LLM API error: {error_text}"
            )

        result = response.json()
        content = result["choices"][0]["message"]["content"]

        if use_schema:
            return json.loads(content)
        return content


def _extract_python_code(text: str) -> str:
    """Extract Python code from markdown code blocks"""
    import re

    matches = re.findall(r"```python\n*(.*?)\n```", text, re.DOTALL)
    return matches[-1] if matches else ""


def _execute_test_code(code: str, df: pd.DataFrame) -> Tuple[bool, float]:
    """Execute hypothesis test code safely"""
    try:
        # Create a safe execution environment
        namespace = {"pd": pd, "stats": stats, "np": np, "df": df}

        # Execute the code
        exec(code, namespace)

        # Call the test function
        if "test_hypothesis" in namespace:
            result = namespace["test_hypothesis"](df)
            if isinstance(result, tuple) and len(result) == 2:
                return bool(result[0]), float(result[1])

        raise Exception("test_hypothesis function not found or invalid return format")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Code execution error: {str(e)}")


async def _generate_summary(
    hypothesis: str,
    description: str,
    success: bool,
    p_value: float,
    api_base_url: str,
    api_key: str,
    model_name: str,
) -> str:
    """Generate plain English summary of test results"""
    system_prompt = """You are an expert data analyst.
Given a hypothesis and its outcome, provide a plain English summary of the findings as a crisp H5 heading (#####), followed by 1-2 concise supporting sentences.
Highlight in **bold** the keywords in the supporting statements.
Do not mention the p-value but _interpret_ it to support the conclusion quantitatively."""

    user_content = (
        f"Hypothesis: {hypothesis}\n\n{description}\n\nResult: {success}. p-value: {p_value:.6f}"
    )

    return await _call_llm(system_prompt, user_content, api_base_url, api_key, model_name)


def open_browser():
    """Open browser after a short delay to ensure server is running"""
    import time
    time.sleep(1.5)  # Wait for server to start
    webbrowser.open("http://localhost:8000")


def main():
    import uvicorn
    
    # Start browser opening in background thread
    browser_thread = threading.Thread(target=open_browser, daemon=True)
    browser_thread.start()
    
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
