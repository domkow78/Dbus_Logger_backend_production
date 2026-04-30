"""
Rdzeń aplikacji do logowania komunikacji UART z detekcją cykli.
Architektura bezramowa - czysta logika biznesowa.
"""

import os
import time
import queue
import threading
import logging
import serial
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Callable
from enum import Enum

from .uart import UARTHandler, Frame, AckType, CRC16XModem, ConnectionManager
from . import config

# Konfiguracja loggera modułu
logger = logging.getLogger(__name__)


class CycleCounter:
    """
    Zarządza persystentnym licznikiem cykli.
    Licznik jest zapisywany do pliku i przetrwa restart aplikacji.
    """

    def __init__(self, counter_file: str = config.COUNTER_FILE):
        """
        Inicjalizuje licznik cykli.

        :param counter_file: Ścieżka do pliku z licznikiem
        """
        self.counter_file = counter_file
        self._current = self.load()
        self._lock = threading.Lock()

    def load(self) -> int:
        """
        Wczytuje ostatni numer cyklu z pliku.

        :return: Ostatni numer cyklu lub 0 jeśli plik nie istnieje
        """
        try:
            if os.path.exists(self.counter_file):
                with open(self.counter_file, 'r') as f:
                    value = int(f.read().strip())
                    logger.info(f"Loaded cycle counter: {value}")
                    return value
        except Exception as e:
            logger.error(f"Error loading cycle counter: {e}")
        return 0

    def get_next(self) -> int:
        """
        Zwraca następny numer cyklu i zapisuje go do pliku.

        :return: Następny numer cyklu
        """
        with self._lock:
            self._current += 1
            self._save()
            return self._current

    def get_current(self) -> int:
        """
        Zwraca aktualny numer cyklu bez inkrementacji.

        :return: Aktualny numer cyklu
        """
        with self._lock:
            return self._current

    def _save(self):
        """Zapisuje aktualny licznik do pliku."""
        try:
            # Upewnij się że katalog istnieje
            os.makedirs(os.path.dirname(self.counter_file), exist_ok=True)
            with open(self.counter_file, 'w') as f:
                f.write(str(self._current))
            logger.debug(f"Saved cycle counter: {self._current}")
        except Exception as e:
            logger.error(f"Error saving cycle counter: {e}")


class CycleEvent(Enum):
    """Typy zdarzeń cyklu."""
    STARTED = "cycle_started"
    ENDED = "cycle_ended"


class CycleDetector:
    """
    Wykrywa początek i koniec cyklu na podstawie CMD + DATA w ramkach.
    START: CMD=CYCLE_CMD, DATA=CYCLE_START_DATA
    END:   CMD=CYCLE_CMD, DATA=CYCLE_END_DATA
    """

    def __init__(self, 
                 cycle_cmd: bytes = config.CYCLE_CMD,
                 start_data: bytes = config.CYCLE_START_DATA,
                 end_data: bytes = config.CYCLE_END_DATA):
        """
        Inicjalizuje detektor cykli.

        :param cycle_cmd: Komenda identyfikująca cykl (2 bajty)
        :param start_data: DATA oznaczający start cyklu
        :param end_data: DATA oznaczający koniec cyklu
        """
        self.cycle_cmd = cycle_cmd
        self.start_data = start_data
        self.end_data = end_data
        self.is_active = False

    def check_frame(self, frame_bytes: bytes) -> Optional[CycleEvent]:
        """
        Sprawdza czy ramka zawiera komendę start/stop cyklu.
        Porównuje zarówno CMD jak i DATA.

        :param frame_bytes: Surowa ramka do sprawdzenia
        :return: CycleEvent jeśli wykryto zdarzenie, None w przeciwnym razie
        """
        try:
            # Parsuj ramkę (bez sprawdzania CRC - będzie sprawdzone później)
            parsed = Frame.parse(frame_bytes, check_crc=False)
            cmd = parsed['cmd']
            data = parsed['data']

            # Sprawdź czy to komenda cyklu
            if cmd == self.cycle_cmd:
                # Sprawdź czy to START
                if data == self.start_data:
                    if not self.is_active:
                        self.is_active = True
                        logger.info(f"Cycle START detected: CMD={cmd.hex().upper()}, DATA={data.hex().upper()}")
                        return CycleEvent.STARTED
                    else:
                        logger.warning("Cycle START detected but cycle already active")
                
                # Sprawdź czy to END
                elif data == self.end_data:
                    if self.is_active:
                        self.is_active = False
                        logger.info(f"Cycle END detected: CMD={cmd.hex().upper()}, DATA={data.hex().upper()}")
                        return CycleEvent.ENDED
                    else:
                        logger.warning("Cycle END detected but no active cycle")

        except Exception as e:
            logger.debug(f"Error checking frame for cycle: {e}")

        return None


