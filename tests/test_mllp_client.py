"""
Unit tests for MLLP Client Module
"""

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.mllp.client import (
    MLLPClient,
    MLLP_START_BLOCK,
    MLLP_END_BLOCK,
    MLLP_CARRIAGE_RETURN,
)


def _run(coro):
    return asyncio.run(coro)


class TestMLLPClientParsing:
    """Tests for MLLP buffer parsing."""

    def setup_method(self):
        self.client = MLLPClient(host="localhost", port=8440)

    def test_parse_single_complete_message(self):
        """Parse a single complete MLLP-wrapped message."""
        hl7_content = b"MSH|^~\\&|APP|FAC|||20260126120000||ADT^A01|123|P|2.5"
        buffer = MLLP_START_BLOCK + hl7_content + MLLP_END_BLOCK + MLLP_CARRIAGE_RETURN

        messages, remaining = self.client._parse_mllp_buffer(buffer)

        assert len(messages) == 1
        assert messages[0] == hl7_content
        assert remaining == b""

    def test_parse_multiple_complete_messages(self):
        """Parse multiple complete MLLP messages in one buffer."""
        msg1 = b"MSH|^~\\&|APP|FAC|||20260126120000||ADT^A01|123|P|2.5"
        msg2 = b"MSH|^~\\&|APP|FAC|||20260126120001||ORU^R01|124|P|2.5"

        buffer = (
            MLLP_START_BLOCK + msg1 + MLLP_END_BLOCK + MLLP_CARRIAGE_RETURN +
            MLLP_START_BLOCK + msg2 + MLLP_END_BLOCK + MLLP_CARRIAGE_RETURN
        )

        messages, remaining = self.client._parse_mllp_buffer(buffer)

        assert len(messages) == 2
        assert messages[0] == msg1
        assert messages[1] == msg2
        assert remaining == b""

    def test_parse_partial_message_returns_remaining(self):
        """Incomplete message should remain in buffer."""
        hl7_content = b"MSH|^~\\&|APP|FAC|||20260126120000||ADT^A01|123|P|2.5"
        # Missing end block and carriage return
        buffer = MLLP_START_BLOCK + hl7_content

        messages, remaining = self.client._parse_mllp_buffer(buffer)

        assert len(messages) == 0
        assert remaining == buffer

    def test_parse_empty_buffer(self):
        """Empty buffer returns no messages."""
        messages, remaining = self.client._parse_mllp_buffer(b"")

        assert len(messages) == 0
        assert remaining == b""

    def test_parse_invalid_framing_raises_error(self):
        """Invalid framing byte should raise ValueError."""
        # Buffer starting with wrong byte
        buffer = b"\x00" + b"MSH|^~\\&|"

        with pytest.raises(ValueError, match="Invalid MLLP framing byte"):
            self.client._parse_mllp_buffer(buffer)


class TestMLLPClientWrapping:
    """Tests for MLLP message wrapping."""

    def setup_method(self):
        self.client = MLLPClient(host="localhost", port=8440)

    def test_wrap_mllp_message(self):
        """Wrap a message with MLLP framing bytes."""
        message = b"MSH|^~\\&|APP|FAC|||20260126120000||ACK|123|P|2.5"

        wrapped = self.client._wrap_mllp_message(message)

        assert wrapped.startswith(MLLP_START_BLOCK)
        assert wrapped.endswith(MLLP_END_BLOCK + MLLP_CARRIAGE_RETURN)
        assert message in wrapped


class TestMLLPClientSafeField:
    """Tests for safe field extraction."""

    def setup_method(self):
        self.client = MLLPClient(host="localhost", port=8440)

    def test_safe_field_valid_index(self):
        """Extract valid field by index."""
        segment = MagicMock()
        segment.__getitem__ = MagicMock(return_value="VALUE")

        result = self.client._safe_field(segment, 5)

        assert result == "VALUE"

    def test_safe_field_returns_default_on_none(self):
        """Return default when field is None."""
        segment = MagicMock()
        segment.__getitem__ = MagicMock(return_value=None)

        result = self.client._safe_field(segment, 5, default="DEFAULT")

        assert result == "DEFAULT"

    def test_safe_field_returns_default_on_exception(self):
        """Return default when field access raises exception."""
        segment = MagicMock()
        segment.__getitem__ = MagicMock(side_effect=IndexError("out of range"))

        result = self.client._safe_field(segment, 99, default="FALLBACK")

        assert result == "FALLBACK"


