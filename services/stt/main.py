"""STT process entry point; inference is deliberately unavailable in M01."""

from services.worker.server import main

if __name__ == "__main__":
    main("stt")
