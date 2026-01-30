"""
AKI Inference Module

Initializes by training on training.csv on startup. Then, accepts stream of  ORU^R01 (creatinine result) messages
and predicts AKI presence.
"""

import asyncio
import signal

import pandas as pd
import numpy as np
from sklearn.ensemble import GradientBoostingClassifier

from typing import Optional

from src.logger import logger
from src.database.patient import PatientDB
from src.mllp.client import MLLPClient
from src.hl7.parser import HL7Parser, PatientInfo, CreatinineResult

PREDICTION_THRESHOLD = 0.5

class AKIClassifier():
    """
    Gradient Boosting Classifier Model for AKI Prediction
    """
    def __init__(self, patient_db: PatientDB):
        """
        Initializes XGBoost implementation of AKI Classifier. It requires initial
        training dataset to train static model for inference.

        Args:
            patient_db (PatientDB): Patient database instance for inference

        Returns:
            None
        """
        self.model = GradientBoostingClassifier()
        self.patient_db = patient_db
        self.is_trained = False

    def _parse_creatinine_test_history_train(self, row) -> list:
        """
        Collect history of matching creatine test dates and results for training.

        Args:
            row (pd.Series): A row of patient data with history of creatinine tests

        Returns:
            list: List of (date, result) pairs for each patient
        """
        # Iteratively search for creatinine date and result pairs (column header)
        idx = 0
        historical_test = []

        while True:
            date_key = f"creatinine_date_{idx}"
            result_key = f"creatinine_result_{idx}"

            # Skip if either date or result key is missing (invalid test history)
            if date_key not in row or result_key not in row:
                break

            creatinine_date = row[date_key]
            creatinine_result = row[result_key]

            if pd.notna(creatinine_date) and pd.notna(creatinine_result):
                try:
                    historical_test.append((pd.to_datetime(creatinine_date), float(creatinine_result)))
                except (ValueError, TypeError) as e:
                    logger.warning(f"Skipping invalid row: {e}")

            idx += 1

        return sorted(historical_test, key=lambda x: x[0])

    def fit(self, X, y) -> None:
        """
        Train model on train data.

        Args:
            X (pd.DataFrame): Train data without target labels
            y (pd.Series): Labels "y" or "n"

        Returns:
            None
        """
        # Sanity checks on data size
        if len(X) != len(y):
            logger.error(f"Input training features and labels are not the same length. X: {len(X)}, y: {len(y)}")
            raise ValueError("Input training features and labels must have same length.")

        if X.empty:
            logger.error("Input training data cannot be empty.")
            raise ValueError("Input training data cannot be empty.")

        X_clean = self._extract_features(X, train=True)
        
        # Map target labels to binary values
        y_clean = y.map({"y": 1, "n": 0})
        
        self.model.fit(X_clean, y_clean)
        self.is_trained = True

        return None


    def _parse_creatinine_test_history_test(self, patient_data: dict):
        """
        Collect history of matching creatine test dates and results for inference.

        Args:
            patient_data (dict): Dictionary from PatientDB.query_patient() with structure:
                {
                    "mrn": str,
                    "age": int or None,
                    "sex": str or None,
                    "creatinine_history": [{"date": str, "result": float}, ...]
                }

        Returns:
            list: List of (date, result) pairs for each patient
        """
        historical_test = []

        creatinine_history = patient_data.get("creatinine_history", [])

        for entry in creatinine_history:
            creatinine_date_str = entry.get("date")
            creatinine_result = entry.get("result")

            if creatinine_date_str and creatinine_result is not None:
                try:
                    creatinine_date = pd.to_datetime(creatinine_date_str)
                    historical_test.append((creatinine_date, float(creatinine_result)))
                except (ValueError, TypeError) as e:
                    logger.warning(f"Skipping invalid row: {e}")

        return sorted(historical_test, key=lambda x: x[0])


    def _extract_features(self, X, train=True) -> pd.DataFrame:
        """Transform features before feeding as input for ML training/inference.

        Glossary:
        - C1: Most recent creatinine result
        - RV1: Lowest creatinine result in past 7 days
        - RV2: Median creatinine result in past 8-365 days
        - RV1 Ratio: C1 / RV1
        - RV2 Ratio: C1 / RV2
        - D_48h: Difference between C1 and lowest creatinine result in past 48 hours

        Args:
            X: pd.DataFrame (training) or list of dicts (inference from SQLite)
            train (bool): True for training data, False for inference

        Returns:
            pd.DataFrame: Transformed feature dataframe
        """
        features_list = []

        if train:
            rows = [row for _, row in X.iterrows()] # pd.DataFrame
        else:
            rows = X if isinstance(X, list) else [X] # X is list of patient_data dicts from SQLite

        for row in rows:
            if train:
                historical_test = self._parse_creatinine_test_history_train(row)
                age = row.get("age", 0)
                sex = row.get("sex")
            else:
                historical_test = self._parse_creatinine_test_history_test(row)
                age = row.get("age") or 0
                sex = row.get("sex")

            # Imputed default values for features if no history present
            features = {
                "age": age,
                "sex": 1 if sex == "m" else 0,
                "c1": -1,
                "rv2": -1,
                "rv1": -1,
                "rv1_ratio": 0.0,
                "rv2_ratio": 0.0,
                "d_48h": 0.0,
                "test_count_history": len(historical_test)
            }

            # Sort historical tests by date > to compute RV1, RV2, etc.
            if not historical_test:
                features_list.append(features)
                continue

            c1_date, c1_result = historical_test[-1]
            features["c1"] = c1_result
            
            prev_results_8_365 = []
            prev_results_0_7 = []
            prev_results_0_2 = []
            
            for test_date, test_result in historical_test[:-1]: 
                days_diff = (c1_date - test_date).days
                
                if 8 <= days_diff <= 365:
                    prev_results_8_365.append(test_result)

                if 0 <= days_diff <= 7:
                    prev_results_0_7.append(test_result)
                
                if 0 < days_diff <= 2:
                    prev_results_0_2.append(test_result)

            if prev_results_0_7:
                features["rv1"] = np.min(prev_results_0_7)
                if features["rv1"] != 0:
                    features["rv1_ratio"] = c1_result / features["rv1"]

            if prev_results_8_365:
                features["rv2"] = np.median(prev_results_8_365)
                if features["rv2"] != 0:
                    features["rv2_ratio"] = c1_result / features["rv2"]

            if prev_results_0_2:
                lowest_48h = np.min(prev_results_0_2)
                features["d_48h"] = c1_result - lowest_48h

            features_list.append(features)

        df = pd.DataFrame(features_list)
        
        # Final fill any missing values with -1
        return df.fillna(-1)

    def predict(self, mrn: str) -> Optional[str]:
        """
        Predict AKI for a single patient using data from the database.
        Called when ORU^R01 message is received.

        Args:
            mrn (str): Patient MRN to query

        Returns:
            Optional[str]: Prediction "y" or "n", or None if patient not found
        """
        if not self.is_trained:
            logger.error("Model must be trained before prediction.")
            raise ValueError("Model must be trained before prediction.")

        # Query patient data from database
        patient_data = self.patient_db.query_patient(mrn)

        if patient_data is None:
            logger.warning(f"Patient {mrn} not found in database, cannot predict")
            return None

        # Extract features (train=False uses _parse_creatinine_test_history_test)
        X_clean = self._extract_features([patient_data], train=False)

        # Run inference
        pred_proba = self.model.predict_proba(X_clean)[:, 1][0]
        prediction = "y" if pred_proba > PREDICTION_THRESHOLD else "n"

        logger.info(f"AKI prediction for {mrn}: {prediction} (prob: {pred_proba:.3f})")

        return prediction

    def train(self, csv_path: str = "data/training.csv") -> None:
        """
        Train model from CSV file. Called at startup.

        Args:
            csv_path (str): Path to training CSV file

        Returns:
            None
        """
        logger.info(f"Loading training data from {csv_path}")
        df = pd.read_csv(csv_path)

        X = df.drop(columns=["aki"])
        y = df["aki"]

        self.fit(X, y)
        logger.info(f"Model trained on {len(df)} samples")

        return None