class LogManager:
    """
    Zarządza plikami logów cykli.
    Obsługuje tworzenie, zapis i zamykanie plików logów.
    """

    def __init__(self, logs_dir: str = config.LOGS_DIR):
        """
        Inicjalizuje menedżer logów.

        :param logs_dir: Katalog do przechowywania logów
        """
        self.logs_dir = logs_dir
        self.current_file: Optional[object] = None
        self.current_filename: Optional[str] = None
        self._lock = threading.Lock()

        # Utwórz katalog jeśli nie istnieje
        os.makedirs(self.logs_dir, exist_ok=True)

        # Wyczyść stare logi cykli
        self._cleanup_old_cycle_logs()
        
    def _cleanup_old_cycle_logs(self):
        """
        Usuwa pliki logów cykli starsze niż LOGS_RETENTION_DAYS.
        """
        try:
            cutoff_date = datetime.now() - timedelta(days=config.LOGS_RETENTION_DAYS)
            for filename in os.listdir(self.logs_dir):
                if filename.startswith("cycle_") and filename.endswith(".txt"):
                    filepath = os.path.join(self.logs_dir, filename)
                    file_time = datetime.fromtimestamp(os.path.getmtime(filepath))
                    if file_time < cutoff_date:
                        os.remove(filepath)
                        logger.info(f"Deleted old cycle log: {filename}")
        except Exception as e:
            logger.error(f"Error cleaning up old cycle logs: {e}")

    def start_new_log(self, cycle_number: int, timestamp: datetime) -> str:
        """
        Tworzy nowy plik logu dla cyklu.

        :param cycle_number: Numer cyklu
        :param timestamp: Timestamp startu cyklu
        :return: Nazwa utworzonego pliku
        """
        with self._lock:
            # Zamknij poprzedni log jeśli istnieje
            if self.current_file:
                self.current_file.close()

            # Generuj nazwę pliku
            time_str = timestamp.strftime("%Y-%m-%d_%H-%M-%S")
            filename = f"cycle_{cycle_number:04d}_{time_str}.txt"
            filepath = os.path.join(self.logs_dir, filename)

            # Otwórz nowy plik
            self.current_file = open(filepath, 'a', encoding='utf-8')
            self.current_filename = filename

            # Nagłówek logu
            header = f"=== CYCLE {cycle_number:04d} LOG ===\n"
            header += f"Started: {timestamp.strftime(config.TIMESTAMP_FORMAT)[:-3]}\n"
            header += "=" * 60 + "\n"
            self.current_file.write(header)
            self.current_file.flush()

            logger.info(f"Started new log: {filename}")
            return filename

    def write_line(self, text: str):
        """
        Zapisuje linię do aktualnego logu.

        :param text: Tekst do zapisania
        """
        with self._lock:
            if self.current_file:
                self.current_file.write(text + '\n')
                self.current_file.flush()

    def write_interruption_note(self, timestamp: datetime, reason: str):
        """
        Zapisuje notatkę o przerwaniu połączenia.

        :param timestamp: Czas przerwania
        :param reason: Powód przerwania
        """
        note = f"\n{'!'*60}\n"
        note += f"INTERRUPTION at {timestamp.strftime(config.TIMESTAMP_FORMAT)[:-3]}\n"
        note += f"Reason: {reason}\n"
        note += f"{'!'*60}\n"
        self.write_line(note)
        logger.warning(f"Logged interruption: {reason}")

    def write_resume_note(self, timestamp: datetime):
        """
        Zapisuje notatkę o wznowieniu połączenia.

        :param timestamp: Czas wznowienia
        """
        note = f"\n{'~'*60}\n"
        note += f"RESUMED at {timestamp.strftime(config.TIMESTAMP_FORMAT)[:-3]}\n"
        note += f"{'~'*60}\n"
        self.write_line(note)
        logger.info("Logged resume")

    def close_log(self):
        """Zamyka aktualny plik logu."""
        with self._lock:
            if self.current_file:
                # Stopka
                footer = "\n" + "=" * 60 + "\n"
                footer += f"Log closed: {datetime.now().strftime(config.TIMESTAMP_FORMAT)[:-3]}\n"
                footer += "=" * 60 + "\n"
                self.current_file.write(footer)
                self.current_file.close()
                logger.info(f"Closed log: {self.current_filename}")
                self.current_file = None
                self.current_filename = None


