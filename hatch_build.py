import sys
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        sys.path.insert(0, self.root)

        from compiler.api.compiler import start as compile_api
        from compiler.errors.compiler import start as compile_errors

        dest_dir = Path(self.directory)

        print("Generating api schema...")
        compile_api(dest_dir / "pyrogram" / "raw")

        print("Generating errors...")
        compile_errors(dest_dir / "pyrogram" / "errors" / "exceptions")

        build_data["force_include"] = {
            "pyrogram/raw": "pyrogram/raw",
            "pyrogram/errors/exceptions": "pyrogram/errors/exceptions",
        }
