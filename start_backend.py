#!/usr/bin/env python3
"""
UART Logger - Backend Entry Point
Uruchamia FastAPI + ApplicationService + UART na Raspberry Pi.

Przeznaczony do uruchomienia na stanowiskach w sieci LAN.
Backend dostępny na porcie 8000 dla wszystkich interfejsów (0.0.0.0).
"""

import logging
import socket
import os
import sys

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_local_ip():
    """Pobiera lokalny adres IP maszyny."""
    try:
        # Trik: połącz się do zewnętrznego IP (nie wysyła pakietów)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def register_mdns_service():
    """
    Opcjonalna rejestracja usługi mDNS dla auto-discovery.
    Wymaga zainstalowania: pip install zeroconf
    """
    try:
        from zeroconf import ServiceInfo, Zeroconf
        import socket
        
        # Informacje o usłudze
        station_id = os.getenv("STATION_ID", socket.gethostname())
        service_type = "_uart-logger._tcp.local."
        service_name = f"{station_id}.{service_type}"
        
        # Rejestracja
        info = ServiceInfo(
            service_type,
            service_name,
            addresses=[socket.inet_aton(get_local_ip())],
            port=8000,
            properties={
                'station_id': station_id,
                'version': '1.0.0'
            }
        )
        
        zeroconf = Zeroconf()
        zeroconf.register_service(info)
        
        logger.info(f"✓ mDNS service registered: {service_name}")
        return zeroconf
        
    except ImportError:
        logger.info("ℹ mDNS auto-discovery disabled (zeroconf not installed)")
        return None
    except Exception as e:
        logger.warning(f"⚠ Failed to register mDNS service: {e}")
        return None


def print_banner():
    """Wyświetla banner informacyjny przy starcie."""
    station_id = os.getenv("STATION_ID", socket.gethostname())
    local_ip = get_local_ip()
    
    print("\n" + "="*70)
    print("🚀 UART LOGGER - BACKEND")
    print("="*70)
    print(f"Station ID:       {station_id}")
    print(f"Hostname:         {socket.gethostname()}")
    print(f"Local IP:         {local_ip}")
    print()
    print("Backend dostępny na:")
    print(f"  • API:          http://{local_ip}:8000")
    print(f"  • API Docs:     http://{local_ip}:8000/docs")
    print(f"  • Health Check: http://{local_ip}:8000/health")
    print()
    print("Aby zatrzymać: Ctrl+C")
    print("="*70 + "\n")


if __name__ == "__main__":
    print_banner()
    
    # Opcjonalna rejestracja mDNS
    zeroconf_instance = register_mdns_service()
    
    try:
        import uvicorn
        
        logger.info("Starting FastAPI backend...")
        
        # Uruchomienie serwera
        uvicorn.run(
            "app.api.main:app",
            host="0.0.0.0",      # Dostępny w sieci LAN
            port=8000,
            log_level="info",
            reload=False         # Stabilność produkcyjna
        )
        
    except KeyboardInterrupt:
        logger.info("\n✓ Backend zatrzymany przez użytkownika (Ctrl+C)")
    except Exception as e:
        logger.error(f"✗ Błąd uruchomienia backendu: {e}")
        sys.exit(1)
    finally:
        # Cleanup mDNS
        if zeroconf_instance:
            try:
                zeroconf_instance.unregister_all_services()
                zeroconf_instance.close()
                logger.info("✓ mDNS service unregistered")
            except Exception:
                pass
