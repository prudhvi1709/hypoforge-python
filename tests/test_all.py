# /// script
# dependencies = [
#     "pytest>=7.4.0",
#     "pytest-asyncio>=0.21.0",
#     "fastapi>=0.104.1",
#     "pandas>=2.1.3",
#     "scipy>=1.11.4",
#     "numpy>=1.26.0",
#     "httpx>=0.27.0",
#     "pyarrow>=15.0.0",
# ]
# ///

"""
Comprehensive test suite for HypoForge API.

This single file contains all tests organized into categories:
- TestAPIEndpoints: Tests for all REST API endpoints
- TestUtilityFunctions: Tests for utility and helper functions  
- TestIntegration: End-to-end workflow tests
- TestPerformance: Performance and stress tests

Run with: uv run pytest tests/test_all.py
"""

# Guard clause to prevent direct execution
if __name__ == "__main__":
    print("❌ This test file should not be run directly!")
    print("✅ Use instead: uv run pytest tests/test_all.py")
    print("✅ Or simply: make uv-test")
    exit(1)

import pytest
import json
import tempfile
import os
import pandas as pd
import sqlite3
from unittest.mock import patch, mock_open
from fastapi import HTTPException

from app import (
    app, session_data, TEMP_DIR,
    _generate_description, _extract_python_code, _execute_test_code,
    _load_file_data, _create_session, _load_session_data
)


# =============================================================================
# API ENDPOINT TESTS
# =============================================================================

class TestAPIEndpoints:
    """Tests for all API endpoints"""
    
    def test_config_endpoint(self, client):
        """Test /config endpoint"""
        mock_config = {
            "demos": [{
                "title": "Test Demo",
                "href": "https://example.com/test.csv",
                "audience": "Test audience",
                "body": "Test description"
            }]
        }
        
        with patch('builtins.open', mock_open(read_data=json.dumps(mock_config))):
            response = client.get("/config")
            assert response.status_code == 200
            assert response.json() == mock_config
    
    def test_root_endpoint(self, client):
        """Test root endpoint returns HTML file"""
        response = client.get("/")
        assert response.status_code == 200
    
    def test_load_csv_data(self, client, sample_csv_file):
        """Test CSV data loading"""
        response = client.post("/load-data", json={"source": sample_csv_file})
        
        assert response.status_code == 200
        data = response.json()
        assert "session_id" in data
        assert data["row_count"] == 5
        assert data["column_count"] == 4
        assert "DataFrame df has 5 rows and 4 columns" in data["description"]
    
    def test_load_sqlite_data(self, client, sample_sqlite_file):
        """Test SQLite data loading"""
        response = client.post("/load-data", json={"source": sample_sqlite_file})
        
        assert response.status_code == 200
        data = response.json()
        assert "session_id" in data
        assert data["row_count"] == 5
        assert data["column_count"] == 5  # Including ID column
    
    def test_load_data_errors(self, client, tmp_path):
        """Test data loading error cases"""
        # Test non-existent file
        response = client.post("/load-data", json={"source": "/non/existent/file.csv"})
        assert response.status_code == 500
        assert "Error loading data" in response.json()["detail"] or "File not found" in response.json()["detail"]
        
        # Test unsupported file format
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("This is a text file")
        response = client.post("/load-data", json={"source": str(txt_file)})
        assert response.status_code == 500
    
    @patch('httpx.AsyncClient')
    def test_load_url_data(self, mock_httpx, client, sample_csv_data):
        """Test loading data from URL"""
        mock_response = mock_httpx.return_value.__aenter__.return_value.get.return_value
        mock_response.status_code = 200
        mock_response.content = sample_csv_data.encode()
        
        response = client.post("/load-data", json={"source": "https://example.com/test.csv"})
        
        assert response.status_code == 200
        data = response.json()
        assert "session_id" in data
        assert data["row_count"] == 5
    
    def test_session_cleanup(self, client, sample_csv_file):
        """Test session management"""
        # Create session
        response = client.post("/load-data", json={"source": sample_csv_file})
        assert response.status_code == 200
        session_id = response.json()["session_id"]
        
        # Clean up session
        response = client.delete(f"/session/{session_id}")
        assert response.status_code == 200
        assert session_id not in session_data
        
        # Test cleanup non-existent session
        response = client.delete("/session/nonexistent-session-id")
        assert response.status_code == 404
    
    def test_hypothesis_execution(self, client, sample_csv_file, hypothesis_test_code):
        """Test hypothesis test execution"""
        # Create session
        response = client.post("/load-data", json={"source": sample_csv_file})
        assert response.status_code == 200
        session_id = response.json()["session_id"]
        
        # Execute hypothesis test
        response = client.post("/execute-hypothesis-test", json={
            "session_id": session_id,
            "analysis_code": hypothesis_test_code
        })
        
        assert response.status_code == 200
        data = response.json()
        assert "success" in data
        assert "p_value" in data
        assert isinstance(data["success"], bool)
        assert isinstance(data["p_value"], float)
    
    def test_hypothesis_execution_errors(self, client, sample_csv_file):
        """Test hypothesis test execution error cases"""
        # Create session
        response = client.post("/load-data", json={"source": sample_csv_file})
        session_id = response.json()["session_id"]
        
        # Test invalid session
        response = client.post("/execute-hypothesis-test", json={
            "session_id": "invalid-session-id",
            "analysis_code": "```python\ndef test_hypothesis(df): return True, 0.05\n```"
        })
        assert response.status_code == 500
        
        # Test invalid code
        invalid_code = "```python\ndef invalid_function(): return 'not a test'\n```"
        response = client.post("/execute-hypothesis-test", json={
            "session_id": session_id,
            "analysis_code": invalid_code
        })
        assert response.status_code == 500