class AppLogger:
    """
    Zarządza logiem operacyjnym aplikacji (diagnostyka, błędy, eventy).
    """

    def __init__(self, app_log_dir: str = config.APP_LOG_DIR):
        """
        Inicjalizuje logger aplikacyjny.

        :param app_log_dir: Katalog dla logów aplikacyjnych
        """
        self.app_log_dir = app_log_dir
        self._lock = threading.Lock()
        
        # Utwórz katalog
        os.makedirs(self.app_log_dir, exist_ok=True)
        
        # Wyczyść stare logi
        self._cleanup_old_logs()

    def _get_log_file(self) -> str:
        """Zwraca ścieżkę do dzisiejszego pliku logu."""
        today = datetime.now().strftime("%Y-%m-%d")
        return os.path.join(self.app_log_dir, f"app_{today}.log")

    def _write(self, level: str, message: str):
        """Zapisuje wiadomość do logu aplikacyjnego."""
        with self._lock:
            timestamp = datetime.now().strftime(config.TIMESTAMP_FORMAT)[:-3]
            log_line = f"{timestamp} | {level:8} | {message}"
            
            filepath = self._get_log_file()
            with open(filepath, 'a', encoding='utf-8') as f:
                f.write(log_line + '\n')

    def log_startup(self):
        """Loguje start aplikacji."""
        self._write("INFO", "Application started")

    def log_shutdown(self):
        """Loguje zamknięcie aplikacji."""
        self._write("INFO", "Application shutdown")

    def log_error(self, message: str):
        """Loguje błąd."""
        self._write("ERROR", message)

    def log_warning(self, message: str):
        """Loguje ostrzeżenie."""
        self._write("WARNING", message)

    def log_info(self, message: str):
        """Loguje informację."""
        self._write("INFO", message)

    def _cleanup_old_logs(self):
        """Usuwa logi starsze niż APP_LOG_RETENTION_DAYS."""
        try:
            cutoff_date = datetime.now() - timedelta(days=config.APP_LOG_RETENTION_DAYS)
            
            for filename in os.listdir(self.app_log_dir):
                if filename.startswith("app_") and filename.endswith(".log"):
                    filepath = os.path.join(self.app_log_dir, filename)
                    file_time = datetime.fromtimestamp(os.path.getmtime(filepath))
                    
                    if file_time < cutoff_date:
                        os.remove(filepath)
                        logger.info(f"Deleted old app log: {filename}")
        except Exception as e:
            logger.error(f"Error cleaning up old logs: {e}")


# ============================================================================
# FUNKCJE POMOCNICZE FORMATOWANIA
# ============================================================================

def format_frame_compact(frame_dict: dict, direction: str, timestamp: datetime) -> str:
    """
    Formatuje ramkę w kompaktowy jednoliniowy format.

    :param frame_dict: Sparsowana ramka (z Frame.parse)
    :param direction: Kierunek: 'TX' lub 'RX'
    :param timestamp: Timestamp ramki
    :return: Sformatowana linia logu
    """
    time_str = timestamp.strftime(config.TIMESTAMP_FORMAT)[:-3]
    addr = f"{frame_dict['addr']:02X}"
    cmd = frame_dict['cmd'].hex().upper()
    data = frame_dict['data'].hex().upper() if frame_dict['data'] else ""
    crc = frame_dict['crc'].hex().upper()
    
    return (f"{time_str} | {direction:2} | "
            f"LEN={frame_dict['len']:02d} "
            f"ADDR={addr} "
            f"CMD={cmd} "
            f"DATA={data} "
            f"CRC={crc}")


