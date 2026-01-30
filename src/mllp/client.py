"""
MLLP Client Module

Connects to a MLLP server, receives HL7 messages, processes them
and sends ACK responses.
"""

import asyncio
import signal
from typing import Optional, Callable, Awaitable
from datetime import datetime
import signal

import hl7

from src.logger import logger

# MLLP Constants (Standard HL7 framing bytes)
MLLP_START_BLOCK = b'\x0b'
MLLP_END_BLOCK = b'\x1c'
MLLP_CARRIAGE_RETURN = b'\x0d'

# Default Configuration
DEFAULT_RECONNECT_DELAY = 5.0
DEFAULT_MAX_MESSAGE_SIZE = 1024 * 1024  # 1 MB

class MLLPClient:
    """
    MLLP HL7 Client implementation.

    Connects to a MLLP server, receives HL7 messages, and sends ACK responses.
    Automatically reconnects on connection loss.
    """
    def __init__(
        self,
        host: str,
        port: int,
        message_handler: Optional[Callable[[str], Awaitable[Optional[str]]]] = None,
        reconnect_delay: float = DEFAULT_RECONNECT_DELAY,
        max_message_size: int = DEFAULT_MAX_MESSAGE_SIZE,
        auto_reconnect: bool = True
    ):
        """
        Initialize the MCP client.

        Args:
            host (str): Server hostname or IP address
            port (int): Server port number
            message_handler (Optional[Callable[[str], Awaitable[Optional[str]]]], optional):
                Async callback for processing HL7 messages. Should return custom ACK message or None for auto-generated ACK.
            reconnect_delay (float, optional): Delay in seconds before reconnecting after disconnection.
            max_message_size (int, optional): Maximum allowed message size in bytes.
            auto_reconnect (bool, optional): Whether to automatically reconnect on connection loss.
        """
        self.host = host
        self.port = port
        self.message_handler = message_handler or self._default_message_handler
        self.reconnect_delay = reconnect_delay
        self.max_message_size = max_message_size
        self.auto_reconnect = auto_reconnect

        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.running = False
        self.is_shutting_down = False

    async def _default_message_handler(self, hl7_message: str) -> Optional[str]:
        """
        Default message handler that logs received HL7 message.

        Args:
            hl7_message (str): Received HL7 message.

        Returns:
            None
        """
        logger.info(f"Received HL7 message:\n{hl7_message}")
        return None
    
    def _parse_mllp_buffer(self, buffer: bytes) -> tuple[list[bytes], bytes]:
        """
        Parse MLLP messages from buffer, handling partial messages.

        Args:
            buffer (bytes): Accumulated buffer bytes.

        Returns:
            tuple[list[bytes], bytes]: Parsed complete messages and remaining buffer.
        """
        messages = []
        idx = 0
        expected = MLLP_START_BLOCK[0]
        consumed = 0

        while idx < len(buffer):
            if expected is not None:
                if buffer[idx] != expected:
                    raise ValueError(f"""Invalid MLLP framing byte encountered.
                                     Expected: {expected}, Found: {hex(buffer[idx])} at position {idx}""")
                
                if expected == MLLP_START_BLOCK[0]:
                    expected = None  # Read until MLLP_END_BLOCK
                    consumed = idx
                elif expected == MLLP_CARRIAGE_RETURN[0]:
                    # Extract message (between start block and end block)
                    message = buffer[consumed+1:idx-1]
                    messages.append(message)
                    expected = MLLP_START_BLOCK[0]
                    consumed = idx + 1
            else:
                if buffer[idx] == MLLP_END_BLOCK[0]:
                    expected = MLLP_CARRIAGE_RETURN[0]

            idx += 1

        return messages, buffer[consumed:]
    
    def _wrap_mllp_message(self, message: bytes) -> bytes:
        """
        Wrap HL7 message with MLLP framing bytes. Mainly for sending MLLP-wrapped ACKs.

        Args:
            message (bytes): HL7 message bytes.

        Returns:
            bytes: MLLP framed message.
        """
        return MLLP_START_BLOCK + message + MLLP_END_BLOCK + MLLP_CARRIAGE_RETURN

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

    def _build_ack_segments(self, msh, ack_code: str, control_id: str) -> str:
        """
        Build a HL7 ACK message string (MSH + MSA) from an MSH segment.

        Args:
            msh: Parsed MSH segment from the original message.
            ack_code (str): ACK code to include (AA/AE/AR).
            control_id (str): Message Control ID for MSA-2 and MSH-10.

        Returns:
            str: HL7 ACK message with segment separators and trailing carriage return.
        """
        msh_fields = [
            "MSH",  # Segment name
            "^~\\&",  # Encoding characters (MSH-2)
            self._safe_field(msh, 5),  # Receiving Application (becomes Sending Application)
            self._safe_field(msh, 6),  # Receiving Facility (becomes Sending Facility)
            self._safe_field(msh, 3),  # Sending Application (becomes Receiving Application)
            self._safe_field(msh, 4),  # Sending Facility (becomes Receiving Facility)
            datetime.now().strftime("%Y%m%d%H%M%S"),  # Message timestamp
            "",  # Security
            "ACK",  # Message type
            control_id,  # Message Control ID (same as original)
            self._safe_field(msh, 11, "P"),  # Processing ID
            self._safe_field(msh, 12, "2.5")  # Version ID
        ]

        msa_fields = [
            "MSA",
            ack_code,  # Acknowledgment code
            control_id
        ]

        msh_segment = "|".join(msh_fields)
        msa_segment = "|".join(msa_fields)

        return "\r".join([msh_segment, msa_segment]) + "\r"
    
    def _generate_ack(self, hl7_message: str, ack_code: str = "AA") -> str:
        """
        Generate HL7 ACK message.

        Args:
            hl7_message (str): Original HL7 message.
            ack_code (str, optional): ACK code to include in the ACK message.
                - AA=Application Accept
                - AE=Application Error
                - AR=Application Reject

        Returns:
            str: HL7 ACK message.
        """
        try:
            # Parse original message to extract MSH fields
            msg = hl7.parse(hl7_message)
            msh = msg.segment("MSH")

            control_id = self._safe_field(msh, 10, "UNKNOWN")

            return self._build_ack_segments(msh, ack_code, control_id)

        except Exception as e:
            logger.error(f"Failed to generate ACK message: {e}", exc_info=True)
            # Return a minimal ACK in case of failure
            msh_fields = [
                "MSH",
                "^~\\&",
                "",
                "",
                "",
                "",
                datetime.now().strftime("%Y%m%d%H%M%S"),
                "",
                "ACK",
                "ERROR",
                "P",
                "2.5"
            ]
            msa_fields = ["MSA", "AE", "ERROR"]
            msh_segment = "|".join(msh_fields)
            msa_segment = "|".join(msa_fields)
            return "\r".join([msh_segment, msa_segment]) + "\r"
        
    async def _connect(self) -> bool:
        """
        Connect to MLLP server.

        Returns:
            bool: True if successfully connected, False otherwise.
        """
        try:
            logger.info(f"Connecting to MLLP server at {self.host}:{self.port}...")
            self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
            logger.info("Connected to MLLP server.")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to MLLP server: {e}")
            return False
        
    async def _disconnect(self):
        """
        Disconnect from MLLP server.

        Returns:
            None
        """
        if self.writer:
            try:
                logger.info("Disconnecting from MLLP server...")
                self.writer.close()
                await self.writer.wait_closed()
                logger.info("Disconnected from MLLP server.")
            except Exception as e:
                logger.error(f"Error during disconnection: {e}")
            finally:
                self.reader = None
                self.writer = None
        logger.info("Disconnected from MLLP server.")

        return None

    async def _process_messages(self):
        """
        To receive messages and send ACKs. Handles partial messages that
        may be split across multiple receiving messages.

        Returns:
            None
        """
        buffer = b""
        while self.running and not self.is_shutting_down:
            try:
                # Read data from server
                data = await self.reader.read(self.max_message_size)

                if not data:
                    logger.warning("Connection closed by server.")
                    break

                # Append data to buffer and parse
                buffer += data
                messages, buffer = self._parse_mllp_buffer(buffer)

                # Process each complete message
                for hl7_message_bytes in messages:
                    try:
                        hl7_message = hl7_message_bytes.decode('utf-8')
                    except UnicodeDecodeError as e:
                        logger.error(f"Failed to decode HL7 message: {e}")
                        continue

                    logger.debug(f"Received HL7 message:\n{hl7_message}")

                    # Process message via handler
                    ack_code = "AA"
                    try:
                        custom_ack = await self.message_handler(hl7_message)
                    except Exception as e:
                        logger.error(f"Error in message handler: {e}")
                        ack_code = "AE" # Force Application Error ACK
                        custom_ack = None

                    # Generate ACK if handler returned None
                    if custom_ack:
                        ack_message = custom_ack
                    else:
                        ack_message = self._generate_ack(hl7_message, ack_code)

                    # Send ACK back to server
                    self.writer.write(self._wrap_mllp_message(ack_message.encode('utf-8')))
                    await self.writer.drain()
                    logger.debug(f"Sent ACK message:\n{ack_message}")

            except ValueError as e:
                logger.error(f"MLLP framing error: {e}")
                break
            except asyncio.CancelledError:
                logger.info("Message processing task cancelled.")
                break
            except Exception as e:
                logger.error(f"Error during message processing: {e}", exc_info=True)
                break
    
        return None

    async def run(self):
        """
        Run client with automatic reconnection.

        Connects to server and processes messages. If connection is lost
        and auto_reconnect enabled, attempt to reconnect after a delay.
        
        Returns:
            None
        """
        self.running = True

        while self.running and not self.is_shutting_down:
            # Connect to server
            if not await self._connect():
                if self.auto_reconnect:
                    logger.info(f"Reconnecting in {self.reconnect_delay} seconds...")
                    await asyncio.sleep(self.reconnect_delay)
                    continue
                else:
                    break

            # Receive and process messages
            try:
                await self._process_messages()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Unexpected error: {e}", exc_info=True)

            # Disconnect from server
            await self._disconnect()

            # Reconnect if enabled
            if self.auto_reconnect and not self.is_shutting_down:
                logger.info(f"Reconnecting in {self.reconnect_delay} seconds...")
                await asyncio.sleep(self.reconnect_delay)
            else:
                break

        self.running = False
        logger.info("MLLP client stopped.")
        
        return None

    async def stop(self):
        """
        Gracefully stop the client.
        
        Returns:
            None
        """
        logger.info("Stopping MLLP client...")
        self.is_shutting_down = True
        self.running = False
        
        # Disconnect if currently connected
        if self.writer:
            await self._disconnect()
        
        logger.info("MLLP client stopped.")

