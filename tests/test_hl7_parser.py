"""
Unit tests for HL7 Parser Module
"""

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from src.hl7.parser import HL7Parser, PatientInfo, CreatinineResult, MessageType


ADT_A01_MSG = (
    "MSH|^~\\&|SIMULATION|SOUTH RIVERSIDE|||202401201630||ADT^A01|||2.5\r"
    "PID|1||478237423||ELIZABETH HOLMES||19840203|F"
)

ADT_A01_NO_MRN = (
    "MSH|^~\\&|SIMULATION|SOUTH RIVERSIDE|||202401201630||ADT^A01|||2.5\r"
    "PID|1||||ELIZABETH HOLMES||19840203|F"
)

ADT_A01_NO_OPTIONAL = (
    "MSH|^~\\&|SIMULATION|SOUTH RIVERSIDE|||202401201630||ADT^A01|||2.5\r"
    "PID|1||478237423||ELIZABETH HOLMES||"
)

ADT_A01_CUSTOM_MRN = (
    "MSH|^~\\&|SIMULATION|SOUTH RIVERSIDE|||202401201630||ADT^A01|||2.5\r"
    "PID|1||999888777||SUNNY BALWANI||19850615|M"
)

ADT_A03_MSG = (
    "MSH|^~\\&|SIMULATION|SOUTH RIVERSIDE|||202401201630||ADT^A03|||2.5\r"
    "PID|1||478237423"
)

ADT_A03_CUSTOM_MRN = (
    "MSH|^~\\&|SIMULATION|SOUTH RIVERSIDE|||202401201630||ADT^A03|||2.5\r"
    "PID|1||999888777"
)

ADT_A03_NO_MRN = (
    "MSH|^~\\&|SIMULATION|SOUTH RIVERSIDE|||202401201630||ADT^A03|||2.5\r"
    "PID|1||"
)

ORU_R01_MSG = (
    "MSH|^~\\&|SIMULATION|SOUTH RIVERSIDE|||202401201630||ORU^R01|||2.5\r"
    "PID|1||478237423\r"
    "OBR|1||||||20240120224300\r"
    "OBX|1|SN|CREATININE||103.4"
)

ORU_R01_CUSTOM_MRN = (
    "MSH|^~\\&|SIMULATION|SOUTH RIVERSIDE|||202401201630||ORU^R01|||2.5\r"
    "PID|1||999888777\r"
    "OBR|1||||||20240120224300\r"
    "OBX|1|SN|CREATININE||103.4"
)

ORU_R01_HIGH_CREATININE = (
    "MSH|^~\\&|SIMULATION|SOUTH RIVERSIDE|||202401201630||ORU^R01|||2.5\r"
    "PID|1||478237423\r"
    "OBR|1||||||20240120224300\r"
    "OBX|1|SN|CREATININE||250.0"
)

ORU_R01_WITH_DATE = (
    "MSH|^~\\&|SIMULATION|SOUTH RIVERSIDE|||202401201630||ORU^R01|||2.5\r"
    "PID|1||478237423\r"
    "OBR|1||||||20240120163045\r"
    "OBX|1|SN|CREATININE||103.4"
)

ORU_R01_NO_MRN = (
    "MSH|^~\\&|SIMULATION|SOUTH RIVERSIDE|||202401201630||ORU^R01|||2.5\r"
    "PID|1||\r"
    "OBR|1||||||20240120224300\r"
    "OBX|1|SN|CREATININE||103.4"
)

ORU_R01_INVALID_CREATININE = (
    "MSH|^~\\&|SIMULATION|SOUTH RIVERSIDE|||202401201630||ORU^R01|||2.5\r"
    "PID|1||478237423\r"
    "OBR|1||||||20240120224300\r"
    "OBX|1|SN|CREATININE||INVALID"
)

ORU_R01_NO_DATE = (
    "MSH|^~\\&|SIMULATION|SOUTH RIVERSIDE|||202401201630||ORU^R01|||2.5\r"
    "PID|1||478237423\r"
    "OBR|1||||||\r"
    "OBX|1|SN|CREATININE||103.4"
)