def format_ack_compact(ack_type: AckType, timestamp: datetime) -> str:
    """
    Formatuje ACK w kompaktowy format.

    :param ack_type: Typ ACK (z AckType enum)
    :param timestamp: Timestamp ACK
    :return: Sformatowana linia logu
    """
    time_str = timestamp.strftime(config.TIMESTAMP_FORMAT)[:-3]
    return f"{time_str} | RX | ACK_{ack_type.name}"


def format_crc_error_compact(raw_frame: bytes, timestamp: datetime, 
                             direction: str, error: str) -> str:
    """
    Formatuje ramkę z błędem CRC.

    :param raw_frame: Surowe bajty ramki
    :param timestamp: Timestamp
    :param direction: Kierunek: 'TX' lub 'RX'
    :param error: Opis błędu
    :return: Sformatowana linia logu z oznaczeniem błędu
    """
    time_str = timestamp.strftime(config.TIMESTAMP_FORMAT)[:-3]
    raw_hex = raw_frame.hex().upper()
    return f"{time_str} | {direction:2} | CRC_ERROR | RAW={raw_hex} | {error}"


def decode_frame_to_dict(raw_frame: bytes) -> Optional[dict]:
    """
    Dekoduje surową ramkę do słownika używając Frame.parse.

    :param raw_frame: Surowe bajty ramki
    :return: Słownik z parsed ramką lub None jeśli błąd
    """
    try:
        return Frame.parse(raw_frame, check_crc=False)
    except Exception as e:
        logger.debug(f"Error decoding frame: {e}")
        return None


# ============================================================================
# GŁÓWNA KLASA APLIKACJI
# ============================================================================