# =============================================================================
# UTILITY FUNCTION TESTS
# =============================================================================

class TestUtilityFunctions:
    """Tests for utility functions"""
    
    def test_data_loading_functions(self, sample_csv_file, sample_sqlite_file):
        """Test data loading utility functions"""
        import asyncio
        
        # Test CSV loading
        df_csv = asyncio.run(_load_file_data(sample_csv_file))
        assert len(df_csv) == 5
        assert len(df_csv.columns) == 4
        assert list(df_csv.columns) == ['name', 'age', 'salary', 'department']
        
        # Test SQLite loading
        df_sqlite = asyncio.run(_load_file_data(sample_sqlite_file))
        assert len(df_sqlite) == 5
        assert len(df_sqlite.columns) == 5  # Including ID
        assert 'name' in df_sqlite.columns
    
    def test_session_management_functions(self, sample_dataframe):
        """Test session management utility functions"""
        import asyncio
        
        # Test session creation
        response = asyncio.run(_create_session(sample_dataframe, "test_file.csv"))
        assert hasattr(response, 'session_id')
        assert response.row_count == 5
        assert response.column_count == 4
        assert response.session_id in session_data
        
        # Test session data loading
        session_id = response.session_id
        loaded_df = _load_session_data(session_id)
        assert len(loaded_df) == 5
        assert list(loaded_df.columns) == ['name', 'age', 'salary', 'department']
    
    def test_description_generation(self, sample_dataframe):
        """Test data description generation"""
        description = _generate_description(sample_dataframe)
        
        assert "DataFrame df has 5 rows and 4 columns" in description
        assert "name: string" in description
        assert "age: numeric" in description
        assert "salary: numeric" in description
        assert "department: string" in description
        assert "mean:" in description  # Should contain numeric stats
        assert "unique values" in description  # Should contain string stats
    
    def test_description_generation_data_types(self):
        """Test description generation for different data types"""
        # Test numeric data
        df_numeric = pd.DataFrame({
            'values': [1, 2, 3, 4, 5],
            'scores': [10.5, 20.3, 15.7, 30.1, 25.9]
        })
        description = _generate_description(df_numeric)
        assert "values: numeric" in description
        assert "mean:" in description
        assert "min:" in description
        assert "max:" in description
        
        # Test datetime data
        df_datetime = pd.DataFrame({
            'dates': pd.date_range('2023-01-01', periods=3),
        })
        description = _generate_description(df_datetime)
        assert "dates: date" in description
        assert "min: 2023-01-01" in description
    
    def test_code_extraction(self):
        """Test Python code extraction from markdown"""
        # Test single code block
        text_single = """
Here is some Python code:

```python
def hello():
    return "Hello World"
```

End of text.
"""
        code = _extract_python_code(text_single)
        expected = "def hello():\n    return \"Hello World\""
        assert code.strip() == expected.strip()
        
        # Test multiple code blocks (should get last one)
        text_multiple = """
First block:
```python
def first():
    return 1
```

Second block:
```python
def second():
    return 2
```
"""
        code = _extract_python_code(text_multiple)
        expected = "def second():\n    return 2"
        assert code.strip() == expected.strip()
        
        # Test no code blocks
        text_none = "This is just plain text with no code blocks."
        code = _extract_python_code(text_none)
        assert code == ""
    
    def test_code_execution(self, sample_dataframe):
        """Test hypothesis test code execution"""
        # Test successful execution
        code_success = """
def test_hypothesis(df):
    mean_age = df['age'].mean()
    p_value = 0.05 if mean_age > 25 else 0.10
    return mean_age > 25, p_value
"""
        success, p_value = _execute_test_code(code_success, sample_dataframe)
        assert isinstance(success, bool)
        assert isinstance(p_value, float)
        assert success is True  # Mean age in sample data is > 25
        
        # Test execution with scipy.stats
        code_stats = """
def test_hypothesis(df):
    import scipy.stats as stats
    engineering = df[df['department'] == 'Engineering']['salary']
    marketing = df[df['department'] == 'Marketing']['salary']
    
    if len(engineering) > 0 and len(marketing) > 0:
        t_stat, p_value = stats.ttest_ind(engineering, marketing)
        return p_value < 0.05, p_value
    else:
        return False, 1.0
"""
        success, p_value = _execute_test_code(code_stats, sample_dataframe)
        assert isinstance(success, bool)
        assert isinstance(p_value, float)
        assert 0 <= p_value <= 1


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