UNSUPPORTED_MSG = (
    "MSH|^~\\&|SIMULATION|SOUTH RIVERSIDE|||202401201630||SIU^S12|||2.5\r"
    "PID|1||478237423||ELIZABETH HOLMES||19840203|F"
)


class TestHL7ParserSafeField:
    """Tests for safe field extraction."""

    def setup_method(self):
        self.parser = HL7Parser()

    def test_safe_field_valid_index(self):
        """Extract valid field by index."""
        segment = MagicMock()
        segment.__getitem__ = MagicMock(return_value="VALUE")

        result = self.parser._safe_field(segment, 3)

        assert result == "VALUE"

    def test_safe_field_returns_default_on_none(self):
        """Return default when field is None."""
        segment = MagicMock()
        segment.__getitem__ = MagicMock(return_value=None)

        result = self.parser._safe_field(segment, 3, default="N/A")

        assert result == "N/A"

    def test_safe_field_returns_default_on_exception(self):
        """Return default when field access raises exception."""
        segment = MagicMock()
        segment.__getitem__ = MagicMock(side_effect=IndexError("out of range"))

        result = self.parser._safe_field(segment, 99, default="FALLBACK")

        assert result == "FALLBACK"

    def test_safe_field_returns_empty_string_by_default(self):
        """Return empty string when no default specified and field missing."""
        segment = MagicMock()
        segment.__getitem__ = MagicMock(side_effect=IndexError)

        result = self.parser._safe_field(segment, 5)

        assert result == ""


class TestHL7ParserDatetime:
    """Tests for datetime parsing."""

    def setup_method(self):
        self.parser = HL7Parser()

    def test_parse_datetime_valid(self):
        """Parse valid HL7 datetime string."""
        result = self.parser._parse_datetime("20260126143000")

        assert result == datetime(2026, 1, 26, 14, 30, 0)

    def test_parse_datetime_empty_string(self):
        """Return None for empty datetime string."""
        result = self.parser._parse_datetime("")

        assert result is None

    def test_parse_datetime_invalid_format(self):
        """Return None for invalid datetime format."""
        result = self.parser._parse_datetime("not-a-date")

        assert result is None

    def test_parse_datetime_partial_format(self):
        """Return None for partial datetime (missing seconds)."""
        result = self.parser._parse_datetime("202601261430")

        assert result is None


class TestHL7ParserAge:
    """Tests for age calculation."""

    def setup_method(self):
        self.parser = HL7Parser()

    def test_parse_age_valid_dob(self):
        """Calculate age from valid DOB."""
        result = self.parser._parse_age("19840203")

        assert isinstance(result, int)
        assert result >= 40  # Born 1984

    def test_parse_age_empty_string(self):
        """Return None for empty DOB string."""
        result = self.parser._parse_age("")

        assert result is None

    def test_parse_age_invalid_format(self):
        """Return None for invalid DOB format."""
        result = self.parser._parse_age("not-a-date")

        assert result is None


class TestHL7ParserADTA01:
    """Tests for ADT^A01 (patient admission) parsing."""

    def setup_method(self):
        self.parser = HL7Parser()

    def test_parse_adt_a01_returns_patient_info(self):
        """ADT^A01 message returns PatientInfo object."""
        result = self.parser.parse(ADT_A01_MSG)

        assert isinstance(result, PatientInfo)

    def test_parse_adt_a01_extracts_mrn(self):
        """ADT^A01 correctly extracts MRN."""
        result = self.parser.parse(ADT_A01_CUSTOM_MRN)

        assert result.mrn == "999888777"

    def test_parse_adt_a01_extracts_sex(self):
        """ADT^A01 correctly extracts sex."""
        result = self.parser.parse(ADT_A01_CUSTOM_MRN)

        assert result.sex == "M"

    def test_parse_adt_a01_extracts_age(self):
        """ADT^A01 correctly calculates age from DOB."""
        result = self.parser.parse(ADT_A01_MSG)

        assert result.age is not None
        assert result.age >= 40  # Born 1984, test written 2024+

    def test_parse_adt_a01_missing_mrn_raises(self):
        """ADT^A01 without MRN raises ValueError."""
        with pytest.raises(ValueError, match="Missing required MRN"):
            self.parser.parse(ADT_A01_NO_MRN)

    def test_parse_adt_a01_missing_optional_fields(self):
        """ADT^A01 with missing optional fields returns None for them."""
        result = self.parser.parse(ADT_A01_NO_OPTIONAL)

        assert result.mrn == "478237423"
        assert result.age is None
        assert result.sex is None


