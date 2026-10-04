# SPDX-License-Identifier: AGPL-3.0-or-later
"""Manual experiment: ask the vision LLM for the bounding box of a given text in an image.

Usage:  python scripts/test_box.py path/to/crop.jpg "123.456.789-09"
(Run from the repository root. Requires a running Ollama server. Not part of the test suite.)
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.ai_client import OllamaClient  # noqa: E402

if len(sys.argv) < 2:
    sys.exit(__doc__)

img_path = sys.argv[1]
target = sys.argv[2] if len(sys.argv) > 2 else "123.456.789-09"

ai = OllamaClient()

prompt = f"""
Return the approximate bounding box of the text "{target}" in the image.
Provide the values as a list of 4 numbers: [y_min, x_min, y_max, x_max],
relative to the whole image, between 0 and 1000 ([0,0,1000,1000] is the entire image).
Answer with JSON only:
{{
    "bbox": [ymin, xmin, ymax, xmax]
}}
"""

res, _, _ = ai.analyze_image(img_path, prompt)
print(json.dumps(res, indent=4))
