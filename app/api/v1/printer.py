"""Printer API router for Network LAN IP thermal printers (ESC/POS over TCP socket)."""

import asyncio
import base64
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from app.core.deps import get_current_user
from app.models.user import User

router = APIRouter(prefix="/printer", tags=["Printer"])


class LanPrinterTestRequest(BaseModel):
    ip: str = Field(..., description="Target printer IP address, e.g. 192.168.1.150")
    port: int = Field(9100, description="Printer RAW ESC/POS port, default 9100")
    station_name: Optional[str] = "Kitchen Printer"


class EscposPrintRequest(BaseModel):
    ip: str = Field(..., description="Target printer IP address")
    port: int = Field(9100, description="Printer RAW port (default 9100)")
    raw_base64: Optional[str] = Field(None, description="Base64 encoded ESC/POS binary data")
    text_content: Optional[str] = Field(None, description="Fallback plain text content to format into ESC/POS")
    cut_paper: bool = True
    sound_buzzer: bool = True


def build_test_escpos_buffer(station_name: str) -> bytes:
    """Builds a diagnostic test slip with standard ESC/POS commands."""
    ESC = b'\x1b'
    GS = b'\x1d'

    buf = bytearray()
    buf += ESC + b'@'  # Initialize printer
    buf += ESC + b'a\x01'  # Center alignment
    buf += ESC + b'E\x01'  # Bold ON
    buf += GS + b'!\x11'  # Double height & width
    buf += b'MENUKIT PRINTER TEST\n'
    buf += GS + b'!\x00'  # Normal size
    buf += b'--------------------------------\n'
    buf += ESC + b'E\x00'  # Bold OFF
    buf += f"Station: {station_name}\n".encode('utf-8')
    buf += b"Status: LAN Socket Connected (OK)\n"
    buf += b"Port: 9100 RAW Data Stream\n"
    buf += b"--------------------------------\n"
    buf += ESC + b'a\x00'  # Left alignment
    buf += b"Kitchen thermal printer network link\n"
    buf += b"is verified and working properly!\n"
    buf += b"\n\n\n"
    buf += ESC + b'B\x02\x02'  # Buzzer (2 beeps)
    buf += GS + b'V\x42\x00'  # Full cut with feed
    return bytes(buf)


@router.post("/test-lan")
async def test_lan_printer(
    payload: LanPrinterTestRequest,
    current_user: User = Depends(get_current_user)
):
    """Tests connection to a LAN printer via TCP socket and prints a test slip."""
    ip = payload.ip.strip()
    port = payload.port or 9100

    if not ip:
        raise HTTPException(status_code=400, detail="Printer IP address is required")

    try:
        # Attempt TCP socket connection with 4s timeout
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port),
            timeout=4.0
        )
        test_data = build_test_escpos_buffer(payload.station_name or "Kitchen Printer")
        writer.write(test_data)
        await writer.drain()
        writer.close()
        await writer.wait_closed()
        return {
            "status": "success",
            "message": f"Successfully connected to printer at {ip}:{port} and dispatched test slip."
        }
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail=f"Connection timed out. Printer at {ip}:{port} did not respond. Check printer power, Ethernet/Wi-Fi cable, and IP configuration."
        )
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to connect to printer at {ip}:{port}: {str(e)}"
        )


@router.post("/print-escpos")
async def print_escpos(
    payload: EscposPrintRequest,
    current_user: User = Depends(get_current_user)
):
    """Directly dispatches raw ESC/POS binary data to an in-house network printer."""
    ip = payload.ip.strip()
    port = payload.port or 9100

    if not ip:
        raise HTTPException(status_code=400, detail="Printer IP address is required")

    data_bytes: bytes = b""

    if payload.raw_base64:
        try:
            data_bytes = base64.b64decode(payload.raw_base64)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid base64 payload provided")
    elif payload.text_content:
        ESC = b'\x1b'
        GS = b'\x1d'
        buf = bytearray()
        buf += ESC + b'@'
        if payload.sound_buzzer:
            buf += ESC + b'B\x02\x02'
        buf += payload.text_content.encode('utf-8', errors='replace')
        buf += b"\n\n\n\n"
        if payload.cut_paper:
            buf += GS + b'V\x42\x00'
        data_bytes = bytes(buf)
    else:
        raise HTTPException(status_code=400, detail="Either raw_base64 or text_content must be provided")

    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port),
            timeout=4.0
        )
        writer.write(data_bytes)
        await writer.drain()
        writer.close()
        await writer.wait_closed()
        return {
            "status": "success",
            "bytes_sent": len(data_bytes),
            "ip": ip,
            "port": port
        }
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail=f"Connection timed out. Network printer at {ip}:{port} is unreachable."
        )
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Network printer error on {ip}:{port}: {str(e)}"
        )
