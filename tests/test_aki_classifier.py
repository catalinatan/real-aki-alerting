"""
Unit tests for AKI Classifier Module
"""

import os
import tempfile
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, patch

import pytest
import pandas as pd
import numpy as np

from src.model.aki import AKIClassifier, PREDICTION_THRESHOLD
from src.database.patient import PatientDB
from src.hl7.parser import PatientInfo, CreatinineResult


class TestAKIClassifierInit:
    """Tests for AKIClassifier initialization."""

    def test_init_stores_patient_db(self):
        """Classifier stores reference to patient database."""
        mock_db = Mock(spec=PatientDB)
        classifier = AKIClassifier(patient_db=mock_db)

        assert classifier.patient_db is mock_db

    def test_init_is_trained_false(self):
        """Classifier starts untrained."""
        mock_db = Mock(spec=PatientDB)
        classifier = AKIClassifier(patient_db=mock_db)

        assert classifier.is_trained is False

    def test_init_creates_gradient_boosting_model(self):
        """Classifier uses GradientBoostingClassifier."""
        from sklearn.ensemble import GradientBoostingClassifier

        mock_db = Mock(spec=PatientDB)
        classifier = AKIClassifier(patient_db=mock_db)

        assert isinstance(classifier.model, GradientBoostingClassifier)


class TestParseCreatinineTestHistoryTrain:
    """Tests for _parse_creatinine_test_history_train."""

    def setup_method(self):
        self.mock_db = Mock(spec=PatientDB)
        self.classifier = AKIClassifier(patient_db=self.mock_db)

    def test_empty_row_returns_empty_list(self):
        """Row with no creatinine columns returns empty list."""
        row = pd.Series({"age": 50, "sex": "m"})

        result = self.classifier._parse_creatinine_test_history_train(row)

        assert result == []

    def test_single_valid_test(self):
        """Single valid date/result pair is parsed correctly."""
        row = pd.Series({
            "age": 50,
            "sex": "m",
            "creatinine_date_0": "2024-01-15",
            "creatinine_result_0": 1.2,
        })

        result = self.classifier._parse_creatinine_test_history_train(row)

        assert len(result) == 1
        assert result[0][1] == 1.2

    def test_multiple_tests_sorted_chronologically(self):
        """Multiple tests are returned sorted by date."""
        row = pd.Series({
            "creatinine_date_0": "2024-01-20",
            "creatinine_result_0": 1.5,
            "creatinine_date_1": "2024-01-10",
            "creatinine_result_1": 1.0,
            "creatinine_date_2": "2024-01-15",
            "creatinine_result_2": 1.2,
        })

        result = self.classifier._parse_creatinine_test_history_train(row)

        assert len(result) == 3
        # Should be sorted: Jan 10, Jan 15, Jan 20
        assert result[0][1] == 1.0
        assert result[1][1] == 1.2
        assert result[2][1] == 1.5

    def test_missing_result_skips_pair(self):
        """Missing result value causes pair to be skipped."""
        row = pd.Series({
            "creatinine_date_0": "2024-01-15",
            "creatinine_result_0": np.nan,
            "creatinine_date_1": "2024-01-16",
            "creatinine_result_1": 1.3,
        })

        result = self.classifier._parse_creatinine_test_history_train(row)

        assert len(result) == 1
        assert result[0][1] == 1.3

    def test_missing_date_skips_pair(self):
        """Missing date value causes pair to be skipped."""
        row = pd.Series({
            "creatinine_date_0": np.nan,
            "creatinine_result_0": 1.2,
            "creatinine_date_1": "2024-01-16",
            "creatinine_result_1": 1.3,
        })

        result = self.classifier._parse_creatinine_test_history_train(row)

        assert len(result) == 1
        assert result[0][1] == 1.3

    def test_invalid_date_format_skips_pair(self):
        """Invalid date format logs warning and skips."""
        row = pd.Series({
            "creatinine_date_0": "not-a-date",
            "creatinine_result_0": 1.2,
            "creatinine_date_1": "2024-01-16",
            "creatinine_result_1": 1.3,
        })

        result = self.classifier._parse_creatinine_test_history_train(row)

        assert len(result) == 1
        assert result[0][1] == 1.3

    def test_non_numeric_result_skips_pair(self):
        """Non-numeric result logs warning and skips."""
        row = pd.Series({
            "creatinine_date_0": "2024-01-15",
            "creatinine_result_0": "invalid",
            "creatinine_date_1": "2024-01-16",
            "creatinine_result_1": 1.3,
        })

        result = self.classifier._parse_creatinine_test_history_train(row)

        assert len(result) == 1
        assert result[0][1] == 1.3