@pytest.mark.integration
class TestIntegration:
    """Integration tests for complete workflows"""
    
    def test_complete_csv_workflow(self, client, sample_csv_file, hypothesis_test_code):
        """Test complete workflow: CSV loading → session creation → hypothesis testing"""
        # Step 1: Load CSV data
        response = client.post("/load-data", json={"source": sample_csv_file})
        assert response.status_code == 200
        
        data = response.json()
        session_id = data["session_id"]
        assert data["row_count"] == 5
        assert data["column_count"] == 4
        
        # Step 2: Execute hypothesis test
        response = client.post("/execute-hypothesis-test", json={
            "session_id": session_id,
            "analysis_code": hypothesis_test_code
        })
        assert response.status_code == 200
        
        test_result = response.json()
        assert "success" in test_result
        assert "p_value" in test_result
        
        # Step 3: Clean up session
        response = client.delete(f"/session/{session_id}")
        assert response.status_code == 200
    
    def test_complete_sqlite_workflow(self, client, sample_sqlite_file):
        """Test complete workflow with SQLite database"""
        # Step 1: Load SQLite data
        response = client.post("/load-data", json={"source": sample_sqlite_file})
        assert response.status_code == 200
        
        data = response.json()
        session_id = data["session_id"]
        assert data["row_count"] == 5
        
        # Step 2: Execute a simple hypothesis test
        hypothesis_code = """```python
def test_hypothesis(df):
    mean_salary = df['salary'].mean()
    return mean_salary > 55000, 0.05 if mean_salary > 55000 else 0.10
```"""
        
        response = client.post("/execute-hypothesis-test", json={
            "session_id": session_id,
            "analysis_code": hypothesis_code
        })
        assert response.status_code == 200
        
        test_result = response.json()
        assert test_result["success"] is True  # Mean salary is 60000
        
        # Step 3: Clean up
        response = client.delete(f"/session/{session_id}")
        assert response.status_code == 200
    
    @patch('httpx.AsyncClient')
    def test_url_workflow(self, mock_httpx, client, sample_csv_data):
        """Test complete workflow with URL data source"""
        # Mock HTTP response
        mock_response = mock_httpx.return_value.__aenter__.return_value.get.return_value
        mock_response.status_code = 200
        mock_response.content = sample_csv_data.encode()
        
        # Step 1: Load data from URL
        response = client.post("/load-data", json={
            "source": "https://example.com/test.csv"
        })
        assert response.status_code == 200
        
        session_id = response.json()["session_id"]
        
        # Step 2: Execute hypothesis test
        hypothesis_code = """```python
def test_hypothesis(df):
    unique_depts = df['department'].nunique()
    return unique_depts > 3, 0.05 if unique_depts > 3 else 0.10
```"""
        
        response = client.post("/execute-hypothesis-test", json={
            "session_id": session_id,
            "analysis_code": hypothesis_code
        })
        assert response.status_code == 200
        
        test_result = response.json()
        assert test_result["success"] is False  # Only 3 unique departments
        
        # Step 3: Clean up
        response = client.delete(f"/session/{session_id}")
        assert response.status_code == 200
    
    def test_error_recovery_workflow(self, client, sample_csv_file):
        """Test workflow with error recovery"""
        # Step 1: Create session
        response = client.post("/load-data", json={"source": sample_csv_file})
        assert response.status_code == 200
        session_id = response.json()["session_id"]
        
        # Step 2: Try invalid hypothesis test
        invalid_code = """```python
def test_hypothesis(df):
    return df['nonexistent_column'].mean()
```"""
        
        response = client.post("/execute-hypothesis-test", json={
            "session_id": session_id,
            "analysis_code": invalid_code
        })
        assert response.status_code == 500
        
        # Step 3: Try valid hypothesis test on same session
        valid_code = """```python
def test_hypothesis(df):
    return True, 0.05
```"""
        
        response = client.post("/execute-hypothesis-test", json={
            "session_id": session_id,
            "analysis_code": valid_code
        })
        assert response.status_code == 200
        assert response.json()["success"] is True
        
        # Step 4: Clean up
        response = client.delete(f"/session/{session_id}")
        assert response.status_code == 200
    
    def test_large_dataset_workflow(self, client, tmp_path):
        """Test workflow with larger dataset"""
        # Create a larger CSV file
        large_data = []
        for i in range(100):  # Reduced from 1000 for faster testing
            large_data.append(f"Person{i},{20 + (i % 40)},{30000 + (i * 10)},Dept{i % 5}")
        
        csv_content = "name,age,salary,department\n" + "\n".join(large_data)
        large_csv = tmp_path / "large_data.csv"
        large_csv.write_text(csv_content)
        
        # Load and test
        response = client.post("/load-data", json={"source": str(large_csv)})
        assert response.status_code == 200
        
        data = response.json()
        assert data["row_count"] == 100
        assert data["column_count"] == 4
        
        # Execute hypothesis test
        hypothesis_code = """```python
def test_hypothesis(df):
    import scipy.stats as stats
    correlation, p_value = stats.pearsonr(df['age'], df['salary'])
    return abs(correlation) > 0.5, p_value
```"""
        
        response = client.post("/execute-hypothesis-test", json={
            "session_id": data["session_id"],
            "analysis_code": hypothesis_code
        })
        assert response.status_code == 200


