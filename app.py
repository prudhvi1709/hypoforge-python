# /// script
# dependencies = [
#     "fastapi>=0.104.1",
#     "uvicorn[standard]>=0.24.0",
#     "python-multipart>=0.0.6",
#     "pandas>=2.1.3",
#     "scipy>=1.11.4",
#     "numpy>=1.26.0",
#     "aiohttp>=3.9.1",
# ]
# ///

from fastapi import FastAPI, UploadFile, HTTPException, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional, Tuple
import pandas as pd
import sqlite3
import json
import os
from io import StringIO
import asyncio
import aiohttp
from datetime import datetime
import numpy as np
import scipy.stats as stats

app = FastAPI(title="Hypothesis Forge", version="1.0.0")

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

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
    description: str
    analysis_prompt: str
    data: List[Dict[str, Any]]
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

@app.get("/")
async def root():
    """Serve the main HTML page"""
    return FileResponse("static/index.html")

@app.get("/config")
async def get_config():
    """Get configuration including demos"""
    with open("config.json", "r") as f:
        return json.load(f)

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """Handle file upload and return data description"""
    try:
        if file.filename.lower().endswith('.csv'):
            content = await file.read()
            df = pd.read_csv(StringIO(content.decode('utf-8')))
        elif file.filename.lower().endswith(('.sqlite', '.sqlite3', '.db', '.s3db', '.sl3')):
            content = await file.read()
            temp_db = f"temp_{file.filename}"
            with open(temp_db, 'wb') as f:
                f.write(content)
            
            conn = sqlite3.connect(temp_db)
            tables = pd.read_sql_query("SELECT name FROM sqlite_master WHERE type='table'", conn)
            if tables.empty:
                conn.close()
                os.remove(temp_db)
                raise HTTPException(status_code=400, detail="No tables found in database")
            
            table_name = tables.iloc[0]['name']
            df = pd.read_sql_query(f"SELECT * FROM `{table_name}`", conn)
            conn.close()
            os.remove(temp_db)
        else:
            raise HTTPException(status_code=400, detail="Unsupported file format")
        
        # Convert DataFrame to JSON-serializable format
        data = df.to_dict('records')
        description = _generate_description(df)
        
        return {"data": data, "description": description}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/generate-hypotheses")
async def generate_hypotheses(request: HypothesisRequest):
    """Generate hypotheses using LLM"""
    try:
        response = await _call_llm(
            request.system_prompt, 
            request.description, 
            request.api_base_url,
            request.api_key,
            request.model_name,
            use_schema=True
        )
        return {"hypotheses": response.get("hypotheses", [])}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/test-hypothesis")
async def test_hypothesis(request: TestRequest):
    """Test a hypothesis using Python code execution"""
    try:
        # Generate analysis code using LLM
        analysis_response = await _call_llm(
            request.analysis_prompt,
            f"Hypothesis: {request.hypothesis}\n\n{request.description}",
            request.api_base_url,
            request.api_key,
            request.model_name
        )
        
        # Extract Python code from response
        code = _extract_python_code(analysis_response)
        
        # Execute code with data
        df = pd.DataFrame(request.data)
        success, p_value = _execute_test_code(code, df)
        
        # Generate summary
        summary = await _generate_summary(
            request.hypothesis, 
            request.description, 
            success, 
            p_value,
            request.api_base_url,
            request.api_key,
            request.model_name
        )
        
        return TestResponse(
            success=success,
            p_value=p_value,
            analysis=analysis_response,
            summary=summary
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/synthesize")
async def synthesize_results(request: SynthesisRequest):
    """Synthesize hypothesis test results"""
    try:
        content = "\n\n".join([
            f"Hypothesis: {h['title']}\nBenefit: {h['benefit']}\nResult: {h['outcome']}"
            for h in request.hypotheses if h.get('outcome')
        ])
        
        system_prompt = """Given the below hypotheses and results, summarize the key takeaways and actions in Markdown.
Begin with the hypotheses with lowest p-values AND highest business impact. Ignore results with errors.
Use action titles has H5 (#####). Just reading titles should tell the audience EXACTLY what to do.
Below each, add supporting bullet points that
  - PROVE the action title, mentioning which hypotheses led to this conclusion.
  - Do not mention the p-value but _interpret_ it to support the action
  - Highlight key phrases in **bold**.
Finally, after a break (---) add a 1-paragraph executive summary section (H5) summarizing these actions."""
        
        response = await _call_llm(
            system_prompt, 
            content,
            request.api_base_url,
            request.api_key,
            request.model_name
        )
        return {"synthesis": response}
    
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
    
    return f"The Pandas DataFrame df has {len(df)} rows and {len(df.columns)} columns:\n" + "\n".join(column_descriptions)

async def _call_llm(system_prompt: str, user_content: str, api_base_url: str, api_key: str, model_name: str, use_schema: bool = False) -> str:
    """Call LLM API"""
    if not api_key:
        raise HTTPException(status_code=400, detail="API key is required")
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content}
    ]
    
    body = {
        "model": model_name,
        "messages": messages,
        "temperature": 0
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
                                    "benefit": {"type": "string"}
                                },
                                "required": ["hypothesis", "benefit"]
                            }
                        }
                    },
                    "required": ["hypotheses"]
                }
            }
        }
    
    api_url = f"{api_base_url}/chat/completions"
    
    async with aiohttp.ClientSession() as session:
        async with session.post(
            api_url,
            json=body,
            headers={"Authorization": f"Bearer {api_key}:hypoforge", "Content-Type": "application/json"}
        ) as response:
            if response.status != 200:
                error_text = await response.text()
                raise HTTPException(status_code=response.status, detail=f"LLM API error: {error_text}")
            
            result = await response.json()
            content = result["choices"][0]["message"]["content"]
            
            if use_schema:
                return json.loads(content)
            return content

def _extract_python_code(text: str) -> str:
    """Extract Python code from markdown code blocks"""
    import re
    matches = re.findall(r'```python\n*(.*?)\n```', text, re.DOTALL)
    return matches[-1] if matches else ""

def _execute_test_code(code: str, df: pd.DataFrame) -> Tuple[bool, float]:
    """Execute hypothesis test code safely"""
    try:
        # Create a safe execution environment
        namespace = {
            'pd': pd,
            'stats': stats,
            'np': np,
            'df': df
        }
        
        # Execute the code
        exec(code, namespace)
        
        # Call the test function
        if 'test_hypothesis' in namespace:
            result = namespace['test_hypothesis'](df)
            if isinstance(result, tuple) and len(result) == 2:
                return bool(result[0]), float(result[1])
        
        raise Exception("test_hypothesis function not found or invalid return format")
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Code execution error: {str(e)}")

async def _generate_summary(hypothesis: str, description: str, success: bool, p_value: float, api_base_url: str, api_key: str, model_name: str) -> str:
    """Generate plain English summary of test results"""
    system_prompt = """You are an expert data analyst.
Given a hypothesis and its outcome, provide a plain English summary of the findings as a crisp H5 heading (#####), followed by 1-2 concise supporting sentences.
Highlight in **bold** the keywords in the supporting statements.
Do not mention the p-value but _interpret_ it to support the conclusion quantitatively."""
    
    user_content = f"Hypothesis: {hypothesis}\n\n{description}\n\nResult: {success}. p-value: {p_value:.6f}"
    
    return await _call_llm(system_prompt, user_content, api_base_url, api_key, model_name)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)