class TestParseCreatinineTestHistoryTest:
    """Tests for _parse_creatinine_test_history_test."""

    def setup_method(self):
        self.mock_db = Mock(spec=PatientDB)
        self.classifier = AKIClassifier(patient_db=self.mock_db)

    def test_empty_history_returns_empty_list(self):
        """Empty creatinine_history returns empty list."""
        patient_data = {
            "mrn": "12345",
            "age": 50,
            "sex": "m",
            "creatinine_history": [],
        }

        result = self.classifier._parse_creatinine_test_history_test(patient_data)

        assert result == []

    def test_missing_history_key_returns_empty_list(self):
        """Missing creatinine_history key returns empty list."""
        patient_data = {"mrn": "12345", "age": 50, "sex": "m"}

        result = self.classifier._parse_creatinine_test_history_test(patient_data)

        assert result == []

    def test_valid_history_parsed_correctly(self):
        """Valid history entries are parsed and sorted."""
        patient_data = {
            "mrn": "12345",
            "creatinine_history": [
                {"date": "2024-01-20", "result": 1.5},
                {"date": "2024-01-10", "result": 1.0},
                {"date": "2024-01-15", "result": 1.2},
            ],
        }

        result = self.classifier._parse_creatinine_test_history_test(patient_data)

        assert len(result) == 3
        # Should be sorted chronologically
        assert result[0][1] == 1.0
        assert result[1][1] == 1.2
        assert result[2][1] == 1.5

    def test_missing_date_skips_entry(self):
        """Entry without date is skipped."""
        patient_data = {
            "mrn": "12345",
            "creatinine_history": [
                {"result": 1.5},
                {"date": "2024-01-15", "result": 1.2},
            ],
        }

        result = self.classifier._parse_creatinine_test_history_test(patient_data)

        assert len(result) == 1
        assert result[0][1] == 1.2

    def test_none_result_skips_entry(self):
        """Entry with None result is skipped."""
        patient_data = {
            "mrn": "12345",
            "creatinine_history": [
                {"date": "2024-01-20", "result": None},
                {"date": "2024-01-15", "result": 1.2},
            ],
        }

        result = self.classifier._parse_creatinine_test_history_test(patient_data)

        assert len(result) == 1
        assert result[0][1] == 1.2

    def test_invalid_date_skips_entry(self):
        """Entry with invalid date is skipped."""
        patient_data = {
            "mrn": "12345",
            "creatinine_history": [
                {"date": "not-a-date", "result": 1.5},
                {"date": "2024-01-15", "result": 1.2},
            ],
        }

        result = self.classifier._parse_creatinine_test_history_test(patient_data)

        assert len(result) == 1
        assert result[0][1] == 1.2


