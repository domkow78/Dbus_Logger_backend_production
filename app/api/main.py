"""
UART Logger - Main Application
Łączy core logic (ApplicationService) z REST API (FastAPI)
"""

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from datetime import datetime
from typing import Optional, List
import re
import socket

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import serial

from app.core import config
from app.core.uart import ConnectionManager
from app.core.core_app import ApplicationService

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global instances
connection_manager: Optional[ConnectionManager] = None
app_service: Optional[ApplicationService] = None
start_time: float = 0.0  # Track application start time


# =============================================================================
# MODELS
# =============================================================================

class SendFrameRequest(BaseModel):
    """Request do wysłania ramki UART"""
    addr: int = Field(..., ge=0, le=255, description="Adres urządzenia (0-255)")
    cmd_h: int = Field(..., ge=0, le=255, description="Komenda HIGH byte (0-255)")
    cmd_l: int = Field(..., ge=0, le=255, description="Komenda LOW byte (0-255)")
    data: List[int] = Field(default_factory=list, description="Opcjonalne dane (lista bajtów 0-255)")


# =============================================================================
# INITIALIZATION
# =============================================================================

def initialize_uart_and_service():
    """
    Inicjalizuje ConnectionManager i ApplicationService z automatycznym reconnect.
    
    Returns:
        tuple: (connection_manager, app_service)
    
    Raises:
        RuntimeError: Jeśli nie można otworzyć portu
    """
    logger.info("="*70)
    logger.info("INICJALIZACJA UART LOGGER")
    logger.info("="*70)
    
    logger.info(f"System: {config.CURRENT_OS.upper()}")
    logger.info(f"Port: {config.DEFAULT_PORT}")
    logger.info(f"Baudrate: {config.DEFAULT_BAUDRATE}")
    logger.info(f"Auto-reconnect: {'ENABLED' if config.RECONNECT_ENABLED else 'DISABLED'}")
    
    # 1. Utworzenie ConnectionManager
    conn_mgr = ConnectionManager(
        port=config.DEFAULT_PORT,
        baudrate=config.DEFAULT_BAUDRATE,
        parity=config.get_parity_constant(config.DEFAULT_PARITY),
        stopbits=config.DEFAULT_STOPBITS,
        timeout=config.DEFAULT_TIMEOUT,
        reconnect_enabled=config.RECONNECT_ENABLED,
        reconnect_delay=config.RECONNECT_DELAY,
        max_attempts=config.RECONNECT_MAX_ATTEMPTS,
        backoff_enabled=config.RECONNECT_BACKOFF,
        max_delay=config.RECONNECT_MAX_DELAY
    )
    logger.info("✓ Connection Manager utworzony")
    
    # 2. Próba nawiązania połączenia
    if not conn_mgr.connect():
        logger.error("="*70)
        logger.error("✗ BŁĄD: Nie można otworzyć portu szeregowego!")
        logger.error(f"Port: {config.DEFAULT_PORT}")
        logger.error("")
        logger.error("Możliwe rozwiązania:")
        logger.error("  1. Sprawdź czy urządzenie jest podłączone")
        logger.error("  2. Sprawdź czy port nie jest używany przez inną aplikację")
        logger.error("  3. Zmień DEFAULT_PORT w config.py")
        logger.error(f"  4. Dostępne porty: {config.list_available_ports()}")
        logger.error("")
        if config.RECONNECT_ENABLED:
            logger.info("ℹ Auto-reconnect jest włączony - backend będzie próbował połączyć się automatycznie")
            logger.info("  Backend uruchomi się mimo błędu i będzie próbował nawiązać połączenie w tle")
        logger.error("="*70)
        
        if not config.RECONNECT_ENABLED:
            raise RuntimeError(f"Cannot open serial port {config.DEFAULT_PORT} and auto-reconnect is disabled")
    else:
        logger.info(f"✓ Port {config.DEFAULT_PORT} otwarty pomyślnie")
    
    # 3. Utworzenie Application Service
    service = ApplicationService(conn_mgr)
    logger.info("✓ Application Service utworzony")
    
    # 4. Uruchomienie wątków
    service.start()
    logger.info("✓ Application Service uruchomiony (wątki RX i process aktywne)")
    
    logger.info("="*70)
    logger.info("✓ INICJALIZACJA ZAKOŃCZONA POMYŚLNIE")
    logger.info("="*70)
    
    return conn_mgr, service


