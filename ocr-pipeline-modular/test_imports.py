#!/usr/bin/env python3
"""Quick test to verify all modules and data classes."""

import sys
from pathlib import Path

try:
    # Test utils imports
    from utils import (
        CharBound, TextBlock, OCROutput, OCRDataHandler,
        ensure_dir, get_output_filename, setup_logging,
        validate_image_path
    )
    print("utils.py imports successful")

    # Test data class creation
    char = CharBound(char='A', x=10, y=20, width=12, height=20, confidence=0.95)
    print(f"CharBound created: {char.char}")

    block = TextBlock(
        text="Test",
        x=10, y=20, width=100, height=30,
        chars=[char],
        confidence=0.9
    )
    print(f"TextBlock created: {block.text}")

    ocr_output = OCROutput(
        image_path="test.jpg",
        dimensions={"width": 1000, "height": 1200},
        blocks=[block]
    )
    print(f"OCROutput created: {len(ocr_output.blocks)} block(s)")

    # Test serialization
    data_dict = ocr_output.to_dict()
    print(f"OCROutput serialized to dict: {len(data_dict)} keys")

    restored = OCROutput.from_dict(data_dict)
    print(f"OCROutput deserialized from dict: {len(restored.blocks)} block(s)")

    print("\nAll module tests passed!")

except Exception as e:
    print(f"Test failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