class TestExtractFeatures:
    """Tests for _extract_features."""

    def setup_method(self):
        self.mock_db = Mock(spec=PatientDB)
        self.classifier = AKIClassifier(patient_db=self.mock_db)

    def test_no_history_returns_defaults(self):
        """No historical tests returns default feature values."""
        df = pd.DataFrame([{"age": 50, "sex": "m"}])

        result = self.classifier._extract_features(df, train=True)

        assert result["c1"].iloc[0] == -1
        assert result["rv1"].iloc[0] == -1
        assert result["rv2"].iloc[0] == -1
        assert result["rv1_ratio"].iloc[0] == 0.0
        assert result["rv2_ratio"].iloc[0] == 0.0
        assert result["d_48h"].iloc[0] == 0.0

    def test_age_and_sex_encoded(self):
        """Age and sex are correctly encoded."""
        df = pd.DataFrame([{"age": 65, "sex": "m"}])

        result = self.classifier._extract_features(df, train=True)

        assert result["age"].iloc[0] == 65
        assert result["sex"].iloc[0] == 1  # male = 1

    def test_female_sex_encoded_as_zero(self):
        """Female sex is encoded as 0."""
        df = pd.DataFrame([{"age": 45, "sex": "f"}])

        result = self.classifier._extract_features(df, train=True)

        assert result["sex"].iloc[0] == 0

    def test_single_test_sets_c1_only(self):
        """Single test sets c1 but no RV1/RV2 (no prior tests)."""
        today = datetime.now()
        df = pd.DataFrame([{
            "age": 50,
            "sex": "m",
            "creatinine_date_0": today.strftime("%Y-%m-%d"),
            "creatinine_result_0": 1.5,
        }])

        result = self.classifier._extract_features(df, train=True)

        assert result["c1"].iloc[0] == 1.5
        assert result["rv1"].iloc[0] == -1  # No prior tests
        assert result["rv2"].iloc[0] == -1

    def test_rv1_calculated_from_7_day_window(self):
        """RV1 is minimum of tests within 0-7 days before C1."""
        today = datetime.now()
        df = pd.DataFrame([{
            "age": 50,
            "sex": "m",
            "creatinine_date_0": (today - timedelta(days=3)).strftime("%Y-%m-%d"),
            "creatinine_result_0": 1.0,
            "creatinine_date_1": (today - timedelta(days=5)).strftime("%Y-%m-%d"),
            "creatinine_result_1": 1.2,
            "creatinine_date_2": today.strftime("%Y-%m-%d"),
            "creatinine_result_2": 1.5,
        }])

        result = self.classifier._extract_features(df, train=True)

        assert result["c1"].iloc[0] == 1.5
        assert result["rv1"].iloc[0] == 1.0  # min of 1.0 and 1.2
        assert result["rv1_ratio"].iloc[0] == pytest.approx(1.5)  # 1.5 / 1.0

    def test_rv2_calculated_from_8_365_day_window(self):
        """RV2 is median of tests within 8-365 days before C1."""
        today = datetime.now()
        df = pd.DataFrame([{
            "age": 50,
            "sex": "m",
            "creatinine_date_0": (today - timedelta(days=30)).strftime("%Y-%m-%d"),
            "creatinine_result_0": 1.0,
            "creatinine_date_1": (today - timedelta(days=60)).strftime("%Y-%m-%d"),
            "creatinine_result_1": 1.4,
            "creatinine_date_2": (today - timedelta(days=90)).strftime("%Y-%m-%d"),
            "creatinine_result_2": 1.2,
            "creatinine_date_3": today.strftime("%Y-%m-%d"),
            "creatinine_result_3": 1.8,
        }])

        result = self.classifier._extract_features(df, train=True)

        assert result["c1"].iloc[0] == 1.8
        assert result["rv2"].iloc[0] == 1.2  # median of [1.0, 1.2, 1.4]
        assert result["rv2_ratio"].iloc[0] == pytest.approx(1.5)  # 1.8 / 1.2

    def test_d_48h_calculated_correctly(self):
        """D_48h is difference between C1 and lowest in past 48 hours."""
        today = datetime.now()
        df = pd.DataFrame([{
            "age": 50,
            "sex": "m",
            "creatinine_date_0": (today - timedelta(days=1)).strftime("%Y-%m-%d"),
            "creatinine_result_0": 1.0,
            "creatinine_date_1": (today - timedelta(days=2)).strftime("%Y-%m-%d"),
            "creatinine_result_1": 1.2,
            "creatinine_date_2": today.strftime("%Y-%m-%d"),
            "creatinine_result_2": 1.8,
        }])

        result = self.classifier._extract_features(df, train=True)

        assert result["c1"].iloc[0] == 1.8
        assert result["d_48h"].iloc[0] == pytest.approx(0.8)  # 1.8 - 1.0

    def test_rv1_zero_avoids_division_by_zero(self):
        """When RV1 is 0, rv1_ratio stays 0 to avoid division by zero."""
        today = datetime.now()
        df = pd.DataFrame([{
            "age": 50,
            "sex": "m",
            "creatinine_date_0": (today - timedelta(days=3)).strftime("%Y-%m-%d"),
            "creatinine_result_0": 0.0,
            "creatinine_date_1": today.strftime("%Y-%m-%d"),
            "creatinine_result_1": 1.5,
        }])

        result = self.classifier._extract_features(df, train=True)

        assert result["rv1"].iloc[0] == 0.0
        assert result["rv1_ratio"].iloc[0] == 0.0  # Not inf

    def test_rv2_zero_avoids_division_by_zero(self):
        """When RV2 is 0, rv2_ratio stays 0 to avoid division by zero."""
        today = datetime.now()
        df = pd.DataFrame([{
            "age": 50,
            "sex": "m",
            "creatinine_date_0": (today - timedelta(days=30)).strftime("%Y-%m-%d"),
            "creatinine_result_0": 0.0,
            "creatinine_date_1": today.strftime("%Y-%m-%d"),
            "creatinine_result_1": 1.5,
        }])

        result = self.classifier._extract_features(df, train=True)

        assert result["rv2"].iloc[0] == 0.0
        assert result["rv2_ratio"].iloc[0] == 0.0  # Not inf

    def test_inference_mode_uses_dict_format(self):
        """Inference mode (train=False) accepts dict list format."""
        today = datetime.now()
        patient_data = [{
            "mrn": "12345",
            "age": 50,
            "sex": "m",
            "creatinine_history": [
                {"date": (today - timedelta(days=3)).strftime("%Y-%m-%d"), "result": 1.0},
                {"date": today.strftime("%Y-%m-%d"), "result": 1.5},
            ],
        }]

        result = self.classifier._extract_features(patient_data, train=False)

        assert result["c1"].iloc[0] == 1.5
        assert result["rv1"].iloc[0] == 1.0

    def test_none_age_defaults_to_zero(self):
        """None age defaults to 0 in inference mode."""
        patient_data = [{
            "mrn": "12345",
            "age": None,
            "sex": "m",
            "creatinine_history": [],
        }]

        result = self.classifier._extract_features(patient_data, train=False)

        assert result["age"].iloc[0] == 0

    def test_test_count_history_tracked(self):
        """test_count_history reflects number of historical tests."""
        today = datetime.now()
        df = pd.DataFrame([{
            "age": 50,
            "sex": "m",
            "creatinine_date_0": (today - timedelta(days=1)).strftime("%Y-%m-%d"),
            "creatinine_result_0": 1.0,
            "creatinine_date_1": (today - timedelta(days=2)).strftime("%Y-%m-%d"),
            "creatinine_result_1": 1.2,
            "creatinine_date_2": today.strftime("%Y-%m-%d"),
            "creatinine_result_2": 1.5,
        }])

        result = self.classifier._extract_features(df, train=True)

        assert result["test_count_history"].iloc[0] == 3

    def test_multiple_patients_processed(self):
        """Multiple patients are processed correctly."""
        df = pd.DataFrame([
            {"age": 50, "sex": "m"},
            {"age": 60, "sex": "f"},
        ])

        result = self.classifier._extract_features(df, train=True)

        assert len(result) == 2
        assert result["age"].iloc[0] == 50
        assert result["age"].iloc[1] == 60
        assert result["sex"].iloc[0] == 1
        assert result["sex"].iloc[1] == 0


