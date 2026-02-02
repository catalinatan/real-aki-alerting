"""
Unit tests for PatientDB module.
    pytest tests/test_patient_db.py -v
"""

import os
import tempfile
import pytest
from datetime import datetime
from pathlib import Path

from src.database.patient import PatientDB
from src.hl7.parser import PatientInfo, CreatinineResult


@pytest.fixture
def temp_db_path():
    """
    Create a temporary database path for testing.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        yield os.path.join(tmpdir, "test_patient.db")

@pytest.fixture
def db(temp_db_path):
    """
    Create a PatientDB instance with a temporary database.
    """
    patient_db = PatientDB(db_path=temp_db_path)
    yield patient_db
    patient_db.close()

@pytest.fixture
def temp_csv_file():
    """
    Create a temporary CSV file with sample patient data.
    """
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        # Write CSV header and sample data
        f.write("mrn,creatinine_date_0,creatinine_result_0,creatinine_date_1,creatinine_result_1\n")
        f.write("100000001,2024-01-01 10:00:00,85.5,2024-01-02 11:00:00,90.2\n")
        f.write("100000002,2024-01-03 09:00:00,120.0,,\n")
        f.write("100000003,2024-01-04 14:30:00,75.3,2024-01-05 08:00:00,78.1\n")
        f.write(",2024-01-06 10:00:00,100.0,,\n")  # Empty MRN - should be skipped
        csv_path = f.name

    yield csv_path

    # Cleanup
    os.unlink(csv_path)

@pytest.fixture
def sample_patient_info():
    """
    Create sample PatientInfo for testing.
    """
    return PatientInfo(mrn="100000001", age=45, sex="M")

@pytest.fixture
def sample_creatinine_result():
    """
    Create sample CreatinineResult for testing.
    """
    return CreatinineResult(
        mrn="100000001",
        creatinine_date=datetime(2024, 1, 15, 10, 30, 0),
        creatinine_result=95.5
    )


class TestDatabaseInitialization:
    """
    Tests for database initialization and schema creation.
    """

    def test_database_creates_file(self, temp_db_path):
        """
        Database file should be created on initialization.
        """
        db = PatientDB(db_path=temp_db_path)
        assert Path(temp_db_path).exists()
        db.close()

    def test_database_creates_parent_directory(self):
        """
        Database should create parent directories if they don't exist.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            nested_path = os.path.join(tmpdir, "nested", "dir", "test.db")
            db = PatientDB(db_path=nested_path)
            assert Path(nested_path).exists()
            db.close()

    def test_schema_creates_patients_table(self, db):
        """
        Schema should create patients table with correct columns.
        """
        cursor = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='patients'"
        )
        assert cursor.fetchone() is not None

    def test_schema_creates_creatinine_history_table(self, db):
        """
        Schema should create creatinine_history table with correct columns.
        """
        cursor = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='creatinine_history'"
        )
        assert cursor.fetchone() is not None

    def test_schema_creates_index_on_mrn(self, db):
        """
        Schema should create index on mrn column.
        """
        cursor = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_mrn'"
        )
        assert cursor.fetchone() is not None

    def test_wal_mode_enabled(self, db):
        """Database should be in WAL mode."""
        cursor = db.conn.execute("PRAGMA journal_mode")
        mode = cursor.fetchone()[0]
        assert mode.lower() == "wal"


class TestCSVLoading:
    """
    Tests for loading patient data from CSV files.
    """

    def test_load_csv_creates_patients(self, db, temp_csv_file):
        """
        load_csv should create patient records from CSV.
        """
        db.load_csv(temp_csv_file)

        cursor = db.conn.execute("SELECT COUNT(*) FROM patients")
        count = cursor.fetchone()[0]
        assert count == 3  # 100000001, 100000002, 100000003 (empty MRN skipped)

    def test_load_csv_creates_creatinine_results(self, db, temp_csv_file):
        """
        load_csv should create creatinine result records from CSV.
        """
        db.load_csv(temp_csv_file)

        cursor = db.conn.execute("SELECT COUNT(*) FROM creatinine_history")
        count = cursor.fetchone()[0]
        assert count == 5  # 2 + 1 + 2 results

    def test_load_csv_skips_empty_mrn(self, db, temp_csv_file):
        """
        load_csv should skip rows with empty MRN.
        """
        db.load_csv(temp_csv_file)

        cursor = db.conn.execute("SELECT * FROM patients WHERE mrn = ''")
        assert cursor.fetchone() is None

    def test_load_csv_handles_missing_file(self, db):
        """
        load_csv should handle missing CSV file gracefully.
        """
        # Should not raise an exception
        db.load_csv("missing_file.csv")

        cursor = db.conn.execute("SELECT COUNT(*) FROM patients")
        count = cursor.fetchone()[0]
        assert count == 0

    def test_load_csv_parses_datetime_correctly(self, db, temp_csv_file):
        """
        load_csv should parse datetime strings correctly.
        """
        db.load_csv(temp_csv_file)

        cursor = db.conn.execute(
            "SELECT creatinine_date FROM creatinine_history WHERE mrn = '100000001' ORDER BY creatinine_date"
        )
        dates = [row[0] for row in cursor.fetchall()]

        assert "2024-01-01" in dates[0]
        assert "2024-01-02" in dates[1]

    def test_load_csv_parses_result_as_float(self, db, temp_csv_file):
        """
        load_csv should parse creatinine results as floats.
        """
        db.load_csv(temp_csv_file)

        cursor = db.conn.execute(
            "SELECT creatinine_result FROM creatinine_history WHERE mrn = '100000001' ORDER BY creatinine_date"
        )
        results = [row[0] for row in cursor.fetchall()]

        assert results[0] == pytest.approx(85.5)
        assert results[1] == pytest.approx(90.2)