class TestHL7ParserADTA03:
    """Tests for ADT^A03 (patient discharge) parsing."""

    def setup_method(self):
        self.parser = HL7Parser()

    def test_parse_adt_a03_returns_patient_info(self):
        """ADT^A03 message returns PatientInfo object."""
        result = self.parser.parse(ADT_A03_MSG)

        assert isinstance(result, PatientInfo)

    def test_parse_adt_a03_extracts_mrn(self):
        """ADT^A03 correctly extracts MRN."""
        result = self.parser.parse(ADT_A03_CUSTOM_MRN)

        assert result.mrn == "999888777"

    def test_parse_adt_a03_missing_mrn_raises(self):
        """ADT^A03 without MRN raises ValueError."""
        with pytest.raises(ValueError, match="Missing required MRN"):
            self.parser.parse(ADT_A03_NO_MRN)


class TestHL7ParserORUR01:
    """Tests for ORU^R01 (lab result) parsing."""

    def setup_method(self):
        self.parser = HL7Parser()

    def test_parse_oru_r01_returns_creatinine_result(self):
        """ORU^R01 message returns CreatinineResult object."""
        result = self.parser.parse(ORU_R01_MSG)

        assert isinstance(result, CreatinineResult)

    def test_parse_oru_r01_extracts_mrn(self):
        """ORU^R01 correctly extracts MRN."""
        result = self.parser.parse(ORU_R01_CUSTOM_MRN)

        assert result.mrn == "999888777"

    def test_parse_oru_r01_extracts_creatinine_value(self):
        """ORU^R01 correctly extracts creatinine result as float."""
        result = self.parser.parse(ORU_R01_HIGH_CREATININE)

        assert result.creatinine_result == 250.0

    def test_parse_oru_r01_extracts_creatinine_date(self):
        """ORU^R01 correctly parses observation date."""
        result = self.parser.parse(ORU_R01_WITH_DATE)

        assert result.creatinine_date == datetime(2024, 1, 20, 16, 30, 45)

    def test_parse_oru_r01_missing_mrn_raises(self):
        """ORU^R01 without MRN raises ValueError."""
        with pytest.raises(ValueError, match="Missing required MRN"):
            self.parser.parse(ORU_R01_NO_MRN)

    def test_parse_oru_r01_invalid_creatinine_value(self):
        """ORU^R01 with non-numeric creatinine returns None for value."""
        result = self.parser.parse(ORU_R01_INVALID_CREATININE)

        assert result.creatinine_result is None

    def test_parse_oru_r01_missing_creatinine_date(self):
        """ORU^R01 with empty date returns None for creatinine_date."""
        result = self.parser.parse(ORU_R01_NO_DATE)

        assert result.creatinine_date is None


class TestHL7ParserUnsupported:
    """Tests for unsupported message types and invalid input."""

    def setup_method(self):
        self.parser = HL7Parser()

    def test_parse_unsupported_message_type_returns_none(self):
        """Unsupported message type returns None."""
        result = self.parser.parse(UNSUPPORTED_MSG)

        assert result is None

    def test_parse_invalid_hl7_raises(self):
        """Completely invalid HL7 input raises ValueError."""
        with pytest.raises(ValueError, match="Failed to parse HL7 message"):
            self.parser.parse("NOT_VALID_HL7")


class TestMessageType:
    """Tests for MessageType enum values."""

    def test_adt_a01_value(self):
        """ADT^A01 enum has correct value."""
        assert MessageType.ADT_A01.value == "ADT^A01"

    def test_adt_a03_value(self):
        """ADT^A03 enum has correct value."""
        assert MessageType.ADT_A03.value == "ADT^A03"

    def test_oru_r01_value(self):
        """ORU^R01 enum has correct value."""
        assert MessageType.ORU_R01.value == "ORU^R01"