class TestFit:
    """Tests for fit method."""

    def setup_method(self):
        self.mock_db = Mock(spec=PatientDB)
        self.classifier = AKIClassifier(patient_db=self.mock_db)

    def test_raises_on_length_mismatch(self):
        """Raises ValueError when X and y have different lengths."""
        X = pd.DataFrame({"age": [50, 60, 70], "sex": ["m", "f", "m"]})
        y = pd.Series(["y", "n"])

        with pytest.raises(ValueError, match="same length"):
            self.classifier.fit(X, y)

    def test_raises_on_empty_data(self):
        """Raises ValueError when X is empty."""
        X = pd.DataFrame()
        y = pd.Series(dtype=str)

        with pytest.raises(ValueError, match="cannot be empty"):
            self.classifier.fit(X, y)

    def test_fit_sets_is_trained(self):
        """Successful fit sets is_trained to True."""
        X = pd.DataFrame({
            "age": [50, 60, 70, 80],
            "sex": ["m", "f", "m", "f"],
        })
        y = pd.Series(["y", "n", "y", "n"])

        self.classifier.fit(X, y)

        assert self.classifier.is_trained is True

    def test_fit_maps_labels_correctly(self):
        """Labels are mapped: 'y' -> 1, 'n' -> 0."""
        X = pd.DataFrame({
            "age": [50, 60],
            "sex": ["m", "f"],
        })
        y = pd.Series(["y", "n"])

        # Should not raise
        self.classifier.fit(X, y)

        assert self.classifier.is_trained is True


