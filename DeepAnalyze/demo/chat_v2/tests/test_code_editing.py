import unittest
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "backend_app"
    / "services"
    / "code_editing.py"
)
spec = spec_from_file_location("code_editing_service", MODULE_PATH)
code_editing_service = module_from_spec(spec)
assert spec is not None
assert spec.loader is not None
sys.modules["code_editing_service"] = code_editing_service
spec.loader.exec_module(code_editing_service)
extract_modified_code = code_editing_service.extract_modified_code


class ExtractModifiedCodeTest(unittest.TestCase):
    def test_extracts_modified_code_tag(self):
        response = """
说明文字
<ModifiedCode>
print("hello")
print("world")
</ModifiedCode>
"""

        self.assertEqual(
            extract_modified_code(response),
            'print("hello")\nprint("world")',
        )

    def test_extracts_markdown_code_block(self):
        response = """
下面是修改后的代码：
```python
value = 1
print(value)
```
"""

        self.assertEqual(
            extract_modified_code(response),
            "value = 1\nprint(value)",
        )

    def test_accepts_plain_code_response(self):
        response = "import pandas as pd\nprint(pd.__version__)\n"

        self.assertEqual(
            extract_modified_code(response),
            "import pandas as pd\nprint(pd.__version__)",
        )

    def test_rejects_empty_response(self):
        with self.assertRaises(ValueError):
            extract_modified_code("   ")


if __name__ == "__main__":
    unittest.main()
