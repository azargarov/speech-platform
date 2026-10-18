"""Production STT worker process entry point."""

from services.worker.server import main

if __name__ == "__main__":
    main("stt")