# =============================================================================
# PERFORMANCE TESTS
# =============================================================================

@pytest.mark.slow
class TestPerformance:
    """Performance and stress tests"""
    
    def test_multiple_sessions(self, client, sample_csv_file):
        """Test multiple session management"""
        session_ids = []
        
        # Create multiple sessions
        for i in range(5):  # Reduced from 10 for faster testing
            response = client.post("/load-data", json={"source": sample_csv_file})
            assert response.status_code == 200
            session_ids.append(response.json()["session_id"])
        
        # Verify all sessions exist and are unique
        assert len(set(session_ids)) == 5
        
        # Clean up all sessions
        response = client.post("/cleanup-old-sessions?max_age_hours=0")
        assert response.status_code == 200
        assert "Cleaned up 5 old sessions" in response.json()["message"]
    
    def test_concurrent_hypothesis_execution(self, client, sample_csv_file):
        """Test multiple hypothesis tests on same session"""
        # Create session
        response = client.post("/load-data", json={"source": sample_csv_file})
        assert response.status_code == 200
        session_id = response.json()["session_id"]
        
        # Execute multiple different tests
        test_codes = [
            "```python\ndef test_hypothesis(df): return df['age'].mean() > 25, 0.05\n```",
            "```python\ndef test_hypothesis(df): return df['salary'].std() > 1000, 0.05\n```",
            "```python\ndef test_hypothesis(df): return len(df) == 5, 0.05\n```"
        ]
        
        for code in test_codes:
            response = client.post("/execute-hypothesis-test", json={
                "session_id": session_id,
                "analysis_code": code
            })
            assert response.status_code == 200
        
        # Clean up
        response = client.delete(f"/session/{session_id}")
        assert response.status_code == 200 