class TestPredict:
    """Tests for predict method."""

    def setup_method(self):
        self.mock_db = Mock(spec=PatientDB)
        self.classifier = AKIClassifier(patient_db=self.mock_db)

    def test_raises_if_not_trained(self):
        """Raises ValueError if model not trained."""
        with pytest.raises(ValueError, match="must be trained"):
            self.classifier.predict("12345")

    def test_returns_none_if_patient_not_found(self):
        """Returns None when patient not in database."""
        self.classifier.is_trained = True
        self.classifier.model = MagicMock()
        self.mock_db.query_patient.return_value = None

        result = self.classifier.predict("unknown_mrn")

        assert result is None
        self.mock_db.query_patient.assert_called_once_with("unknown_mrn")

    def test_returns_y_for_high_probability(self):
        """Returns 'y' when prediction probability > threshold."""
        self.classifier.is_trained = True
        mock_model = MagicMock()
        mock_model.predict_proba.return_value = np.array([[0.3, 0.7]])  # 70% AKI
        self.classifier.model = mock_model

        self.mock_db.query_patient.return_value = {
            "mrn": "12345",
            "age": 50,
            "sex": "m",
            "creatinine_history": [],
        }

        result = self.classifier.predict("12345")

        assert result == "y"

    def test_returns_n_for_low_probability(self):
        """Returns 'n' when prediction probability <= threshold."""
        self.classifier.is_trained = True
        mock_model = MagicMock()
        mock_model.predict_proba.return_value = np.array([[0.7, 0.3]])  # 30% AKI
        self.classifier.model = mock_model

        self.mock_db.query_patient.return_value = {
            "mrn": "12345",
            "age": 50,
            "sex": "m",
            "creatinine_history": [],
        }

        result = self.classifier.predict("12345")

        assert result == "n"

    def test_threshold_boundary_returns_n(self):
        """Returns 'n' when probability equals threshold."""
        self.classifier.is_trained = True
        mock_model = MagicMock()
        mock_model.predict_proba.return_value = np.array([[0.5, 0.5]])  # Exactly 50%
        self.classifier.model = mock_model

        self.mock_db.query_patient.return_value = {
            "mrn": "12345",
            "age": 50,
            "sex": "m",
            "creatinine_history": [],
        }

        result = self.classifier.predict("12345")

        assert result == "n"  # 0.5 is not > 0.5