async def main():
    """
    AKI Inference Pipeline:
        1. Initialize PatientDB and load historical CSV
        2. Train AKI classifier on training.csv
        3. Connect to MLLP simulator
        4. On each HL7 message:
            - ADT^A01/A03: Upsert patient demographics to DB
            - ORU^R01: Insert creatinine result to DB, then run AKI inference

    Usage:
        # Start simulator first (in another terminal):
        cd simulator
        python simulator.py --messages messages.mllp --mllp 8440

        # Then run this module:
        python -m src.model.aki
    """
    # Initialize database and load historical data
    db = PatientDB(db_path="data/patient.db")
    db.load_csv("simulator/history.csv")

    # Initialize and train classifier
    classifier = AKIClassifier(patient_db=db)
    classifier.train(csv_path="data/training.csv")

    # Initialize HL7 parser
    parser = HL7Parser()

    async def handle_message(hl7_message: str) -> Optional[str]:
        """
        Process incoming HL7 messages.

        - ADT messages: Upsert patient demographics
        - ORU^R01 messages: Insert creatinine result and run AKI inference

        Args:
            hl7_message (str): Raw HL7 message string.

        Returns:
            Optional[str]: Custom ACK message or None for auto-generated ACK.
        """
        try:
            result = parser.parse(hl7_message)

            if result is None:
                logger.debug("Unsupported message type, skipping.")
                return None

            if isinstance(result, PatientInfo):
                # ADT^A01 or ADT^A03 - patient demographics
                db.upsert_patient(result)
                logger.info(f"Updated patient demographics: MRN={result.mrn}")

            elif isinstance(result, CreatinineResult):
                # ORU^R01 - creatinine result
                db.insert_creatinine(result)
                logger.info(f"Inserted creatinine for MRN={result.mrn}: {result.creatinine_result}")

                # Run AKI inference
                prediction = classifier.predict(result.mrn)
                if prediction == "y":
                    logger.warning(f"AKI ALERT: Patient {result.mrn} predicted positive for AKI")
                else:
                    logger.info(f"AKI prediction for {result.mrn}: negative")

        except ValueError as e:
            logger.error(f"Parse error: {e}")
        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)

        return None  # Auto-generate ACK

    # Create MLLP client
    client = MLLPClient(
        host="localhost",
        port=8440,
        message_handler=handle_message,
        reconnect_delay=5.0,
        auto_reconnect=True
    )

    # Setup graceful shutdown
    loop = asyncio.get_running_loop()

    def signal_handler():
        logger.info("Received shutdown signal")
        asyncio.create_task(client.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    # Run client
    logger.info("Starting AKI inference pipeline...")
    try:
        await client.run()
    finally:
        db.close()
        logger.info("AKI inference pipeline stopped.")


if __name__ == "__main__":
    asyncio.run(main())
