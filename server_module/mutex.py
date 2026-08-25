import os
import socket
import atexit
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class ServerMutex:
    def __init__(self, lock_file: str = "server.lock"):
        self.lock_path = Path(lock_file)
        self.is_owner = False

    def acquire(self) -> bool:
        """
        Attempt to acquire the lock. Returns True if successful, False otherwise.
        """
        if self.lock_path.exists():
            try:
                with open(self.lock_path, "r") as f:
                    content = f.read().strip()
                
                if content:
                    pid, hostname = content.split(":")
                    pid = int(pid)
                    
                    # Check if the process is still alive on the same host
                    if hostname == socket.gethostname():
                        try:
                            os.kill(pid, 0)
                            logger.error(f"Server is already running on this host (PID: {pid}).")
                            return False
                        except OSError:
                            # Process is dead, can steal the lock
                            logger.warning(f"Found stale lock file for PID {pid}. Cleaning up.")
                    else:
                        logger.warning(f"Lock file exists from another host: {hostname}. Proceed with caution.")
            except Exception as e:
                logger.error(f"Error reading lock file: {e}. Attempting recovery.")

        # Create/Overwirte the lock file
        try:
            with open(self.lock_path, "w") as f:
                f.write(f"{os.getpid()}:{socket.gethostname()}")
            
            self.is_owner = True
            atexit.register(self.release)
            logger.info(f"Acquired lock file at {self.lock_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to create lock file: {e}")
            return False

    def release(self):
        """Release the lock if held."""
        if self.is_owner and self.lock_path.exists():
            self.lock_path.unlink()
            logger.info(f"Released lock file at {self.lock_path}")
            self.is_owner = False

if __name__ == "__main__":
    # Test
    logging.basicConfig(level=logging.INFO)
    mutex = ServerMutex("test.lock")
    if mutex.acquire():
        print("Acquired!")
        mutex2 = ServerMutex("test.lock")
        if not mutex2.acquire():
            print("Successfully blocked second instance.")
    mutex.release()
