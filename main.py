"""System entrypoint for AKI inference pipeline."""

import asyncio
import os
import signal
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from src.database.patient import PatientDB
from src.hl7.parser import HL7Parser, PatientInfo, CreatinineResult
from src.logger import logger
from src.model.aki import AKIClassifier
from src.mllp.client import MLLPClient
from src.pager.pager import Pager

DEFAULT_MLLP_ADDRESS = "localhost:8440"
DEFAULT_PAGER_ADDRESS = "localhost:8441"
DEFAULT_DB_PATH = "data/patient.db"
DEFAULT_HISTORY_CSV = "/data/history.csv"
DEFAULT_TRAINING_CSV = "/data/training.csv"


def _parse_host_port(address: str) -> tuple[str, int]:
    if not address:
        raise ValueError("MLLP_ADDRESS is required")

    if "://" in address:
        parsed = urlparse(address)
        if not parsed.hostname or not parsed.port:
            raise ValueError(f"Invalid MLLP_ADDRESS: {address}")
        return parsed.hostname, parsed.port

    if ":" not in address:
        raise ValueError(f"Invalid MLLP_ADDRESS: {address}")

    host, port_str = address.rsplit(":", 1)
    if not host or not port_str:
        raise ValueError(f"Invalid MLLP_ADDRESS: {address}")

    return host, int(port_str)


def _build_pager_url(address: str) -> str:
    if not address:
        raise ValueError("PAGER_ADDRESS is required")

    if "://" not in address:
        address = f"http://{address}"

    parsed = urlparse(address)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid PAGER_ADDRESS: {address}")

    path = parsed.path or "/page"
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def _resolve_history_csv() -> Optional[str]:
    candidates = [
        os.getenv("HISTORY_CSV"),
        DEFAULT_HISTORY_CSV,
        "simulator/history.csv",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return candidates[0] or DEFAULT_HISTORY_CSV


def _resolve_training_csv() -> str:
    candidates = [
        os.getenv("TRAINING_CSV"),
        DEFAULT_TRAINING_CSV,
        "data/training.csv",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    raise FileNotFoundError(
        "Training CSV not found. Set TRAINING_CSV or provide /data/training.csv."
    )


async def run() -> None:
    mllp_address = os.getenv("MLLP_ADDRESS", DEFAULT_MLLP_ADDRESS)
    pager_address = os.getenv("PAGER_ADDRESS", DEFAULT_PAGER_ADDRESS)
    db_path = os.getenv("DB_PATH", DEFAULT_DB_PATH)

    host, port = _parse_host_port(mllp_address)
    pager_url = _build_pager_url(pager_address)

    history_csv = _resolve_history_csv()
    training_csv = _resolve_training_csv()

    # Log configurations for visibility
    logger.info(f"MLLP Address: {host}:{port}")
    logger.info(f"Pager URL: {pager_url}")
    logger.info(f"Database Path: {db_path}")
    logger.info(f"History CSV: {history_csv}")
    logger.info(f"Training CSV: {training_csv}")

    db = PatientDB(db_path=db_path)
    db.load_csv(history_csv)

    classifier = AKIClassifier(patient_db=db)
    classifier.train(csv_path=training_csv)

    parser = HL7Parser()
    pager = Pager(pager_url, payload_format="csv")

    async def handle_message(hl7_message: str) -> Optional[str]:
        try:
            result = parser.parse(hl7_message)

            if result is None:
                logger.debug("Unsupported message type, skipping.")
                return None

            if isinstance(result, PatientInfo):
                db.upsert_patient(result)
                logger.info(f"Updated patient demographics: MRN={result.mrn}")
                return None

            if isinstance(result, CreatinineResult):
                db.insert_creatinine(result)
                logger.info(
                    f"Inserted creatinine for MRN={result.mrn}: {result.creatinine_result}"
                )

                prediction = classifier.predict(result.mrn)
                if prediction == "y":
                    prediction_time = None
                    if result.creatinine_date:
                        prediction_time = result.creatinine_date.strftime("%Y%m%d%H%M%S")
                    success = await asyncio.to_thread(
                        pager.page, result.mrn, prediction_time
                    )
                    if success:
                        logger.warning(
                            f"AKI ALERT: Paged for MRN={result.mrn} at {prediction_time}"
                        )
                    else:
                        logger.error(f"Failed to page for MRN={result.mrn}")
                else:
                    logger.info(f"AKI prediction for {result.mrn}: negative")

        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)

        return None

    client = MLLPClient(
        host=host,
        port=port,
        message_handler=handle_message,
        reconnect_delay=5.0,
        auto_reconnect=True,
    )

    loop = asyncio.get_running_loop()

    def signal_handler() -> None:
        logger.info("Received shutdown signal")
        asyncio.create_task(client.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    logger.info("Starting AKI inference pipeline...")
    try:
        await client.run()
    finally:
        db.close()
        logger.info("AKI inference pipeline stopped.")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