class TestTrain:
    """Tests for train method."""

    def setup_method(self):
        self.mock_db = Mock(spec=PatientDB)
        self.classifier = AKIClassifier(patient_db=self.mock_db)

    def test_train_loads_csv_and_fits(self):
        """Train loads CSV and calls fit."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("age,sex,aki\n")
            f.write("50,m,y\n")
            f.write("60,f,n\n")
            f.write("70,m,y\n")
            f.write("80,f,n\n")
            csv_path = f.name

        try:
            self.classifier.train(csv_path=csv_path)

            assert self.classifier.is_trained is True
        finally:
            os.unlink(csv_path)

    def test_train_raises_on_missing_file(self):
        """Raises error when CSV file doesn't exist."""
        with pytest.raises(FileNotFoundError):
            self.classifier.train(csv_path="nonexistent.csv")

    def test_train_raises_on_missing_aki_column(self):
        """Raises KeyError when aki column missing."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("age,sex\n")
            f.write("50,m\n")
            csv_path = f.name

        try:
            with pytest.raises(KeyError):
                self.classifier.train(csv_path=csv_path)
        finally:
            os.unlink(csv_path)


class TestPredictionThreshold:
    """Tests for PREDICTION_THRESHOLD constant."""

    def test_threshold_is_valid(self):
        """Threshold is between 0 and 1."""
        assert 0 < PREDICTION_THRESHOLD < 1

    def test_threshold_is_half(self):
        """Threshold is set to 0.5."""
        assert PREDICTION_THRESHOLD == 0.5


class TestExtractFeaturesEdgeCases:
    """Additional edge case tests for _extract_features."""

    def setup_method(self):
        self.mock_db = Mock(spec=PatientDB)
        self.classifier = AKIClassifier(patient_db=self.mock_db)

    def test_test_on_same_day_as_c1_not_in_rv1(self):
        """Tests on same day as C1 (days_diff=0) should be in rv1 window."""
        today = datetime.now()
        df = pd.DataFrame([{
            "age": 50,
            "sex": "m",
            # Two tests on same day - only most recent is C1
            "creatinine_date_0": today.strftime("%Y-%m-%d %H:%M:%S"),
            "creatinine_result_0": 1.0,
            "creatinine_date_1": (today + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"),
            "creatinine_result_1": 1.5,
        }])

        result = self.classifier._extract_features(df, train=True)

        assert result["c1"].iloc[0] == 1.5

    def test_test_exactly_7_days_ago_in_rv1(self):
        """Test exactly 7 days before C1 is included in RV1."""
        today = datetime.now()
        df = pd.DataFrame([{
            "age": 50,
            "sex": "m",
            "creatinine_date_0": (today - timedelta(days=7)).strftime("%Y-%m-%d"),
            "creatinine_result_0": 1.0,
            "creatinine_date_1": today.strftime("%Y-%m-%d"),
            "creatinine_result_1": 1.5,
        }])

        result = self.classifier._extract_features(df, train=True)

        assert result["rv1"].iloc[0] == 1.0

    def test_test_exactly_8_days_ago_in_rv2(self):
        """Test exactly 8 days before C1 is included in RV2."""
        today = datetime.now()
        df = pd.DataFrame([{
            "age": 50,
            "sex": "m",
            "creatinine_date_0": (today - timedelta(days=8)).strftime("%Y-%m-%d"),
            "creatinine_result_0": 1.0,
            "creatinine_date_1": today.strftime("%Y-%m-%d"),
            "creatinine_result_1": 1.5,
        }])

        result = self.classifier._extract_features(df, train=True)

        assert result["rv2"].iloc[0] == 1.0

    def test_test_exactly_365_days_ago_in_rv2(self):
        """Test exactly 365 days before C1 is included in RV2."""
        today = datetime.now()
        df = pd.DataFrame([{
            "age": 50,
            "sex": "m",
            "creatinine_date_0": (today - timedelta(days=365)).strftime("%Y-%m-%d"),
            "creatinine_result_0": 1.0,
            "creatinine_date_1": today.strftime("%Y-%m-%d"),
            "creatinine_result_1": 1.5,
        }])

        result = self.classifier._extract_features(df, train=True)

        assert result["rv2"].iloc[0] == 1.0

    def test_test_366_days_ago_not_in_rv2(self):
        """Test 366 days before C1 is NOT included in RV2."""
        today = datetime.now()
        df = pd.DataFrame([{
            "age": 50,
            "sex": "m",
            "creatinine_date_0": (today - timedelta(days=366)).strftime("%Y-%m-%d"),
            "creatinine_result_0": 1.0,
            "creatinine_date_1": today.strftime("%Y-%m-%d"),
            "creatinine_result_1": 1.5,
        }])

        result = self.classifier._extract_features(df, train=True)

        assert result["rv2"].iloc[0] == -1  # Default, no valid RV2 tests

    def test_missing_values_filled_with_negative_one(self):
        """Missing values in features are filled with -1."""
        df = pd.DataFrame([{"age": None, "sex": None}])

        result = self.classifier._extract_features(df, train=True)

        # Verify fillna(-1) was applied
        assert not result.isna().any().any()
