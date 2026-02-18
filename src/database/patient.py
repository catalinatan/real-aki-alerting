"""
Patient Database Module - State Management

To ingest historical patient history (CSV); as well as new entries or updates
from received HL7 messages.

Uses SQLite with WAL (Write-Ahead Logging) mode. Ensure local state persistence
with durability.
"""

import csv
import io
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.hl7.parser import PatientInfo, CreatinineResult
from src.logger import logger

class PatientDB:
    """
    SQLite database to hold patient demographics and history.
    """
    def __init__(self, db_path: str = "data/patient.db"):
        """
        Initialize Patient SQLite database. On first setup,
        create directory and database schema if they do not exists.

        Args:
            db_path (str, optional): Path to SQLite database file.
        """
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None
        self._connect()
        self._create_schema()

    def _connect(self) -> None:
        """
        Connect to database in WAL mode.
        
        Returns:
            None
        """
        # Create database file if does not exist
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        # Connect to SQLite database with WAL mode
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.row_factory = sqlite3.Row

        return None

    def _create_schema(self) -> None:
        """
        Create database schema if not exists.

        Schema:
            - patients table (demographics):
                mrn (PK), age, sex

            - creatinine_history table (patient history):
                id (PK), mrn (FK), creatinine_date, creatinine_result
        
        Returns:
            None
        """
        # Create tables if does not exist
        self.conn.executescript("""
                    CREATE TABLE IF NOT EXISTS patients (
                        mrn TEXT PRIMARY KEY,
                        age INTEGER,
                        sex TEXT
                    );

                    CREATE TABLE IF NOT EXISTS creatinine_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        mrn TEXT,
                        creatinine_date TEXT,
                        creatinine_result REAL,
                        FOREIGN KEY(mrn) REFERENCES patients(mrn),
                        UNIQUE(mrn, creatinine_date)
                    );

                    CREATE INDEX IF NOT EXISTS idx_mrn ON creatinine_history(mrn);
                """)
        self.conn.commit()

        return None

    def load_csv(self, csv_path: str) -> None:
        """
        Load historical patient history from CSV export.
        
        Args:
            csv_path (str): Path to CSV file.

        Returns:
            None
        """
        if not Path(csv_path).exists():
            logger.warning(f"""
                           Historical patient CSV not found: {csv_path}.
                           Initializing database without historical data...
                           """)
            return None
        
        logger.info(f"Loading historical patient data from: {csv_path}")

        load_count = 0
        with open(csv_path, "r") as f:
            csv_data = io.StringIO(f.read())
            csv_reader = csv.DictReader(csv_data)

            for row in csv_reader:
                mrn = row.get("mrn", "").strip()
                if not mrn:
                    continue # Skip rows with no MRN, untrackable test history

                self.conn.execute(
                    "INSERT OR IGNORE INTO patients (mrn) VALUES (?)",
                    (mrn,)
                )

                # Iteratively search for creatinine date and result pairs (column header)
                idx = 0
                while True:
                    date_key = f"creatinine_date_{idx}"
                    result_key = f"creatinine_result_{idx}"

                    if date_key not in row:
                        break

                    date_str = row.get(date_key, "").strip()
                    result_str = row.get(result_key, "").strip()

                    if date_str and result_str:
                        try:
                            creatinine_date = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
                            creatinine_date_str = creatinine_date.strftime("%Y-%m-%d %H:%M:%S")
                            creatinine_result = float(result_str)

                            self.conn.execute("""
                                INSERT OR IGNORE INTO creatinine_history
                                (mrn, creatinine_date, creatinine_result)
                                VALUES (?, ?, ?)
                            """, (mrn, creatinine_date_str, creatinine_result))

                            load_count += 1
                        except (ValueError, TypeError) as e:
                            logger.warning(f"Skipping invalid row: {e}")
                    idx += 1

        self.conn.commit()
        logger.info(f"Loaded {load_count} creatinine results from CSV")

        return None
                
    def upsert_patient(self, patient: PatientInfo) -> None:
        """
        Insert or update patient demographics from newly received HL7 ADT message.
        Expect ADT message as pre-parsed into PatientInfo dataclass.

        Args:
            patient (PatientInfo): Patient info from ADT^A01 or ADT^A03.

        Returns:
            None
        """
        self.conn.execute("""
            INSERT INTO patients (mrn, age, sex)
            VALUES (?, ?, ?)
            ON CONFLICT(mrn) DO UPDATE SET
                age = COALESCE(excluded.age, patients.age),
                sex = COALESCE(excluded.sex, patients.sex)
        """, (patient.mrn, patient.age, patient.sex))
        self.conn.commit()
        logger.debug(f"Upserted patient: {patient.mrn}")

        return None

    def insert_creatinine(self, result: CreatinineResult) -> None:
        """
        Insert creatinine result from newly received HL7 ORU message.
        Expect ORU message as pre-parsed into CreatinineResult dataclass.

        Args:
            result (CreatinineResult): Creatinine result from ORU^R01.
        """
        if result.creatinine_date is None or result.creatinine_result is None:
            logger.warning(f"Skipping incomplete creatinine result for {result.mrn}")
            return None

        # Insert patient test result for new or existing patient
        self.conn.execute(
            "INSERT OR IGNORE INTO patients (mrn) VALUES (?)",
            (result.mrn,)
        )

        creatinine_date_str = result.creatinine_date.strftime("%Y-%m-%d %H:%M:%S")

        self.conn.execute("""
            INSERT OR IGNORE INTO creatinine_history
            (mrn, creatinine_date, creatinine_result)
            VALUES (?, ?, ?)
        """, (result.mrn, creatinine_date_str, result.creatinine_result))
        self.conn.commit()
        logger.debug(f"Inserted creatinine for {result.mrn}: {result.creatinine_result}")

        return None

    def query_patient(self, mrn: str) -> Optional[dict]:
        """Get patient with creatinine history sorted by date descending.

        If MRN is not found in both patients and creatinine_history tables, return None.
        Else, we will return patient information with whatever demographic or test history available.

        Args:
            mrn (str): Patient MRN.

        Returns:
            Optional[dict]: Patient data with creatinine history. Return None if patient does not exist.
        """
        # Query by MRN demographics and creatinine history
        cursor_demographics = self.conn.execute(
            "SELECT mrn, age, sex FROM patients WHERE mrn = ?",
            (mrn,)
        )
        row_demographics = cursor_demographics.fetchone()

        cursor_creatinine_history = self.conn.execute("""
            SELECT mrn, creatinine_date, creatinine_result
            FROM creatinine_history
            WHERE mrn = ?
            ORDER BY creatinine_date DESC
        """, (mrn,))
        rows_creatinine_history = cursor_creatinine_history.fetchall()

        # Return None if non-existent MRN in both tables
        if not row_demographics and not rows_creatinine_history:
            return None

        patient = {
            "mrn": row_demographics["mrn"] if row_demographics else rows_creatinine_history[0]["mrn"],
            "age": row_demographics["age"] if row_demographics else None,
            "sex": row_demographics["sex"] if row_demographics else None,
            "creatinine_history": []
        }

        for row in rows_creatinine_history:
            patient["creatinine_history"].append({
                "date": row["creatinine_date"],
                "result": row["creatinine_result"]
            })
        
        return patient

    def close(self) -> None:
        """
        Close database connection.

        Returns:
            None
        """
        if self.conn:
            self.conn.close()
            self.conn = None
