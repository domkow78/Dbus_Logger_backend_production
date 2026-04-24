import serial
import crcmod
import time
import logging
import threading
from enum import Enum
from typing import Optional

"""
DEBUG (10):
Najniższy poziom logowania.
Służy do rejestrowania szczegółowych informacji diagnostycznych, które są przydatne podczas debugowania.
Przykład: logger.debug("This is a debug message.")

INFO (20):
Informacje ogólne o działaniu programu.
Służy do rejestrowania komunikatów, które informują o normalnym działaniu programu.
Przykład: logger.info("Program started successfully.")

WARNING (30):
Ostrzeżenia o potencjalnych problemach, które nie zatrzymują działania programu.
Przykład: logger.warning("Low disk space.")

ERROR (40):
Błędy, które uniemożliwiają wykonanie pewnych operacji, ale program nadal działa.
Przykład: logger.error("Failed to open file.")

CRITICAL (50):
Najwyższy poziom logowania.
Służy do rejestrowania krytycznych błędów, które mogą spowodować zatrzymanie programu.
Przykład: logger.critical("System crash!")

"""

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AckType(Enum):
    OK = 0x0A
    BUSY = 0x03
    WRONG = 0x07

    @staticmethod
    def from_byte(byte: int):
        """
        Decode ACK type from raw ACK byte.
        ACK is identified by lower nibble.
        """
        code = byte & 0x0F
        for ack in AckType:
            if ack.value == code:
                return ack
        return None

class SerialPort(serial.Serial):
    """
    Class to handle serial port communication.
    Extends the `serial.Serial` class to add logging and error handling.
    """
    
    def __init__(self, port, baudrate=9600, bytesize=8, parity=serial.PARITY_NONE, stopbits=1, timeout=1):
        """
        Initialize the serial port with specified settings.

        :param port: Serial port identifier (e.g., 'COM2' for Windows, '/dev/serial0' for Linux).
        :param baudrate: Communication speed in bps. Default is 9600.
        :param bytesize: Number of data bits. Default is 8.
        :param parity: Parity checking. Default is `serial.PARITY_NONE`.
        :param stopbits: Number of stop bits. Default is 1.
        :param timeout: Read timeout in seconds. Default is 1 second.
        """
        super().__init__(port, baudrate, bytesize=bytesize, parity=parity, stopbits=stopbits, timeout=timeout)
        logger.info(f"Serial port {port} initialized with baudrate {baudrate}.")

    def open_port(self):
        """
        Opens the serial port if it is not already open.
        Logs the success or failure of the operation.

        :raises RuntimeError: If the port cannot be opened.
        """
        try:
            if not self.is_open:
                self.open()
                logger.info(f"Port {self.port} opened successfully.")
        except serial.SerialException as e:
            logger.error(f"Error opening port {self.port}: {e}")
            raise RuntimeError(f"Error opening port {self.port}: {e}")

    def is_port_alive(self):
        """
        Checks if the serial port is still alive and accessible.
        
        :return: True if port is alive, False otherwise
        """
        try:
            if not self.is_open:
                return False
            # Sprawdź czy można odczytać in_waiting (test dostępności portu)
            _ = self.in_waiting
            return True
        except (serial.SerialException, OSError):
            return False

    def close(self):
        """
        Close the serial port if it is open.
        Logs the closure of the port.
        """
        if self.is_open:
            super().close()
            logger.info("Connection closed.")

class CRC16XModem:
    """
    Class for calculating CRC16 using the XMODEM protocol.
    """

    @staticmethod
    def calculate(data):
        """
        Calculate the CRC16 checksum for the given data.

        :param data: Data for which to calculate the CRC (bytes or bytearray).
        :return: Calculated CRC value as an integer.
        """
        crc16 = crcmod.mkCrcFun(0x11021, initCrc=0x0000, xorOut=0x0000, rev=False)
        crc = crc16(data)
        logger.debug(f"Calculated CRC16: {crc:04X} for data: {data.hex().upper()}")
        return crc

