import sys
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        sys.path.insert(0, self.root)

        from compiler.api.compiler import start as compile_api
        from compiler.errors.compiler import start as compile_errors

        print("Generating api schema...")
        compile_api()

        print("Generating errors...")
        compile_errors()
