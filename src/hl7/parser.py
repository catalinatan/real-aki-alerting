"""
HL7 Message Parser Module

Parses HL7v2 messages into structured data objects from ADT and ORU message types.
We only care about the following message types. Others are ignored.

ADT^A01 - Patient Admission
ADT^A03 - Patient Discharge
- Extract patient MRN and demographics

ORU^R01 - Observation Result (Lab)
- Extract patient MRN, creatinine test result and date
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from enum import Enum
import asyncio
import signal

import hl7

from src.mllp.client import MLLPClient
from src.logger import logger

class MessageType(Enum):
    """HL7 Message types supported by this parser."""
    ADT_A01 = "ADT^A01"
    ADT_A03 = "ADT^A03"
    ORU_R01 = "ORU^R01"


@dataclass
class PatientInfo:
    """Patient information from PID segment. To extract from ADT^A01 and ADT^A03 messages."""
    mrn: str                           # PID.3 - Medical Record Number
    age: Optional[int] = None          # PID.7 - DOB (as datetime), to convert to age
    sex: Optional[str] = None          # PID.8 - Sex


@dataclass
class CreatinineResult:
    """Creatinine test information from OBR/OBX segments. To extract from ORU^R01 messages."""
    mrn: str                                            # PID.3 - Medical Record Number
    creatinine_date: Optional[datetime] = None          # OBR.7 - Time which test took place
    creatinine_result: Optional[float] = None           # OBX.5 - Observed value of creatinine


class HL7Parser:
    """
    HL7v2 Message Parser implementation.

    Parses ADT^A01 and ADT^A03 messages for patient info
    and ORU^R01 messages for creatinine results.
    """

    def _safe_field(self, segment, index: int, default: str = "") -> str:
        """
        Safely get a field value from a HL7 segment by index.

        Args:
            segment: HL7 segment object.
            index (int): Field index to retrieve.
            default (str, optional): Fallback value when field is missing or None.

        Returns:
            str: Field value as string or default when unavailable.
        """
        try:
            value = segment[index]
            return str(value) if value is not None else default
        except Exception:
            return default
    
    def _parse_datetime(self, datetime_str: str) -> Optional[datetime]:
        """
        Parse HL7 datetime format 'yyyyMMddHHmm' into 'yyyyMMddHHmmss'.

        Args:
            datetime_str (str): HL7 datetime string.

        Returns:
            Optional[datetime]: Parsed datetime or None if invalid.
        """
        if not datetime_str:
            return None
        
        try:
            return datetime.strptime(datetime_str, "%Y%m%d%H%M%S")
        except ValueError:
            pass

        return None
    
    def _parse_age(self, datetime_str: str) -> Optional[int]:
        """
        Calculate age from HL7 datetime format 'yyyyMMddHHmm'.

        Args:
            datetime_str (str): HL7 datetime string.

        Returns:
            Optional[int]: Calculated age or None if invalid.
        """
        if not datetime_str:
            return None
        
        try:
            dob = datetime.strptime(datetime_str, "%Y%m%d%H%M")
            today = datetime.now()
            age = today.year - dob.year
            
            # Adjust if birthday hasn't occurred yet this year
            if (today.month, today.day) < (dob.month, dob.day):
                age -= 1
            return age
        except ValueError:
            return None

    def _get_segment(self, msg, segment_name: str) -> Optional[hl7.Segment]:
        """
        Get a segment from a parsed message.
        
        Args:
            msg: Parsed HL7 message object.
            segment_name (str): Name of the segment to retrieve.
                - e.g. "PID", "OBR", "OBX"

        Returns:
            Optional[hl7.Segment]: The requested segment or None if not found.
        """
        try:
            return msg.segment(segment_name)
        except (KeyError, IndexError):
            return None
    
    def _parse_patient_info(self, msg) -> PatientInfo:
        """
        Extract patient information from PID segment. If MRN is missing, raises ValueError.
        
        Args:
            msg: Parsed HL7 message object.
        
        Returns:
            PatientInfo: Extracted patient information.
        """
        # If message untraceable to patient (by MRN), raise error
        pid = self._get_segment(msg, "PID")
        mrn = self._safe_field(pid, 3)
        if not mrn:
            raise ValueError("Missing required MRN in PID.3")

        dob_str = self._safe_field(pid, 7)
        sex = self._safe_field(pid, 8)

        # Calculate age from DOB
        age = None
        if dob_str:
            try:
                age = self._parse_age(dob_str)
            except (ValueError, IndexError):
                pass

        patient = PatientInfo(
            mrn=mrn,
            age=age,
            sex=sex if sex else None
        )

        return patient
    
    def _parse_creatinine_result(self, msg) -> CreatinineResult:
        """
        Extract creatinine result from OBR/OBX segments. If MRN is missing, raises ValueError.
        
        Args:
            msg: Parsed HL7 message object.

        Returns:
            CreatinineResult: Extracted creatinine result.
        """
        # If message untraceable to patient (by MRN), raise error
        pid = self._get_segment(msg, "PID")
        mrn = self._safe_field(pid, 3)
        if not mrn:
            raise ValueError("Missing required MRN in PID.3")
        
        # Extract OBR segment for test date
        obr = self._get_segment(msg, "OBR")
        creatinine_date_str = self._safe_field(obr, 7)
        creatinine_date = self._parse_datetime(creatinine_date_str)

        # Extract OBX segment for creatinine result
        obx = self._get_segment(msg, "OBX")
        creatinine_result_str = self._safe_field(obx, 5)
        creatinine_result = None
        if creatinine_result_str:
            try:
                creatinine_result = float(creatinine_result_str)
            except ValueError:
                pass

        return CreatinineResult(
            mrn=mrn,
            creatinine_date=creatinine_date,
            creatinine_result=creatinine_result
        )

    def parse(self, hl7_message: str) -> Optional[object]:
        """
        Parse an HL7 message and return the appropriate typed object.

        Returns:
            PatientInfo | CreatinineResult | None
        """
        try:
            msg = hl7.parse(hl7_message)
            msh = msg.segment("MSH")
            msg_type = self._safe_field(msh, 9)

            if msg_type == MessageType.ADT_A01.value or msg_type == MessageType.ADT_A03.value:
                return self._parse_patient_info(msg)
            
            elif msg_type == MessageType.ORU_R01.value:
                return self._parse_creatinine_result(msg)

            return None

        except Exception as e:
            raise ValueError(f"Failed to parse HL7 message: {e}") from e


async def main():
    """
    Example usage of parsing HL7 messages from an MLLP server.
    """
    parser = HL7Parser()

    async def handler(hl7_message: str) -> None:
        """
        Parse HL7 message and log the result.

        Args:
            hl7_message (str): Received HL7 message.

        Returns:
            None
        """
        try:
            result = parser.parse(hl7_message)

            if result is None:
                logger.warning("Unsupported message type, skipping.")
            elif isinstance(result, PatientInfo):
                logger.info(f"Patient: MRN={result.mrn}, Age={result.age}, Sex={result.sex}")
            elif isinstance(result, CreatinineResult):
                logger.info(f"Creatinine: MRN={result.mrn}, Date={result.creatinine_date}, Result={result.creatinine_result}")

        except ValueError as e:
            logger.error(f"Parse error: {e}")

        return None

    client = MLLPClient(
        host="localhost",
        port=8440,
        message_handler=handler,
    )

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(client.stop()))

    await client.run()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())