class ApplicationService:
    """
    Główna klasa orkiestrująca aplikację logowania UART.
    
    Zarządza:
    - Odbiorem danych z UART (wątek RX)
    - Przetwarzaniem transakcji (wątek process)
    - Wykrywaniem cykli
    - Logowaniem do plików
    - Monitorowaniem stanu połączenia
    - Automatycznym wznawianiem połączenia po błędach
    """

    def __init__(self, connection_manager: ConnectionManager):
        """
        Inicjalizuje serwis aplikacji.

        :param connection_manager: Instancja ConnectionManager do zarządzania połączeniem UART
        """
        self.connection_manager = connection_manager
        
        # Komponenty
        self.cycle_counter = CycleCounter()
        self.cycle_detector = CycleDetector()
        self.log_manager = LogManager()
        self.app_logger = AppLogger()
        
        # Kolejki
        self.rx_queue = queue.Queue(maxsize=1000)
        self.tx_queue = queue.Queue(maxsize=100)  # Dla przyszłego TX
        
        # Stan
        self._running = False
        self._rx_thread: Optional[threading.Thread] = None
        self._process_thread: Optional[threading.Thread] = None
        self.current_cycle: Optional[int] = None
        self.cycle_active = False
        self.last_activity_time = time.time()
        self._status_lock = threading.Lock()
        self._connection_lost = False

    def start(self):
        """Uruchamia serwis aplikacji (wątki RX i przetwarzania)."""
        if self._running:
            logger.warning("ApplicationService already running")
            return

        self._running = True
        self.app_logger.log_startup()
        
        # Uruchom wątki
        self._rx_thread = threading.Thread(target=self._rx_worker, daemon=True)
        self._process_thread = threading.Thread(target=self._process_worker, daemon=True)
        
        self._rx_thread.start()
        self._process_thread.start()
        
        logger.info("ApplicationService started")

    def stop(self):
        """Zatrzymuje serwis aplikacji."""
        if not self._running:
            return

        logger.info("Stopping ApplicationService...")
        self._running = False
        
        # Czekaj na zakończenie wątków
        if self._rx_thread:
            self._rx_thread.join(timeout=5.0)
        if self._process_thread:
            self._process_thread.join(timeout=5.0)
        
        # Zamknij aktywny log
        if self.cycle_active:
            self.log_manager.close_log()
        
        self.app_logger.log_shutdown()
        logger.info("ApplicationService stopped")

    def is_running(self) -> bool:
        """
        Sprawdza czy serwis aplikacji jest uruchomiony.
        
        :return: True jeśli działa, False jeśli zatrzymany
        """
        return self._running

    def is_in_cycle(self) -> bool:
        """
        Sprawdza czy aktualnie trwa cykl logowania.
        
        :return: True jeśli cykl aktywny, False jeśli nie
        """
        return self.cycle_active

    def _rx_worker(self):
        """Wątek odbierający dane z UART i przekazujący do kolejki.
        Obsługuje automatyczne wznawianie połączenia w przypadku błędów."""
        logger.info("RX worker started")
        
        while self._running:
            try:
                # Sprawdź połączenie
                if not self.connection_manager.is_connected():
                    if not self._connection_lost:
                        logger.warning("Connection lost - attempting reconnect...")
                        self._connection_lost = True
                        
                        if self.cycle_active:
                            self.log_manager.write_interruption_note(
                                datetime.now(),
                                "Connection lost - reconnecting..."
                            )
                            self.app_logger.log_error("UART connection lost")
                    
                    # Próba reconnect
                    if self.connection_manager.attempt_reconnect():
                        logger.info("Connection restored")
                        self._connection_lost = False
                        
                        if self.cycle_active:
                            self.log_manager.write_resume_note(datetime.now())
                            self.app_logger.log_info("UART connection restored")
                    else:
                        # Reconnect nieudany - czekaj i spróbuj ponownie
                        time.sleep(1.0)
                        continue
                
                # Pobierz UART handler
                uart_handler = self.connection_manager.get_uart_handler()
                if not uart_handler:
                    time.sleep(0.1)
                    continue
                
                # Odbieraj dane z UART
                for transaction in uart_handler.read_data(timeout=config.INTERRUPTION_TIMEOUT):
                    if not self._running:
                        break
                    
                    # Przekaż transakcję do kolejki przetwarzania
                    try:
                        self.rx_queue.put(transaction, timeout=1.0)
                        self.last_activity_time = time.time()
                    except queue.Full:
                        logger.error("RX queue full, dropping transaction")
                        self.app_logger.log_error("RX queue full")
                        
            except serial.SerialException as e:
                # Błąd komunikacji szeregowej
                logger.error(f"Serial communication error: {e}")
                self._connection_lost = True
                
                if self.cycle_active:
                    self.log_manager.write_interruption_note(
                        datetime.now(),
                        f"Serial error: {e}"
                    )
                    self.app_logger.log_error(f"Serial error: {e}")
                
                # Krótkie opóźnienie przed próbą reconnect
                time.sleep(0.5)
                
            except Exception as e:
                logger.exception(f"RX worker error: {e}")
                self.app_logger.log_error(f"RX worker crashed: {e}")
                time.sleep(1.0)  # Uniknięcie szybkiego zapętlania przy błędach
        
        logger.info("RX worker stopped")

    def _process_worker(self):
        """Wątek przetwarzający transakcje z kolejki."""
        logger.info("Process worker started")
        
        interruption_logged = False
        
        try:
            while self._running:
                # Sprawdź timeout (przerwanie połączenia)
                if self.cycle_active:
                    elapsed = time.time() - self.last_activity_time
                    if elapsed >= config.INTERRUPTION_TIMEOUT:
                        if not interruption_logged:
                            self.log_manager.write_interruption_note(
                                datetime.now(),
                                f"No data for {config.INTERRUPTION_TIMEOUT}s"
                            )
                            self.app_logger.log_warning(
                                f"Connection interrupted (timeout {config.INTERRUPTION_TIMEOUT}s)"
                            )
                            interruption_logged = True
                
                # Pobierz transakcję z kolejki
                try:
                    transaction = self.rx_queue.get(timeout=1.0)
                except queue.Empty:
                    continue
                
                # Jeśli dane wróciły po przerwaniu
                if interruption_logged:
                    self.log_manager.write_resume_note(datetime.now())
                    self.app_logger.log_info("Connection resumed")
                    interruption_logged = False
                
                # Przetwórz transakcję
                if transaction is not None:
                    self._process_transaction(transaction)
                
        except Exception as e:
            logger.exception(f"Process worker error: {e}")
            self.app_logger.log_error(f"Process worker crashed: {e}")
        
        logger.info("Process worker stopped")

    def _process_transaction(self, transaction: bytes):
        """
        Przetwarza pojedynczą transakcję UART.

        :param transaction: Surowe bajty transakcji
        """
        timestamp = datetime.now()
        
        # Pobierz UART handler z connection managera
        uart_handler = self.connection_manager.get_uart_handler()
        if not uart_handler:
            logger.warning("UART handler not available, skipping transaction")
            return
        
        # Dekoduj transakcję na zdarzenia (ramki + ACK)
        events = uart_handler.decode_transaction(transaction)
        
        for event in events:
            # Event może być ramką (bytes) lub ACK (AckType)
            if isinstance(event, bytes):
                self._process_frame(event, timestamp)
            elif isinstance(event, AckType):
                self._process_ack(event, timestamp)

    def _process_frame(self, frame_bytes: bytes, timestamp: datetime):
        """
        Przetwarza pojedynczą ramkę.

        :param frame_bytes: Surowe bajty ramki
        :param timestamp: Timestamp odbioru
        """
        # Sprawdź czy to komenda cyklu
        cycle_event = self.cycle_detector.check_frame(frame_bytes)
        
        if cycle_event == CycleEvent.STARTED:
            self._handle_cycle_start(timestamp)
        elif cycle_event == CycleEvent.ENDED:
            self._handle_cycle_end(timestamp)
        
        # Dekoduj ramkę
        frame_dict = decode_frame_to_dict(frame_bytes)
        
        if frame_dict:
            # Sprawdź CRC
            try:
                Frame.parse(frame_bytes, check_crc=True)
                # CRC OK - formatuj normalnie
                log_line = format_frame_compact(frame_dict, "RX", timestamp)
            except ValueError as e:
                # CRC ERROR
                log_line = format_crc_error_compact(frame_bytes, timestamp, "RX", str(e))
                self.app_logger.log_warning(f"CRC error in frame: {frame_bytes.hex().upper()}")
        else:
            # Nie udało się zdekodować
            log_line = format_crc_error_compact(
                frame_bytes, timestamp, "RX", "Failed to decode frame"
            )
            self.app_logger.log_error(f"Failed to decode frame: {frame_bytes.hex().upper()}")
        
        # Zapisz do logu jeśli cykl aktywny
        if self.cycle_active:
            self.log_manager.write_line(log_line)

    def _process_ack(self, ack_type: AckType, timestamp: datetime):
        """
        Przetwarza ACK.

        :param ack_type: Typ ACK
        :param timestamp: Timestamp odbioru
        """
        log_line = format_ack_compact(ack_type, timestamp)
        
        # Zapisz do logu jeśli cykl aktywny
        if self.cycle_active:
            self.log_manager.write_line(log_line)

    def _handle_cycle_start(self, timestamp: datetime):
        """
        Obsługuje start nowego cyklu.

        :param timestamp: Timestamp startu
        """
        with self._status_lock:
            if self.cycle_active:
                logger.warning("Cycle start detected but cycle already active")
                return
            
            # Pobierz nowy numer cyklu
            self.current_cycle = self.cycle_counter.get_next()
            self.cycle_active = True
            
            # Rozpocznij nowy log
            filename = self.log_manager.start_new_log(self.current_cycle, timestamp)
            
            self.app_logger.log_info(f"Cycle {self.current_cycle} started -> {filename}")
            logger.info(f"Cycle {self.current_cycle} started")

    def _handle_cycle_end(self, timestamp: datetime):
        """
        Obsługuje koniec cyklu.

        :param timestamp: Timestamp końca
        """
        with self._status_lock:
            if not self.cycle_active:
                logger.warning("Cycle end detected but no active cycle")
                return
            
            # Zamknij log
            self.log_manager.close_log()
            
            self.app_logger.log_info(f"Cycle {self.current_cycle} ended")
            logger.info(f"Cycle {self.current_cycle} ended")
            
            self.cycle_active = False

    def get_status(self) -> dict:
        """
        Zwraca aktualny status aplikacji (read-only).

        :return: Słownik ze statusem
        """
        with self._status_lock:
            connection_status = self.connection_manager.get_status()
            return {
                'running': self._running,
                'cycle_active': self.cycle_active,
                'current_cycle': self.current_cycle,
                'current_log_filename': self.log_manager.current_filename,
                'last_activity_time': self.last_activity_time,
                'rx_queue_size': self.rx_queue.qsize(),
                'connection_status': connection_status,
                'connection_lost': self._connection_lost,
            }