class TestUpsertPatient:
    """
    Tests for upserting patient demographics.
    """

    def test_upsert_inserts_new_patient(self, db, sample_patient_info):
        """
        upsert_patient should insert new patient.
        """
        db.upsert_patient(sample_patient_info)

        cursor = db.conn.execute(
            "SELECT mrn, age, sex FROM patients WHERE mrn = ?",
            (sample_patient_info.mrn,)
        )
        row = cursor.fetchone()

        assert row is not None
        assert row["mrn"] == "100000001"
        assert row["age"] == 45
        assert row["sex"] == "M"

    def test_upsert_updates_existing_patient(self, db, sample_patient_info):
        """
        upsert_patient should update existing patient demographics.
        """
        # Insert initial patient
        db.upsert_patient(sample_patient_info)

        # Update with new demographics
        updated_patient = PatientInfo(mrn="100000001", age=46, sex="M")
        db.upsert_patient(updated_patient)

        cursor = db.conn.execute(
            "SELECT age FROM patients WHERE mrn = ?",
            (sample_patient_info.mrn,)
        )
        row = cursor.fetchone()

        assert row["age"] == 46

    def test_upsert_preserves_existing_values_when_null(self, db, sample_patient_info):
        """
        upsert_patient should preserve existing values when new values are None.
        """
        # Insert initial patient with demographics
        db.upsert_patient(sample_patient_info)

        # Update with partial data (None values)
        partial_patient = PatientInfo(mrn="100000001", age=None, sex=None)
        db.upsert_patient(partial_patient)

        cursor = db.conn.execute(
            "SELECT age, sex FROM patients WHERE mrn = ?",
            (sample_patient_info.mrn,)
        )
        row = cursor.fetchone()

        # Original values should be preserved
        assert row["age"] == 45
        assert row["sex"] == "M"

    def test_upsert_patient_with_no_demographics(self, db):
        """
        upsert_patient should handle patient with no demographics.
        """
        patient = PatientInfo(mrn="100000002", age=None, sex=None)
        db.upsert_patient(patient)

        cursor = db.conn.execute(
            "SELECT mrn, age, sex FROM patients WHERE mrn = '100000002'"
        )
        row = cursor.fetchone()

        assert row["mrn"] == "100000002"
        assert row["age"] is None
        assert row["sex"] is None


class TestInsertCreatinine:
    """Tests for inserting creatinine results."""

    def test_insert_creatinine_creates_record(self, db, sample_creatinine_result):
        """
        insert_creatinine should create creatinine result record.
        """
        db.insert_creatinine(sample_creatinine_result)

        cursor = db.conn.execute(
            "SELECT mrn, creatinine_result FROM creatinine_history WHERE mrn = ?",
            (sample_creatinine_result.mrn,)
        )
        row = cursor.fetchone()

        assert row is not None
        assert row["creatinine_result"] == pytest.approx(95.5)

    def test_insert_creatinine_creates_patient_if_not_exists(self, db, sample_creatinine_result):
        """
        insert_creatinine should create patient record if it doesn't exist.
        """
        db.insert_creatinine(sample_creatinine_result)

        cursor = db.conn.execute(
            "SELECT mrn FROM patients WHERE mrn = ?",
            (sample_creatinine_result.mrn,)
        )
        row = cursor.fetchone()

        assert row is not None

    def test_insert_creatinine_skips_null_date(self, db):
        """
        insert_creatinine should skip results with null date.
        """
        result = CreatinineResult(mrn="100000001", creatinine_date=None, creatinine_result=100.0)
        db.insert_creatinine(result)

        cursor = db.conn.execute("SELECT COUNT(*) FROM creatinine_history")
        count = cursor.fetchone()[0]
        assert count == 0

    def test_insert_creatinine_skips_null_result(self, db):
        """
        insert_creatinine should skip results with null creatinine value.
        """
        result = CreatinineResult(
            mrn="100000001",
            creatinine_date=datetime(2024, 1, 15, 10, 0, 0),
            creatinine_result=None
        )
        db.insert_creatinine(result)

        cursor = db.conn.execute("SELECT COUNT(*) FROM creatinine_history")
        count = cursor.fetchone()[0]
        assert count == 0

    def test_insert_multiple_creatinine_results(self, db):
        """
        insert_creatinine should allow multiple results for same patient.
        """
        result1 = CreatinineResult(
            mrn="100000001",
            creatinine_date=datetime(2024, 1, 15, 10, 0, 0),
            creatinine_result=95.0
        )
        result2 = CreatinineResult(
            mrn="100000001",
            creatinine_date=datetime(2024, 1, 16, 10, 0, 0),
            creatinine_result=98.0
        )

        db.insert_creatinine(result1)
        db.insert_creatinine(result2)

        cursor = db.conn.execute(
            "SELECT COUNT(*) FROM creatinine_history WHERE mrn = '100000001'"
        )
        count = cursor.fetchone()[0]
        assert count == 2