# =============================================================================
# FASTAPI LIFESPAN
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Zarządzanie cyklem życia aplikacji FastAPI.
    Startup: inicjalizacja UART i service
    Shutdown: zamknięcie połączeń
    """
    global connection_manager, app_service, start_time
    
    # STARTUP
    logger.info("Starting FastAPI application...")
    start_time = time.time()  # Track start time
    
    try:
        connection_manager, app_service = initialize_uart_and_service()
    except Exception as e:
        logger.critical(f"Failed to initialize: {e}")
        raise
    
    logger.info("FastAPI ready - API endpoints available")
    
    # Aplikacja działa...
    yield
    
    # SHUTDOWN
    logger.info("="*70)
    logger.info("SHUTDOWN - Zamykanie aplikacji...")
    logger.info("="*70)
    
    if app_service:
        try:
            logger.info("Zatrzymywanie Application Service...")
            app_service.stop()
            logger.info("✓ Application Service zatrzymany")
        except Exception as e:
            logger.error(f"Błąd podczas zatrzymywania service: {e}")
    
    if connection_manager:
        try:
            logger.info("Zamykanie połączenia UART...")
            connection_manager.disconnect()
            logger.info("✓ Połączenie UART zamknięte")
        except Exception as e:
            logger.error(f"Błąd podczas zamykania połączenia: {e}")
    
    logger.info("="*70)
    logger.info("✓ SHUTDOWN ZAKOŃCZONY")
    logger.info("="*70)


# =============================================================================
# FASTAPI APP
# =============================================================================

app = FastAPI(
    title="UART Logger API",
    description="REST API dla aplikacji do logowania komunikacji UART z detekcją cykli",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware to allow web GUI access (NiceGUI on different port)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# ENDPOINTS
# =============================================================================

@app.get("/", response_class=HTMLResponse)
async def root():
    """
    API info page - JSON API with separate NiceGUI
    """
    return """
    <html>
        <head>
            <title>UART Logger API</title>
            <style>
                body { 
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
                    max-width: 900px; 
                    margin: 50px auto; 
                    padding: 20px; 
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    min-height: 100vh;
                }
                .container {
                    background: white;
                    padding: 40px;
                    border-radius: 10px;
                    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
                }
                h1 { color: #667eea; margin-top: 0; }
                h2 { color: #764ba2; border-bottom: 2px solid #e5e7eb; padding-bottom: 10px; }
                a { color: #667eea; text-decoration: none; font-weight: 600; }
                a:hover { text-decoration: underline; }
                .endpoints { 
                    background: #f9fafb; 
                    padding: 20px; 
                    border-radius: 8px; 
                    border-left: 4px solid #667eea;
                }
                .endpoints p { margin: 10px 0; }
                .note { 
                    background: #dbeafe; 
                    padding: 20px; 
                    border-left: 4px solid #3b82f6; 
                    margin: 20px 0; 
                    border-radius: 4px;
                }
                .note strong { color: #1e40af; }
                code {
                    background: #1f2937;
                    color: #10b981;
                    padding: 4px 8px;
                    border-radius: 4px;
                    font-family: 'Courier New', monospace;
                }
                .status {
                    display: inline-block;
                    background: #d1fae5;
                    color: #065f46;
                    padding: 4px 12px;
                    border-radius: 12px;
                    font-weight: 600;
                    font-size: 0.9em;
                }
                ul { list-style: none; padding: 0; }
                ul li { 
                    padding: 10px; 
                    margin: 5px 0; 
                    background: #f3f4f6; 
                    border-radius: 6px;
                    transition: all 0.2s;
                }
                ul li:hover { background: #e5e7eb; transform: translateX(5px); }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>🔌 UART Logger API</h1>
                <p><strong>Version:</strong> 1.0.0</p>
                <p><strong>Status:</strong> <span class="status">✓ Running</span></p>
                
                <div class="note">
                    <strong>💡 GUI (NiceGUI):</strong> Uruchom osobno na porcie 8080:<br>
                    <code>python gui_nicegui.py</code> (produkcja) lub 
                    <code>python demo_ngui.py</code> (demo)
                </div>
                
                <h2>📚 Quick Links</h2>
                <ul>
                    <li>📖 <a href="/docs">API Documentation (Swagger UI)</a></li>
                    <li>📄 <a href="/redoc">API Documentation (ReDoc)</a></li>
                    <li>📋 <a href="/api">API Info (JSON)</a></li>
                    <li>� <a href="/health">Health Check (JSON)</a></li>
                    <li>�📊 <a href="/status">Status (JSON)</a></li>
                </ul>
                
                <h2>🔌 Available Endpoints</h2>
                <div class="endpoints">
                    <p><strong>GET /health</strong> - Health check stanowiska (station_id, UART status, uptime)</p>
                    <p><strong>GET /status</strong> - Status aplikacji i cyklu</p>
                    <p><strong>GET /logs</strong> - Lista plików logów cykli</p>
                    <p><strong>GET /logs/{filename}</strong> - Zawartość logu (JSON)</p>
                    <p><strong>GET /logs/{filename}/download</strong> - Pobierz plik logu</p>
                    <p><strong>POST /uart/send</strong> - Wyślij ramkę UART</p>
                </div>
            </div>
        </body>
    </html>
    """


@app.get("/api")
async def api_info():
    """
    API Information endpoint (JSON)
    """
    return {
        "name": "UART Logger API",
        "version": "1.0.0",
        "status": "running",
        "description": "REST API dla monitoringu i kontroli aplikacji UART Logger",
        "gui": {
            "type": "NiceGUI",
            "note": "Run separately: python gui_nicegui.py (port 8080)"
        },
        "endpoints": {
            "health": "GET /health - Health check stanowiska",
            "status": "GET /status - Status aplikacji",
            "logs": "GET /logs - Lista plików logów",
            "log_content": "GET /logs/{filename} - Zawartość logu",
            "log_download": "GET /logs/{filename}/download - Pobierz log",
            "send_frame": "POST /uart/send - Wysłanie ramki UART",
            "docs": "GET /docs - Interaktywna dokumentacja API"
        }
    }


@app.get("/health")
async def health_check():
    """
    Health check endpoint dla monitoringu stanowiska.
    
    Zwraca:
    - station_id: ID stanowiska (z env STATION_ID lub hostname)
    - hostname: Nazwa hosta
    - ip_address: Lokalny adres IP
    - status: Status backendu ('healthy' lub 'unhealthy')
    - uart: Status połączenia UART
    - service: Status ApplicationService
    - timestamp: Timestamp odpowiedzi
    """
    global connection_manager, app_service, start_time
    
    # Podstawowe informacje o stanowisku
    station_id = config.get_station_id()
    hostname = socket.gethostname()
    ip_address = config.get_local_ip()
    
    # Status UART
    if connection_manager:
        conn_status = connection_manager.get_status()
        uart_status = {
            "port": conn_status["port"],
            "connected": conn_status["connected"],
            "baudrate": conn_status["baudrate"],
            "reconnect_enabled": conn_status["reconnect_enabled"],
            "reconnect_attempts": conn_status["reconnect_attempts"]
        }
    else:
        uart_status = {
            "port": config.DEFAULT_PORT,
            "connected": False,
            "baudrate": config.DEFAULT_BAUDRATE,
            "reconnect_enabled": False,
            "reconnect_attempts": 0
        }
    
    # Status ApplicationService
    service_status = {
        "running": app_service.is_running() if app_service else False,
        "uptime_seconds": round(time.time() - start_time, 2) if start_time > 0 else 0,
        "cycles_total": app_service.cycle_counter.get_current() if app_service else 0,
        "in_cycle": app_service.is_in_cycle() if app_service else False
    }
    
    # Określ ogólny status
    # healthy jeśli service działa (connection może być w trakcie reconnect)
    overall_status = "healthy" if service_status["running"] else "unhealthy"
    
    return {
        "status": overall_status,
        "station_id": station_id,
        "hostname": hostname,
        "ip_address": ip_address,
        "uart": uart_status,
        "service": service_status,
        "timestamp": datetime.now().isoformat()
    }


@app.get("/status")
async def get_status():
    """
    Zwraca aktualny status aplikacji.
    
    Zawiera informacje o:
    - Czy aplikacja działa (running)
    - Czy cykl jest aktywny (cycle_active)
    - Numer aktualnego cyklu (current_cycle)
    - Nazwa pliku logu (current_log_filename)
    - Rozmiar kolejki RX (rx_queue_size)
    - Czas ostatniej aktywności (last_activity_time)
    """
    if not app_service:
        raise HTTPException(
            status_code=503,
            detail="Application service not initialized"
        )
    
    status = app_service.get_status()
    
    # Dodaj czytelny timestamp
    status['last_activity_readable'] = datetime.fromtimestamp(
        status['last_activity_time']
    ).strftime('%Y-%m-%d %H:%M:%S')
    
    return status


@app.get("/logs")
async def list_logs():
    """
    Zwraca listę wszystkich plików logów cykli.
    
    Pliki są posortowane od najnowszych (największy numer cyklu).
    """
    logs_dir = Path(config.LOGS_DIR)
    
    if not logs_dir.exists():
        return {
            "logs": [],
            "count": 0,
            "directory": config.LOGS_DIR
        }
    
    log_files = []
    
    for filepath in sorted(logs_dir.glob("cycle_*.txt"), reverse=True):
        stat = filepath.stat()
        
        # Parse cycle number z nazwy pliku
        match = re.match(r'cycle_(\d+)_', filepath.name)
        cycle_num = int(match.group(1)) if match else None
        
        log_files.append({
            "filename": filepath.name,
            "cycle_number": cycle_num,
            "size_bytes": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
            "path": str(filepath)
        })
    
    return {
        "logs": log_files,
        "count": len(log_files),
        "directory": config.LOGS_DIR
    }


@app.get("/logs/{filename}")
async def get_log_content(filename: str):
    """
    Zwraca zawartość konkretnego pliku logu (jako JSON).
    
    Parametry:
    - filename: Nazwa pliku (np. cycle_0001_2026-02-09_14-20-51.txt)
    
    Bezpieczeństwo:
    - Akceptowane tylko pliki pasujące do wzorca cycle_*.txt
    - Blokada path traversal (../)
    """
    # Walidacja nazwy pliku (bezpieczeństwo)
    if not re.match(r'^cycle_.*\.txt$', filename):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid filename format. Expected: cycle_*.txt, got: {filename}"
        )
    
    # Dodatkowa ochrona przed path traversal
    if '..' in filename or '/' in filename or '\\' in filename:
        raise HTTPException(
            status_code=400,
            detail="Invalid filename: path traversal detected"
        )
    
    filepath = Path(config.LOGS_DIR) / filename
    
    if not filepath.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Log file not found: {filename}"
        )
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # Usuń znaki nowej linii z każdej linii
        lines = [line.rstrip('\n\r') for line in lines]
        
        # Policz ramki (linie zaczynające się od timestampu)
        frames_count = sum(1 for line in lines if line and not line.startswith(' '))
        
        # Parsuj cycle number z nazwy pliku (cycle_0087_...)
        cycle_match = re.match(r'cycle_(\d+)_', filename)
        cycle_number = int(cycle_match.group(1)) if cycle_match else 0
        
        return {
            "filename": filename,
            "cycle_number": cycle_number,
            "lines": lines,
            "frames_count": frames_count,
            "size_bytes": filepath.stat().st_size
        }
    
    except Exception as e:
        logger.error(f"Error reading log file {filename}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error reading file: {str(e)}"
        )


@app.get("/logs/{filename}/download")
async def download_log_file(filename: str):
    """
    Pobiera log jako plik (do pobrania przez przeglądarkę).
    
    Parametry:
    - filename: Nazwa pliku (np. cycle_0001_2026-02-09_14-20-51.txt)
    
    Przeglądarka automatycznie pobierze plik zamiast wyświetlać JSON.
    
    Bezpieczeństwo:
    - Akceptowane tylko pliki pasujące do wzorca cycle_*.txt
    - Blokada path traversal (../)
    """
    # Walidacja nazwy pliku (bezpieczeństwo)
    if not re.match(r'^cycle_.*\.txt$', filename):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid filename format. Expected: cycle_*.txt, got: {filename}"
        )
    
    # Ochrona przed path traversal
    if '..' in filename or '/' in filename or '\\' in filename:
        raise HTTPException(
            status_code=400,
            detail="Invalid filename: path traversal detected"
        )
    
    filepath = Path(config.LOGS_DIR) / filename
    
    if not filepath.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Log file not found: {filename}"
        )
    
    # Zwróć jako plik do pobrania
    return FileResponse(
        path=filepath,
        media_type='text/plain',
        filename=filename,
        headers={
            "Content-Disposition": f"attachment; filename={filename}"
        }
    )


@app.post("/uart/send")
async def send_uart_frame(request: SendFrameRequest):
    """
    Wysyła ramkę UART.
    
    Używane głównie do testowania i debugowania.
    Ramka jest automatycznie opakowana (dodawane LEN i CRC).
    
    Parametry:
    - addr: Adres urządzenia (0-255)
    - cmd_h: Bajt HIGH komendy (0-255)
    - cmd_l: Bajt LOW komendy (0-255)
    - data: Opcjonalna lista bajtów danych (każdy 0-255)
    
    Przykład START cyklu:
    {
      "addr": 21,      # 0x15
      "cmd_h": 16,     # 0x10
      "cmd_l": 1,      # 0x01
      "data": [1, 0]   # 0x01 0x00
    }
    """
    if not connection_manager:
        raise HTTPException(
            status_code=503,
            detail="Connection manager not initialized"
        )
    
    # Sprawdź połączenie
    if not connection_manager.is_connected():
        raise HTTPException(
            status_code=503,
            detail="UART not connected. Auto-reconnect in progress..."
        )
    
    uart_handler = connection_manager.get_uart_handler()
    if not uart_handler:
        raise HTTPException(
            status_code=503,
            detail="UART handler not available"
        )
    
    # Walidacja data
    for byte_val in request.data:
        if not (0 <= byte_val <= 255):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid data byte: {byte_val}. Must be 0-255"
            )
    
    # Buduj payload: ADDR + CMD_H + CMD_L + DATA
    try:
        payload = bytes([request.addr, request.cmd_h, request.cmd_l]) + bytes(request.data)
        
        logger.info(f"Sending UART frame: payload={payload.hex().upper()}")
        
        # Wyślij (Frame.create() wywoła się wewnątrz send_data)
        success = uart_handler.send_data(payload, timeout=2)
        
        if success:
            return {
                "success": True,
                "message": "Frame sent successfully",
                "payload_hex": payload.hex().upper(),
                "addr": request.addr,
                "cmd": f"{request.cmd_h:02X}{request.cmd_l:02X}",
                "data_hex": bytes(request.data).hex().upper() if request.data else ""
            }
        else:
            raise HTTPException(
                status_code=500,
                detail="Failed to send frame (timeout waiting for idle line)"
            )
    
    except Exception as e:
        logger.error(f"Error sending frame: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error sending frame: {str(e)}"
        )


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    
    print("\n" + "="*70)
    print("UART LOGGER - Production API")
    print("="*70)
    print(f"API będzie dostępne na: http://localhost:8000")
    print(f"Dokumentacja API: http://localhost:8000/docs")
    print(f"\nGUI (NiceGUI): Uruchom osobno - python gui_nicegui.py")
    print("="*70 + "\n")
    
    uvicorn.run(
        "my_project.api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info"
    )