class Frame:
    """
    Class for creating and parsing data frames.
    """

    @staticmethod
    def create(target_id_data: bytes | bytearray) -> bytearray:
        """
        Create a frame according to protocol specification.

        target_id_data format:
        [ADDR][CMD_H][CMD_L][DATA...]

        LEN = len(CMD + DATA)
        CRC = CRC16 XMODEM calculated from: LEN + ADDR + CMD + DATA
        """

        if len(target_id_data) < 3:
            raise ValueError("target_id_data must contain at least ADDR + CMD")

        addr = target_id_data[0:1]
        cmd_and_data = target_id_data[1:]

        length = len(cmd_and_data)  # CMD (2) + DATA (N)
        len_byte = bytes([length])

        # ✅ CRC over LEN + ADDR + CMD + DATA
        crc = CRC16XModem.calculate(len_byte + addr + cmd_and_data)
        crc_bytes = crc.to_bytes(2, byteorder="big")

        frame = len_byte + addr + cmd_and_data + crc_bytes

        logger.info(
            f"Created frame: {frame.hex().upper()} "
            f"(LEN={length}, CRC={crc:04X})"
        )

        return bytearray(frame)


    @staticmethod
    def parse(frame: bytes | bytearray, check_crc: bool = True):
        """
        Parse a complete frame.

        Frame format:
        [LEN][ADDR][CMD_H][CMD_L][DATA...][CRC_H][CRC_L]

        CRC = CRC16 XMODEM calculated from: LEN + ADDR + CMD + DATA
        """

        if len(frame) < 1 + 1 + 2 + 2:
            raise ValueError("Frame too short")

        length = frame[0]

        expected_len = 1 + 1 + length + 2
        if len(frame) != expected_len:
            raise ValueError(
                f"Frame length mismatch: expected {expected_len}, got {len(frame)}"
            )

        # --- CRC CHECK ---
        crc_received = frame[-2:]
        crc_calculated = CRC16XModem.calculate(
            frame[:-2]  # LEN + ADDR + CMD + DATA
        ).to_bytes(2, byteorder="big")

        if check_crc and crc_received != crc_calculated:
            raise ValueError(
                f"Invalid CRC: received={crc_received.hex().upper()}, "
                f"calculated={crc_calculated.hex().upper()}"
            )

        addr = frame[1]
        cmd = frame[2:4]
        data = frame[4:4 + (length - 2)] if length > 2 else b""

        return {
            "len": length,
            "addr": addr,
            "cmd": cmd,
            "data": data,
            "crc": crc_received,
        }


