"""
Integration tests for PatientDB workflows.
"""

import os
import tempfile
from datetime import datetime

import pytest

from src.database.patient import PatientDB
from src.hl7.parser import PatientInfo, CreatinineResult


@pytest.fixture
def temp_db_path():
    """Create a temporary database path for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield os.path.join(tmpdir, "test_patient.db")


@pytest.fixture
def db(temp_db_path):
    """Create a PatientDB instance with a temporary database."""
    patient_db = PatientDB(db_path=temp_db_path)
    yield patient_db
    patient_db.close()


@pytest.fixture
def temp_csv_file():
    """Create a temporary CSV file with sample patient data."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write("mrn,creatinine_date_0,creatinine_result_0,creatinine_date_1,creatinine_result_1\n")
        f.write("100000001,2024-01-01 10:00:00,85.5,2024-01-02 11:00:00,90.2\n")
        f.write("100000002,2024-01-03 09:00:00,120.0,,\n")
        f.write("100000003,2024-01-04 14:30:00,75.3,2024-01-05 08:00:00,78.1\n")
        f.write(",2024-01-06 10:00:00,100.0,,\n")
        csv_path = f.name

    yield csv_path

    os.unlink(csv_path)


class TestIntegration:
    """Integration tests combining multiple operations."""

    def test_full_workflow(self, db, temp_csv_file):
        """Test complete workflow: load CSV, add HL7 data, query."""
        db.load_csv(temp_csv_file)

        new_patient = PatientInfo(mrn="100000001", age=35, sex="F")
        db.upsert_patient(new_patient)

        new_creatinine = CreatinineResult(
            mrn="100000001",
            creatinine_date=datetime(2024, 2, 1, 10, 0, 0),
            creatinine_result=88.0,
        )
        db.insert_creatinine(new_creatinine)

        patient = db.query_patient("100000001")

        assert patient["age"] == 35
        assert patient["sex"] == "F"
        assert len(patient["creatinine_history"]) == 3

    def test_concurrent_reads_with_wal(self, temp_db_path):
        """Test that WAL mode allows concurrent reads."""
        db1 = PatientDB(db_path=temp_db_path)
        db2 = PatientDB(db_path=temp_db_path)

        patient = PatientInfo(mrn="100000004", age=30, sex="M")
        db1.upsert_patient(patient)

        result = db2.query_patient("100000004")

        assert result is not None
        assert result["mrn"] == "100000004"

        db1.close()
        db2.close()
