import pytest
import hashlib
from ingest_module.ingestor import calculate_sha256

def test_calculate_sha256_success(tmp_path):
    """Test that calculate_sha256 correctly hashes a file."""
    # Create a temporary file
    p = tmp_path / "test_file.txt"
    content = b"test content for hashing"
    p.write_bytes(content)

    # Calculate expected hash
    expected_hash = hashlib.sha256(content).hexdigest()

    # Run the function
    actual_hash = calculate_sha256(str(p))

    assert actual_hash == expected_hash

def test_calculate_sha256_file_not_found(tmp_path):
    """Test that calculate_sha256 raises FileNotFoundError for missing files."""
    # Using a path within a tmp directory that we know doesn't exist
    non_existent = tmp_path / "does_not_exist.pdf"
    with pytest.raises(FileNotFoundError):
        calculate_sha256(str(non_existent))