class TestQueryPatient:
    """
    Tests for querying patient data.
    """

    def test_query_patient_returns_none_for_nonexistent(self, db):
        """
        query_patient should return None for non-existent MRN.
        """
        result = db.query_patient("200000001")
        assert result is None

    def test_query_patient_returns_demographics(self, db, sample_patient_info):
        """
        query_patient should return patient demographics.
        """
        db.upsert_patient(sample_patient_info)

        result = db.query_patient("100000001")

        assert result is not None
        assert result["mrn"] == "100000001"
        assert result["age"] == 45
        assert result["sex"] == "M"

    def test_query_patient_returns_creatinine_history(self, db, sample_patient_info, sample_creatinine_result):
        """
        query_patient should return creatinine history.
        """
        db.upsert_patient(sample_patient_info)
        db.insert_creatinine(sample_creatinine_result)

        result = db.query_patient("100000001")

        assert len(result["creatinine_history"]) == 1
        assert result["creatinine_history"][0]["result"] == pytest.approx(95.5)

    def test_query_patient_returns_history_sorted_desc(self, db, sample_patient_info):
        """
        query_patient should return creatinine history sorted by date descending.
        """
        db.upsert_patient(sample_patient_info)

        # Insert results in random order
        dates = [
            datetime(2024, 1, 10, 10, 0, 0),
            datetime(2024, 1, 20, 10, 0, 0),
            datetime(2024, 1, 15, 10, 0, 0),
        ]
        for i, date in enumerate(dates):
            result = CreatinineResult(mrn="100000001", creatinine_date=date, creatinine_result=float(100 + i))
            db.insert_creatinine(result)

        patient = db.query_patient("100000001")
        history = patient["creatinine_history"]

        # Should be sorted descending (newest first)
        assert "2024-01-20" in history[0]["date"]
        assert "2024-01-15" in history[1]["date"]
        assert "2024-01-10" in history[2]["date"]

    def test_query_patient_with_no_demographics(self, db):
        """
        query_patient should work when patient has no demographics (age/sex are NULL).
        """
        # Insert creatinine result - this creates patient with NULL demographics
        result = CreatinineResult(
            mrn="200000002",
            creatinine_date=datetime(2024, 1, 15, 10, 0, 0),
            creatinine_result=100.0
        )
        db.insert_creatinine(result)

        patient = db.query_patient("200000002")

        assert patient is not None
        assert patient["mrn"] == "200000002"
        assert patient["age"] is None  # No demographics from ADT message
        assert patient["sex"] is None  # No demographics from ADT message
        assert len(patient["creatinine_history"]) == 1

    def test_query_patient_with_only_demographics(self, db, sample_patient_info):
        """
        query_patient should work when patient only has demographics (no creatinine history).
        """
        db.upsert_patient(sample_patient_info)

        patient = db.query_patient("100000001")

        assert patient is not None
        assert patient["mrn"] == "100000001"
        assert patient["age"] == 45
        assert patient["creatinine_history"] == []


class TestConnectionManagement:
    """
    Tests for database connection management.
    """

    def test_close_closes_connection(self, temp_db_path):
        """
        close should close the database connection.
        """
        db = PatientDB(db_path=temp_db_path)
        db.close()

        assert db.conn is None

    def test_close_is_idempotent(self, temp_db_path):
        """
        close should be safe to call multiple times.
        """
        db = PatientDB(db_path=temp_db_path)
        db.close()
        db.close()  # Should not raise

        assert db.conn is None