class UARTHandler:
    """
    Class for handling UART communication.
    Provides methods for sending and receiving data frames.
    """

    def __init__(self, serial_port):
        """
        Initialize UART handler with a serial port.

        :param serial_port: SerialPort object for UART communication.
        """
        self.serial_port = serial_port
        self.buffer = bytearray()
        self.last_activity_time = time.time()
        self.idle_timeout = 0.017

    def send_data(self, target_id_data, timeout=2):
        """
        Sends a data frame over UART, ensuring the line is idle for the required time before transmitting.

        :param target_id_data: Data to send (bytes or bytearray).
        :param timeout: Maximum time to wait for the line to become idle (in seconds). Default is 2 seconds.
        :return: True if data was sent successfully, False otherwise.
        :raises serial.SerialException: If communication error occurs
        """
        try:
            frame = Frame.create(target_id_data)  # Tworzenie ramki
            start_time = time.time()  # Czas rozpoczęcia operacji

            while True:
                now = time.time()

                # 1️⃣ Sprawdzenie timeoutu bezpieczeństwa
                if now - start_time > timeout:
                    logger.error("TX timeout: line never became idle")
                    return False

                # 2️⃣ Sprawdzenie, czy linia była idle przez wymagany czas
                if (now - self.last_activity_time) >= self.idle_timeout:
                    self.serial_port.write(frame)  # Wysyłanie ramki
                    self.last_activity_time = now  # Aktualizacja czasu ostatniej aktywności
                    logger.info(f"TX after idle gap: {frame.hex().upper()}")
                    return True

                # 3️⃣ Krótkie opóźnienie przed kolejną iteracją
                time.sleep(0.001)

        except serial.SerialException as e:
            logger.error(f"Serial communication error in send_data: {e}")
            raise  # Propaguj błąd do wyższego poziomu
        except Exception as e:
            logger.exception(f"Unexpected error in send_data: {e}")
            return False

    def read_data(self, timeout=None):
        """
        Idle-based receiver.
        Collects raw bytes until IDLE GAP occurs,
        then yields ONE complete transaction (bytes).

        :param timeout: Timeout for receiving data (in seconds). Default is None (no timeout).
        :yield: A complete transaction (bytes) or None if timeout occurs.
        :raises serial.SerialException: If communication error occurs
        """
        rx_buffer = bytearray()

        while True:
            now = time.time()

            try:
                if self.serial_port.in_waiting > 0:
                    data = self.serial_port.read(self.serial_port.in_waiting)
                    rx_buffer.extend(data)
                    self.last_activity_time = now

                    logger.debug(
                        f"RX bytes: {data.hex().upper()} | "
                        f"BUFFER={rx_buffer.hex().upper()}"
                    )

                else:
                    # --- IDLE GAP = END OF TRANSACTION ---
                    if rx_buffer and (now - self.last_activity_time) >= self.idle_timeout:
                        transaction = bytes(rx_buffer)
                        rx_buffer.clear()

                        logger.info(
                            f"IDLE detected -> TRANSACTION: {transaction.hex().upper()}"
                        )

                        yield transaction

                # --- Logical timeout (no traffic at all) ---
                if timeout is not None:
                    if (now - self.last_activity_time) >= timeout:
                        logger.warning("Timeout: No data received.")
                        yield None
                        self.last_activity_time = now

                time.sleep(0.001)
                
            except serial.SerialException as e:
                logger.error(f"Serial communication error in read_data: {e}")
                raise  # Propaguj błąd do wyższego poziomu
            except Exception as e:
                logger.exception(f"Unexpected error in read_data: {e}")
                raise


    def decode_transaction(self, data: bytes):
        """
        Decode one UART transaction (bytes between IDLE gaps).

        Rules:
        - Transaction can contain multiple frames
        - ACK can appear ONLY AFTER a valid FRAME
        - CRC is calculated from: LEN + ADDR + CMD + DATA
        - Invalid frames are skipped, decoding continues with next byte
        """

        events = []
        buf = bytearray(data)

        logger.debug(f"Decoding transaction: {buf.hex().upper()}")

        while buf:
            # 1. FRAME (check if current byte could be LEN)
            if len(buf) < 1:
                break

            length = buf[0]

            # Valid LEN range (CMD is 2 bytes minimum)
            if 2 <= length <= 64:
                frame_len = 1 + 1 + length + 2  # LEN + ADDR + CMD+DATA + CRC

                # Check if we have enough bytes for complete frame
                if len(buf) < frame_len:
                    logger.warning(
                        f"Incomplete frame in transaction: "
                        f"expected {frame_len}, have {len(buf)}. "
                        f"Remaining data: {buf.hex().upper()}"
                    )
                    # Don't break - could be trailing data or partial frame
                    # Skip this byte and try next
                    buf.pop(0)
                    continue

                frame = bytes(buf[:frame_len])

                # CRC over LEN + ADDR + CMD + DATA
                crc_received = frame[-2:]
                crc_calculated = CRC16XModem.calculate(
                    frame[:-2]
                ).to_bytes(2, byteorder="big")

                logger.debug(
                    f"FRAME candidate: {frame.hex().upper()} | "
                    f"CRC recv={crc_received.hex().upper()} "
                    f"CRC calc={crc_calculated.hex().upper()}"
                )

                if crc_received != crc_calculated:
                    logger.error(
                        f"CRC FAIL for frame: {frame.hex().upper()}. "
                        f"Skipping {frame_len} bytes and continuing..."
                    )
                    # Przesuń bufor o długość ramki, by nie próbować dekodować środka ramki
                    del buf[:frame_len]
                    continue

                logger.info(f"Frame OK: {frame.hex().upper()}")
                events.append(frame)
                del buf[:frame_len]

                # 2. ACK (ONLY immediately after a FRAME)
                if buf:
                    ack = AckType.from_byte(buf[0])
                    if ack:
                        logger.info(f"ACK_{ack.name} detected")
                        events.append(ack)
                        buf.pop(0)

                continue

            # 3. INVALID BYTE (not a valid LEN)
            logger.warning(
                f"Invalid LEN byte 0x{buf[0]:02X} in transaction, skipping"
            )
            buf.pop(0)

        return events