class TestMLLPClientACKGeneration:
    """Tests for ACK message generation."""

    def setup_method(self):
        self.client = MLLPClient(host="localhost", port=8440)

    def test_generate_ack_success(self):
        """Generate ACK for a valid HL7 message."""
        hl7_message = (
            "MSH|^~\\&|SEND_APP|SEND_FAC|RECV_APP|RECV_FAC|20260126120000||ADT^A01|12345|P|2.5\r"
            "PID|1||123456||DOE^JOHN||19800101|M\r"
        )

        ack = self.client._generate_ack(hl7_message, ack_code="AA")

        assert "MSH|" in ack
        assert "MSA|AA|12345" in ack
        assert "ACK" in ack

    def test_generate_ack_error_code(self):
        """Generate ACK with error code."""
        hl7_message = (
            "MSH|^~\\&|SEND_APP|SEND_FAC|RECV_APP|RECV_FAC|20260126120000||ADT^A01|99999|P|2.5\r"
        )

        ack = self.client._generate_ack(hl7_message, ack_code="AE")

        assert "MSA|AE|99999" in ack

    def test_generate_ack_fallback_on_parse_error(self):
        """Fallback ACK when message parsing fails."""
        invalid_message = "NOT_VALID_HL7"

        ack = self.client._generate_ack(invalid_message)

        assert "MSH|" in ack
        assert "MSA|AE|ERROR" in ack


class TestMLLPClientBuildACKSegments:
    """Tests for _build_ack_segments helper."""

    def setup_method(self):
        self.client = MLLPClient(host="localhost", port=8440)

    def test_build_ack_segments_swaps_sender_receiver(self):
        """ACK should swap sending and receiving applications."""
        msh = MagicMock()
        msh.__getitem__ = lambda self, i: {
            3: "SEND_APP",
            4: "SEND_FAC",
            5: "RECV_APP",
            6: "RECV_FAC",
            11: "P",
            12: "2.5",
        }.get(i, "")

        ack = self.client._build_ack_segments(msh, "AA", "CTRL123")

        # Receiving app (index 5) becomes sending app in ACK (field 3)
        # Sending app (index 3) becomes receiving app in ACK (field 5)
        lines = ack.split("\r")
        msh_line = lines[0]
        fields = msh_line.split("|")

        # MSH|^~\&|RECV_APP|RECV_FAC|SEND_APP|SEND_FAC|...
        assert fields[2] == "RECV_APP"  # Sending Application
        assert fields[3] == "RECV_FAC"  # Sending Facility
        assert fields[4] == "SEND_APP"  # Receiving Application
        assert fields[5] == "SEND_FAC"  # Receiving Facility


class TestMLLPClientConnection:
    """Tests for connection handling."""

    def setup_method(self):
        self.client = MLLPClient(host="localhost", port=8440)

    def test_connect_success(self):
        """Successful connection returns True."""
        mock_reader = AsyncMock()
        mock_writer = MagicMock()

        with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
            result = _run(self.client._connect())

        assert result is True
        assert self.client.reader is mock_reader
        assert self.client.writer is mock_writer

    def test_connect_failure(self):
        """Failed connection returns False."""
        with patch("asyncio.open_connection", side_effect=ConnectionRefusedError("refused")):
            result = _run(self.client._connect())

        assert result is False
        assert self.client.reader is None
        assert self.client.writer is None

    def test_disconnect_closes_writer(self):
        """Disconnect closes the writer and clears state."""
        mock_writer = MagicMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        self.client.writer = mock_writer
        self.client.reader = MagicMock()

        _run(self.client._disconnect())

        mock_writer.close.assert_called_once()
        mock_writer.wait_closed.assert_awaited_once()
        assert self.client.writer is None
        assert self.client.reader is None


class TestMLLPClientStop:
    """Tests for graceful shutdown."""

    def setup_method(self):
        self.client = MLLPClient(host="localhost", port=8440)

    def test_stop_sets_shutdown_flag(self):
        """Stop sets shutdown flag and running to False."""
        self.client.running = True
        self.client.is_shutting_down = False

        _run(self.client.stop())

        assert self.client.is_shutting_down is True
        assert self.client.running is False

    def test_stop_disconnects_if_connected(self):
        """Stop disconnects if writer is present."""
        mock_writer = MagicMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        self.client.writer = mock_writer
        self.client.reader = MagicMock()

        _run(self.client.stop())

        mock_writer.close.assert_called_once()


class TestMLLPClientMessageHandler:
    """Tests for message handler invocation."""

    def test_custom_handler_called(self):
        """Custom message handler is invoked with HL7 message."""
        handler = AsyncMock(return_value=None)
        client = MLLPClient(host="localhost", port=8440, message_handler=handler)

        hl7_message = "MSH|^~\\&|APP|FAC|||20260126120000||ADT^A01|123|P|2.5"

        # Simulate processing a message
        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()

        client.reader = mock_reader
        client.writer = mock_writer
        client.running = True

        # Return a complete MLLP message then empty to break loop
        wrapped_msg = MLLP_START_BLOCK + hl7_message.encode() + MLLP_END_BLOCK + MLLP_CARRIAGE_RETURN
        mock_reader.read = AsyncMock(side_effect=[wrapped_msg, b""])

        _run(client._process_messages())

        handler.assert_awaited_once()
        call_args = handler.call_args[0][0]
        assert "MSH|" in call_args
