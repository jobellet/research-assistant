from .ingestor import calculate_sha256, process_file

# Attempt to import monitor-related functions, which depend on watchdog
try:
    from .monitor import start_monitoring
except ImportError:
    # watchdog might not be installed in all environments
    pass

__all__ = ["calculate_sha256", "process_file"]
if "start_monitoring" in locals():
    __all__.append("start_monitoring")