class ConnectionManager:
    """
    Zarządza połączeniem z portem szeregowym z automatycznym odzyskiwaniem.
    Obsługuje wykrywanie rozłączeń i automatyczne wznawianie połączenia.
    """
    
    def __init__(self, port: str, baudrate: int = 9600, 
                 bytesize: int = 8, parity=serial.PARITY_NONE, 
                 stopbits: int = 1, timeout: float = 1.0,
                 reconnect_enabled: bool = True,
                 reconnect_delay: float = 2.0,
                 max_attempts: int = 0,
                 backoff_enabled: bool = True,
                 max_delay: float = 30.0):
        """
        Inicjalizuje menedżer połączenia.
        
        :param port: Nazwa portu szeregowego
        :param baudrate: Prędkość transmisji
        :param bytesize: Liczba bitów danych
        :param parity: Parzystość
        :param stopbits: Liczba bitów stopu
        :param timeout: Timeout odczytu
        :param reconnect_enabled: Czy włączyć automatyczne wznawianie
        :param reconnect_delay: Początkowe opóźnienie między próbami (sekundy)
        :param max_attempts: Maksymalna liczba prób (0 = nieskończone)
        :param backoff_enabled: Czy zwiększać opóźnienie przy kolejnych próbach
        :param max_delay: Maksymalne opóźnienie między próbami (sekundy)
        """
        self.port_name = port
        self.baudrate = baudrate
        self.bytesize = bytesize
        self.parity = parity
        self.stopbits = stopbits
        self.timeout = timeout
        
        self.reconnect_enabled = reconnect_enabled
        self.reconnect_delay = reconnect_delay
        self.max_attempts = max_attempts
        self.backoff_enabled = backoff_enabled
        self.max_delay = max_delay
        
        self.serial_port: Optional[SerialPort] = None
        self.uart_handler: Optional[UARTHandler] = None
        self._connected = False
        self._reconnect_attempts = 0
        self._lock = threading.Lock()
        
        logger.info(f"ConnectionManager initialized for {port} @ {baudrate} baud")
    
    def connect(self) -> bool:
        """
        Próbuje nawiązać połączenie z portem szeregowym.
        
        :return: True jeśli połączenie udane, False w przeciwnym razie
        """
        with self._lock:
            try:
                # Zamknij poprzednie połączenie jeśli istnieje
                if self.serial_port and self.serial_port.is_open:
                    self.serial_port.close()
                
                # Utwórz nowy port
                self.serial_port = SerialPort(
                    port=self.port_name,
                    baudrate=self.baudrate,
                    bytesize=self.bytesize,
                    parity=self.parity,
                    stopbits=self.stopbits,
                    timeout=self.timeout
                )
                
                # Otwórz port
                self.serial_port.open_port()
                
                # Utwórz UART handler
                self.uart_handler = UARTHandler(self.serial_port)
                
                self._connected = True
                self._reconnect_attempts = 0
                
                logger.info(f"✓ Connected to {self.port_name}")
                return True
                
            except (serial.SerialException, RuntimeError) as e:
                logger.error(f"Failed to connect to {self.port_name}: {e}")
                self._connected = False
                self.serial_port = None
                self.uart_handler = None
                return False
    
    def disconnect(self):
        """Rozłącza połączenie z portem szeregowym."""
        with self._lock:
            if self.serial_port:
                try:
                    self.serial_port.close()
                    logger.info(f"Disconnected from {self.port_name}")
                except Exception as e:
                    logger.error(f"Error during disconnect: {e}")
                finally:
                    self.serial_port = None
                    self.uart_handler = None
                    self._connected = False
    
    def is_connected(self) -> bool:
        """
        Sprawdza czy połączenie jest aktywne.
        
        :return: True jeśli połączony, False w przeciwnym razie
        """
        with self._lock:
            if not self._connected or not self.serial_port:
                return False
            
            # Sprawdź czy port jest nadal dostępny
            if not self.serial_port.is_port_alive():
                logger.warning("Port connection lost")
                self._connected = False
                return False
            
            return True
    
    def attempt_reconnect(self) -> bool:
        """
        Próbuje automatycznie wznowić połączenie.
        Używa exponential backoff jeśli włączony.
        
        :return: True jeśli reconnect udany, False w przeciwnym razie
        """
        if not self.reconnect_enabled:
            logger.info("Auto-reconnect disabled")
            return False
        
        self._reconnect_attempts += 1
        
        # Sprawdź limit prób
        if self.max_attempts > 0 and self._reconnect_attempts > self.max_attempts:
            logger.error(f"Max reconnect attempts ({self.max_attempts}) exceeded")
            return False
        
        # Oblicz opóźnienie z backoff
        if self.backoff_enabled:
            delay = min(
                self.reconnect_delay * (2 ** (self._reconnect_attempts - 1)),
                self.max_delay
            )
        else:
            delay = self.reconnect_delay
        
        logger.info(
            f"Attempting reconnect #{self._reconnect_attempts} "
            f"in {delay:.1f}s..."
        )
        
        time.sleep(delay)
        
        # Próba połączenia
        if self.connect():
            logger.info(f"✓ Reconnected successfully after {self._reconnect_attempts} attempts")
            return True
        else:
            logger.warning(f"Reconnect attempt #{self._reconnect_attempts} failed")
            return False
    
    def get_uart_handler(self) -> Optional[UARTHandler]:
        """
        Zwraca UART handler jeśli połączenie aktywne.
        
        :return: UARTHandler lub None
        """
        with self._lock:
            if self._connected and self.uart_handler:
                return self.uart_handler
            return None
    
    def get_status(self) -> dict:
        """
        Zwraca status połączenia.
        
        :return: Słownik ze statusem
        """
        with self._lock:
            return {
                'connected': self._connected,
                'port': self.port_name,
                'baudrate': self.baudrate,
                'reconnect_enabled': self.reconnect_enabled,
                'reconnect_attempts': self._reconnect_attempts,
            }