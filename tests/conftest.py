# /// script
# dependencies = [
#     "pytest>=7.4.0",
#     "pytest-asyncio>=0.21.0",
#     "fastapi>=0.104.1",
#     "pandas>=2.1.3",
#     "httpx>=0.27.0",
# ]
# ///

import pytest
import tempfile
import os
import pandas as pd
import sqlite3
from pathlib import Path
from fastapi.testclient import TestClient
from unittest.mock import patch

# Import the app
from app import app, session_data, TEMP_DIR


@pytest.fixture
def client():
    """Create a test client for the FastAPI app"""
    return TestClient(app)


@pytest.fixture
def sample_csv_data():
    """Sample CSV data for testing"""
    return """name,age,salary,department
John,25,50000,Engineering
Jane,30,60000,Marketing
Bob,35,70000,Engineering
Alice,28,55000,Sales
Charlie,32,65000,Marketing"""


@pytest.fixture
def sample_csv_file(tmp_path, sample_csv_data):
    """Create a temporary CSV file for testing"""
    csv_file = tmp_path / "test_data.csv"
    csv_file.write_text(sample_csv_data)
    return str(csv_file)


@pytest.fixture
def sample_sqlite_file(tmp_path):
    """Create a temporary SQLite file for testing"""
    db_file = tmp_path / "test_data.db"
    conn = sqlite3.connect(str(db_file))
    
    # Create a test table
    conn.execute("""
        CREATE TABLE employees (
            id INTEGER PRIMARY KEY,
            name TEXT,
            age INTEGER,
            salary REAL,
            department TEXT
        )
    """)
    
    # Insert test data
    test_data = [
        (1, "John", 25, 50000.0, "Engineering"),
        (2, "Jane", 30, 60000.0, "Marketing"),
        (3, "Bob", 35, 70000.0, "Engineering"),
        (4, "Alice", 28, 55000.0, "Sales"),
        (5, "Charlie", 32, 65000.0, "Marketing")
    ]
    
    conn.executemany(
        "INSERT INTO employees (id, name, age, salary, department) VALUES (?, ?, ?, ?, ?)",
        test_data
    )
    conn.commit()
    conn.close()
    
    return str(db_file)


@pytest.fixture
def sample_dataframe():
    """Create a sample pandas DataFrame for testing"""
    return pd.DataFrame({
        'name': ['John', 'Jane', 'Bob', 'Alice', 'Charlie'],
        'age': [25, 30, 35, 28, 32],
        'salary': [50000, 60000, 70000, 55000, 65000],
        'department': ['Engineering', 'Marketing', 'Engineering', 'Sales', 'Marketing']
    })


@pytest.fixture(autouse=True)
def clean_session_data():
    """Clean up session data before and after each test"""
    # Clean up before test
    session_data.clear()
    
    # Clean up temp files
    if TEMP_DIR.exists():
        for file in TEMP_DIR.glob("*.parquet"):
            try:
                file.unlink()
            except FileNotFoundError:
                pass
    
    yield
    
    # Clean up after test
    session_data.clear()
    if TEMP_DIR.exists():
        for file in TEMP_DIR.glob("*.parquet"):
            try:
                file.unlink()
            except FileNotFoundError:
                pass


@pytest.fixture
def mock_config():
    """Mock configuration for testing"""
    return {
        "app": {
            "title": "HypoForge Test",
            "version": "1.0.0",
            "host": "0.0.0.0",
            "port": 8000
        },
        "defaults": {
            "max_age_hours": 24
        }
    }


@pytest.fixture
def hypothesis_test_code():
    """Sample hypothesis test code for testing"""
    return """```python
import pandas as pd
import scipy.stats as stats

def test_hypothesis(df):
    # Test if mean salary differs between departments
    engineering = df[df['department'] == 'Engineering']['salary']
    marketing = df[df['department'] == 'Marketing']['salary']
    
    if len(engineering) > 0 and len(marketing) > 0:
        t_stat, p_value = stats.ttest_ind(engineering, marketing)
        return p_value < 0.05, p_value
    else:
        return False, 1.0
```"""


@pytest.fixture
def invalid_hypothesis_test_code():
    """Invalid hypothesis test code for testing error handling"""
    return """```python
def invalid_function():
    return "This is not a valid test"
```""" 