async def main():
    """
    Example usage of the MLLP client.
    """
    # Custom message handler example
    async def custom_handler(hl7_message: str) -> Optional[str]:
        """
        Process HL7 message and optionally return custom ACK.
        
        Args:
            hl7_message (str): Received HL7 message.

        Returns:
            Optional[str]: Custom ACK message or None for auto-generated ACK.
        """
        try:
            msg = hl7.parse(hl7_message)
            msh = msg.segment('MSH')

            def _safe_field(segment, index: int, default: str = "") -> str:
                try:
                    value = segment[index]
                    return str(value) if value is not None else default
                except Exception:
                    return default

            def _segment_name(segment) -> str:
                try:
                    return str(segment[0])
                except Exception:
                    return ""

            def _iter_segments(message, name: str):
                segments = []
                try:
                    segments = message.segments(name)
                except Exception:
                    segments = []
                if segments:
                    for segment in segments:
                        yield segment
                else:
                    for segment in message:
                        if _segment_name(segment) == name:
                            yield segment

            def _is_creatinine(obx3: str) -> bool:
                candidate = (obx3 or "").upper()
                return "CREATININE" in candidate or "CREAT" in candidate

            logger.info(f"Message Type: {_safe_field(msh, 9)}")
            control_id = _safe_field(msh, 10)
            if control_id:
                logger.info(f"Control ID: {control_id}")
            else:
                logger.info("Control ID: ")
            
            # Example: Extract patient info if it's an ADT message
            if 'ADT' in str(_safe_field(msh, 9)):
                try:
                    pid = msg.segment('PID')
                    patient_id = _safe_field(pid, 3)
                    patient_name = _safe_field(pid, 5)
                    if patient_id:
                        logger.info(f"Patient ID: {patient_id}")
                    if patient_name:
                        logger.info(f"Patient Name: {patient_name}")
                    if not patient_id and not patient_name:
                        logger.warning("Could not extract patient info: missing PID fields")
                except Exception as e:
                    logger.warning(f"Could not extract patient info: {e}")

            # Extract creatinine test result if it's an ORU^R01 message
            if 'ORU^R01' in str(_safe_field(msh, 9)):
                creatinine_found = False
                for obx in _iter_segments(msg, 'OBX'):
                    obx3 = _safe_field(obx, 3)
                    if not _is_creatinine(obx3):
                        continue
                    value = _safe_field(obx, 5)
                    units = _safe_field(obx, 6)
                    status = _safe_field(obx, 11)
                    logger.info(
                        f"Creatinine Result: {value} {units} (status: {status})"
                    )
                    creatinine_found = True
                if not creatinine_found:
                    logger.warning("Creatinine result not found in ORU^R01 message")
            
            # Return None to use automatic ACK generation
            return None
            
        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)
            return None
    
    # Create client
    client = MLLPClient(
        host='localhost',  # Connect to simulator
        port=8440,         # Default MLLP port in simulator
        message_handler=custom_handler,
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
    await client.run()


if __name__ == '__main__':
    asyncio.run(main())