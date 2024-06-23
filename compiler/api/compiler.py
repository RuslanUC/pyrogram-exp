#  Pyrogram - Telegram MTProto API Client Library for Python
#  Copyright (C) 2017-present Dan <https://github.com/delivrance>
#
#  This file is part of Pyrogram.
#
#  Pyrogram is free software: you can redistribute it and/or modify
#  it under the terms of the GNU Lesser General Public License as published
#  by the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Pyrogram is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Lesser General Public License for more details.
#
#  You should have received a copy of the GNU Lesser General Public License
#  along with Pyrogram.  If not, see <http://www.gnu.org/licenses/>.

import json
import os
import re
import shutil
from functools import partial
from pathlib import Path
from typing import NamedTuple, List, Tuple, Dict

# from autoflake import fix_code
# from black import format_str, FileMode

HOME_PATH = Path("compiler/api")
DESTINATION_PATH = Path("pyrogram/raw")
NOTICE_PATH = "NOTICE"

SECTION_RE = re.compile(r"---(\w+)---")
LAYER_RE = re.compile(r"//\sLAYER\s(\d+)")
COMBINATOR_RE = re.compile(r"^([\w.]+)#([0-9a-f]+)\s(?:.*)=\s([\w<>.]+);$", re.MULTILINE)
ARGS_RE = re.compile(r"[^{](\w+):([\w?!.<>#]+)")
FLAGS_RE = re.compile(r"flags(\d?)\.(\d+)\?")
FLAGS_RE_2 = re.compile(r"flags(\d?)\.(\d+)\?([\w<>.]+)")
FLAGS_RE_3 = re.compile(r"flags(\d?):#")
INT_RE = re.compile(r"int(\d+)")

CORE_TYPES = ["int", "long", "int128", "int256", "double", "bytes", "string", "Bool", "true"]

WARNING = """
# # # # # # # # # # # # # # # # # # # # # # # #
#               !!! WARNING !!!               #
#          This is a generated file!          #
# All changes made in this file will be lost! #
# # # # # # # # # # # # # # # # # # # # # # # #
""".strip()

__INIT__IMPORTS = """
import sys
from typing import TYPE_CHECKING

try:
    from lazy_imports import LazyImporter
except ImportError:
    LazyImporter = None
""".strip()

LAZY_IMPORT_DICT = """
from importlib import import_module


class LazyLoadDict(dict):
    def __getitem__(self, item: int) -> type:
        mod = dict.__getitem__(self, item)
        if isinstance(mod, str):
            path, name = mod.rsplit(".", 1)
            self[item] = mod = getattr(import_module(path), name)
            return mod
        else:
            return mod
""".strip()

# noinspection PyShadowingBuiltins
open = partial(open, encoding="utf-8")

types_to_constructors = {}
types_to_functions = {}
constructors_to_functions = {}
namespaces_to_types = {}
namespaces_to_constructors = {}
namespaces_to_functions = {}

try:
    with open("docs.json") as f:
        docs = json.load(f)
except FileNotFoundError:
    docs = {
        "type": {},
        "constructor": {},
        "method": {}
    }


class Combinator(NamedTuple):
    section: str
    qualname: str
    namespace: str
    name: str
    id: str
    has_flags: bool
    args: List[Tuple[str, str]]
    qualtype: str
    typespace: str
    type: str


def snake(s: str):
    # https://stackoverflow.com/q/1175208
    s = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", s)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s).lower()


def camel(s: str):
    return "".join([i[0].upper() + i[1:] for i in s.split("_")])


# noinspection PyShadowingBuiltins, PyShadowingNames
def get_type_hint(type: str) -> str:
    is_flag = FLAGS_RE.match(type)
    is_core = False

    if is_flag:
        type = type.split("?")[1]

    if type in CORE_TYPES:
        is_core = True

        if type == "long" or "int" in type:
            type = "int"
        elif type == "double":
            type = "float"
        elif type == "string":
            type = "str"
        elif type in ["Bool", "true"]:
            type = "bool"
        else:  # bytes and object
            type = "bytes"

    if type in ["Object", "!X"]:
        return "TLObject"

    if re.match("^vector", type, re.I):
        is_core = True

        sub_type = type.split("<")[1][:-1]
        type = f"List[{get_type_hint(sub_type)}]"

    if is_core:
        return f"Optional[{type}] = None" if is_flag else type
    else:
        ns, name = type.split(".") if "." in type else ("", type)
        type = f'"raw.base.' + ".".join([ns, name]).strip(".") + '"'

        return f'{type}{" = None" if is_flag else ""}'


def sort_args(args):
    """Put flags at the end"""
    args = args.copy()
    flags = [i for i in args if FLAGS_RE.match(i[1])]

    for i in flags:
        args.remove(i)

    for i in args[:]:
        if re.match(r"flags\d?", i[0]) and i[1] == "#":
            args.remove(i)

    return args + flags


def remove_whitespaces(source: str) -> str:
    """Remove whitespaces from blank lines"""
    lines = source.split("\n")

    for i, _ in enumerate(lines):
        if re.match(r"^\s+$", lines[i]):
            lines[i] = ""

    return "\n".join(lines)


def get_docstring_arg_type(t: str):
    if t in CORE_TYPES:
        if t == "long":
            return "``int`` ``64-bit``"
        elif "int" in t:
            size = INT_RE.match(t)
            return f"``int`` ``{size.group(1)}-bit``" if size else "``int`` ``32-bit``"
        elif t == "double":
            return "``float`` ``64-bit``"
        elif t == "string":
            return "``str``"
        elif t == "true":
            return "``bool``"
        else:
            return f"``{t.lower()}``"
    elif t == "TLObject" or t == "X":
        return "Any object from :obj:`~pyrogram.raw.types`"
    elif t == "!X":
        return "Any function from :obj:`~pyrogram.raw.functions`"
    elif t.lower().startswith("vector"):
        return "List of " + get_docstring_arg_type(t.split("<", 1)[1][:-1])
    else:
        return f":obj:`{t} <pyrogram.raw.base.{t}>`"


def get_references(t: str, kind: str):
    if kind == "constructors":
        t = constructors_to_functions.get(t)
    elif kind == "types":
        t = types_to_functions.get(t)
    else:
        raise ValueError("Invalid kind")

    if t:
        return "\n            ".join(t), len(t)

    return None, 0


# noinspection PyShadowingBuiltins
def start(format: bool = False):
    shutil.rmtree(DESTINATION_PATH / "types", ignore_errors=True)
    shutil.rmtree(DESTINATION_PATH / "functions", ignore_errors=True)
    shutil.rmtree(DESTINATION_PATH / "base", ignore_errors=True)

    with open(HOME_PATH / "source/auth_key.tl") as f1, \
        open(HOME_PATH / "source/sys_msgs.tl") as f2, \
        open(HOME_PATH / "source/main_api.tl") as f3:
        schema = (f1.read() + f2.read() + f3.read()).splitlines()

    with open(HOME_PATH / "template/type.txt") as f1, \
        open(HOME_PATH / "template/combinator.txt") as f2:
        type_tmpl = f1.read()
        combinator_tmpl = f2.read()

    with open(NOTICE_PATH, encoding="utf-8") as f:
        notice = []

        for line in f.readlines():
            notice.append(f"#  {line}".strip())

        notice = "\n".join(notice)

    section = None
    layer = None
    combinators: Dict[str, Combinator] = {}

    for line in schema:
        # Check for section changer lines
        section_match = SECTION_RE.match(line)
        if section_match:
            section = section_match.group(1)
            continue

        # Save the layer version
        layer_match = LAYER_RE.match(line)
        if layer_match:
            layer = layer_match.group(1)
            continue

        combinator_match = COMBINATOR_RE.match(line)
        if combinator_match:
            # noinspection PyShadowingBuiltins
            qualname, id, qualtype = combinator_match.groups()

            namespace, name = qualname.split(".") if "." in qualname else ("", qualname)
            name = camel(name)
            qualname = ".".join([namespace, name]).lstrip(".")

            typespace, type = qualtype.split(".") if "." in qualtype else ("", qualtype)
            type = camel(type)
            qualtype = ".".join([typespace, type]).lstrip(".")

            # Pingu!
            has_flags = not not FLAGS_RE_3.findall(line)

            args: List[Tuple[str, str]] = ARGS_RE.findall(line)

            # Fix arg name being "self" (reserved python keyword)
            for i, item in enumerate(args):
                if item[0] == "self":
                    args[i] = ("is_self", item[1])
                elif item[0] in {"from"}:
                    args[i] = (f"{item[0]}_", item[1])

            combinator = Combinator(
                section=section,
                qualname=qualname,
                namespace=namespace,
                name=name,
                id=f"0x{id}",
                has_flags=has_flags,
                args=args,
                qualtype=qualtype,
                typespace=typespace,
                type=type
            )

            combinators[qualname] = combinator

    for c in combinators.values():
        qualtype = c.qualtype

        if qualtype.startswith("Vector"):
            qualtype = qualtype.split("<")[1][:-1]

        d = types_to_constructors if c.section == "types" else types_to_functions

        if qualtype not in d:
            d[qualtype] = []

        d[qualtype].append(c.qualname)

        if c.section == "types":
            key = c.namespace

            if key not in namespaces_to_types:
                namespaces_to_types[key] = []

            if c.type not in namespaces_to_types[key]:
                namespaces_to_types[key].append(c.type)

    for k, v in types_to_constructors.items():
        for i in v:
            try:
                constructors_to_functions[i] = types_to_functions[k]
            except KeyError:
                pass

    # import json
    # print(json.dumps(namespaces_to_types, indent=2))

    for qualtype in types_to_constructors:
        typespace, type = qualtype.split(".") if "." in qualtype else ("", qualtype)
        dir_path = DESTINATION_PATH / "base" / typespace

        module = type

        if module == "Updates":
            module = "UpdatesT"

        os.makedirs(dir_path, exist_ok=True)

        constructors = sorted(types_to_constructors[qualtype])
        constr_count = len(constructors)
        items = "\n            ".join([f"{c}" for c in constructors])

        type_docs = docs["type"].get(qualtype, None)

        if type_docs:
            type_docs = type_docs["desc"]
        else:
            type_docs = "Telegram API base type."

        docstring = type_docs

        docstring += f"\n\n    Constructors:\n" \
                     f"        This base type has {constr_count} constructor{'s' if constr_count > 1 else ''} available.\n\n" \
                     f"        .. currentmodule:: pyrogram.raw.types\n\n" \
                     f"        .. autosummary::\n" \
                     f"            :nosignatures:\n\n" \
                     f"            {items}"

        references, ref_count = get_references(qualtype, "types")

        if references:
            docstring += f"\n\n    Functions:\n        This object can be returned by " \
                         f"{ref_count} function{'s' if ref_count > 1 else ''}.\n\n" \
                         f"        .. currentmodule:: pyrogram.raw.functions\n\n" \
                         f"        .. autosummary::\n" \
                         f"            :nosignatures:\n\n" \
                         f"            " + references

        with open(dir_path / f"{snake(module)}.py", "w") as f:
            f.write(
                type_tmpl.format(
                    notice=notice,
                    warning=WARNING,
                    docstring=docstring,
                    name=type,
                    qualname=qualtype,
                    types=", ".join([f"raw.types.{c}" for c in constructors]),
                    doc_name=snake(type).replace("_", "-")
                )
            )

    for c in combinators.values():
        sorted_args = sort_args(c.args)

        arguments = (
            (", *, " if c.args else "") +
            (", ".join(
                [f"{i[0]}: {get_type_hint(i[1])}"
                 for i in sorted_args]
            ) if sorted_args else "")
        )

        fields = "\n        ".join(
            [f"self.{i[0]} = {i[0]}  # {i[1]}"
             for i in sorted_args]
        ) if sorted_args else "pass"

        docstring = ""
        docstring_args = []

        if c.section == "functions":
            combinator_docs = docs["method"]
        else:
            combinator_docs = docs["constructor"]

        for i, arg in enumerate(sorted_args):
            arg_name, arg_type = arg
            is_optional = FLAGS_RE.match(arg_type)
            flag_number = is_optional.group(1) if is_optional else -1
            arg_type = arg_type.split("?")[-1]

            arg_docs = combinator_docs.get(c.qualname, None)

            if arg_docs:
                arg_docs = arg_docs["params"].get(arg_name, "N/A")
            else:
                arg_docs = "N/A"

            docstring_args.append(
                "{} ({}{}):\n            {}\n".format(
                    arg_name,
                    get_docstring_arg_type(arg_type),
                    ", *optional*".format(flag_number) if is_optional else "",
                    arg_docs
                )
            )

        if c.section == "types":
            constructor_docs = docs["constructor"].get(c.qualname, None)

            if constructor_docs:
                constructor_docs = constructor_docs["desc"]
            else:
                constructor_docs = "Telegram API type."

            docstring += constructor_docs + "\n"
            docstring += f"\n    Constructor of :obj:`~pyrogram.raw.base.{c.qualtype}`."
        else:
            function_docs = docs["method"].get(c.qualname, None)

            if function_docs:
                docstring += function_docs["desc"] + "\n"
            else:
                docstring += f"Telegram API function."

        docstring += f"\n\n    Details:\n        - Layer: ``{layer}``\n        - ID: ``{c.id[2:].upper()}``\n\n"
        docstring += f"    Parameters:\n        " + \
                     (f"\n        ".join(docstring_args) if docstring_args else "No parameters required.\n")

        if c.section == "functions":
            docstring += "\n    Returns:\n        " + get_docstring_arg_type(c.qualtype)
        else:
            references, count = get_references(c.qualname, "constructors")

            if references:
                docstring += f"\n    Functions:\n        This object can be returned by " \
                             f"{count} function{'s' if count > 1 else ''}.\n\n" \
                             f"        .. currentmodule:: pyrogram.raw.functions\n\n" \
                             f"        .. autosummary::\n" \
                             f"            :nosignatures:\n\n" \
                             f"            " + references

        write_types = read_types = "" if c.has_flags else "# No flags\n        "

        for arg_name, arg_type in c.args:
            flag = FLAGS_RE_2.match(arg_type)

            if re.match(r"flags\d?", arg_name) and arg_type == "#":
                write_flags = []

                for i in c.args:
                    flag = FLAGS_RE_2.match(i[1])

                    if flag:
                        if arg_name != f"flags{flag.group(1)}":
                            continue

                        if flag.group(3) == "true" or flag.group(3).startswith("Vector"):
                            write_flags.append(f"{arg_name} |= (1 << {flag.group(2)}) if self.{i[0]} else 0")
                        else:
                            write_flags.append(
                                f"{arg_name} |= (1 << {flag.group(2)}) if self.{i[0]} is not None else 0")

                write_flags = "\n        ".join([
                    f"{arg_name} = 0",
                    "\n        ".join(write_flags),
                    f"b.write(Int({arg_name}))\n        "
                ])

                write_types += write_flags
                read_types += f"\n        {arg_name} = Int.read(b)\n        "

                continue

            if flag:
                number, index, flag_type = flag.groups()

                if flag_type == "true":
                    read_types += "\n        "
                    read_types += f"{arg_name} = True if flags{number} & (1 << {index}) else False"
                elif flag_type in CORE_TYPES:
                    write_types += "\n        "
                    write_types += f"if self.{arg_name} is not None:\n            "
                    write_types += f"b.write({flag_type.title()}(self.{arg_name}))\n        "

                    read_types += "\n        "
                    read_types += f"{arg_name} = {flag_type.title()}.read(b) if flags{number} & (1 << {index}) else None"
                elif "vector" in flag_type.lower():
                    sub_type = arg_type.split("<")[1][:-1]

                    write_types += "\n        "
                    write_types += f"if self.{arg_name} is not None:\n            "
                    write_types += "b.write(Vector(self.{}{}))\n        ".format(
                        arg_name, f", {sub_type.title()}" if sub_type in CORE_TYPES else ""
                    )

                    read_types += "\n        "
                    read_types += "{} = Vector.read_strict(b{}) if flags{} & (1 << {}) else []\n        ".format(
                        arg_name, f", {sub_type.title()}" if sub_type in CORE_TYPES else "", number, index
                    )
                else:
                    clear_arg_type = arg_type.split("?")[1]
                    if arg_type in {"Object", "!X"}:
                        obj_constuctors = []
                    else:
                        obj_constuctors = [combinators.get(qn) for qn in types_to_constructors[clear_arg_type]]

                    write_types += "\n        "
                    write_types += f"if self.{arg_name} is not None:\n            "
                    write_types += f"b.write(self.{arg_name}.write())\n        "

                    read_types += "\n        "
                    read_types += f"if flags{number} & (1 << {index}):\n            "

                    obj_type_name = "TLObject"
                    if obj_constuctors:
                        obj_type_name = f"{arg_name}_{obj_type_name}"
                        constr_id_name = f"{arg_name}_constructor"

                        constructor_ids = [f"raw.types.{obj_c.qualname}.ID: raw.types.{obj_c.qualname}" for obj_c in obj_constuctors]
                        read_types += f"{constr_id_name} = Int.read(b, False)\n            "
                        read_types += f"{obj_type_name}: type[TLObject]"
                        read_types += " = {\n                "
                        read_types += ", ".join(constructor_ids)
                        read_types += "\n            }"
                        read_types += f".get({constr_id_name}, None)\n            "
                        read_types += f"if {obj_type_name} is None:\n                "
                        read_types += f"raise raw.DeserializationError(\"{c.name}\", \"{arg_name}\", \"{clear_arg_type}\", {constr_id_name})\n            "

                    read_types += f"{arg_name} = {obj_type_name}.read(b)\n        "
                    read_types += "else:\n            "
                    read_types += f"{arg_name} = None\n        "
            else:
                if arg_type in CORE_TYPES:
                    write_types += "\n        "
                    write_types += f"b.write({arg_type.title()}(self.{arg_name}))\n        "

                    read_types += "\n        "
                    read_types += f"{arg_name} = {arg_type.title()}.read(b)\n        "
                elif "vector" in arg_type.lower():
                    sub_type = arg_type.split("<")[1][:-1]

                    write_types += "\n        "
                    write_types += "b.write(Vector(self.{}{}))\n        ".format(
                        arg_name, f", {sub_type.title()}" if sub_type in CORE_TYPES else ""
                    )

                    read_types += "\n        "
                    read_types += "{} = Vector.read_strict(b{})\n        ".format(
                        arg_name, f", {sub_type.title()}" if sub_type in CORE_TYPES else ""
                    )
                else:
                    if arg_type in {"Object", "!X"}:
                        obj_constuctors = []
                    else:
                        obj_constuctors = [combinators.get(qn) for qn in types_to_constructors[arg_type]]

                    write_types += "\n        "
                    write_types += f"b.write(self.{arg_name}.write())\n        "

                    read_types += "\n        "
                    obj_type_name = "TLObject"
                    if obj_constuctors:
                        obj_type_name = f"{arg_name}_{obj_type_name}"
                        constr_id_name = f"{arg_name}_constructor"

                        constructor_ids = [f"raw.types.{obj_c.qualname}.ID: raw.types.{obj_c.qualname}" for obj_c in obj_constuctors]
                        read_types += f"{constr_id_name} = Int.read(b, False)\n        "
                        read_types += f"{obj_type_name}: type[TLObject]"
                        read_types += " = {\n            "
                        read_types += ", ".join(constructor_ids)
                        read_types += "\n        }"
                        read_types += f".get({constr_id_name}, None)\n        "
                        read_types += f"if {obj_type_name} is None:\n            "
                        read_types += f"raise raw.DeserializationError(\"{c.name}\", \"{arg_name}\", \"{arg_type}\", {constr_id_name})\n        "

                    read_types += f"{arg_name} = {obj_type_name}.read(b)\n        "

        slots = ", ".join([f'"{i[0]}"' for i in sorted_args])
        return_arguments = ", ".join([f"{i[0]}={i[0]}" for i in sorted_args])

        compiled_combinator = combinator_tmpl.format(
            notice=notice,
            warning=WARNING,
            name=c.name,
            docstring=docstring,
            slots=slots,
            id=c.id,
            qualname=f"{c.section}.{c.qualname}",
            arguments=arguments,
            fields=fields,
            read_types=read_types,
            write_types=write_types,
            return_arguments=return_arguments
        )

        directory = "types" if c.section == "types" else c.section

        dir_path = DESTINATION_PATH / directory / c.namespace

        os.makedirs(dir_path, exist_ok=True)

        module = c.name

        if module == "Updates":
            module = "UpdatesT"

        with open(dir_path / f"{snake(module)}.py", "w") as f:
            f.write(compiled_combinator)

        d = namespaces_to_constructors if c.section == "types" else namespaces_to_functions

        if c.namespace not in d:
            d[c.namespace] = []

        d[c.namespace].append(c.name)

    for namespace, types in namespaces_to_types.items():
        with open(DESTINATION_PATH / "base" / namespace / "__init__.py", "w") as f:
            f.write(f"{notice}\n\n")
            f.write(f"{WARNING}\n\n")

            for t in types:
                module = t

                if module == "Updates":
                    module = "UpdatesT"

                f.write(f"from .{snake(module)} import {t}\n")

            if not namespace:
                f.write(f"from . import {', '.join(filter(bool, namespaces_to_types))}")

    for section, namespaces_to in (("types", namespaces_to_constructors), ("functions", namespaces_to_functions)):
        for namespace, types in namespaces_to.items():
            with open(DESTINATION_PATH / section / namespace / "__init__.py", "w") as f:
                f.write(f"{notice}\n\n")
                f.write(f"{__INIT__IMPORTS}\n\n")
                f.write(f"{WARNING}\n\n")
                f.write("if TYPE_CHECKING or LazyImporter is None:\n")

                nss = list(filter(bool, namespaces_to))
                if not namespace:
                    f.write(f"    from . import {', '.join(nss)}\n")

                for t in types:
                    module = t

                    if module == "Updates":
                        module = "UpdatesT"

                    f.write(f"    from .{snake(module)} import {t}\n")

                f.write("else:\n")
                f.write("    _import_structure = {\n")

                for t in types:
                    module = t

                    if module == "Updates":
                        module = "UpdatesT"

                    f.write(f"        \"{snake(module)}\": [\"{t}\"],\n")

                f.write("    }\n")
                extra_objects = ""
                if not namespace:
                    f.write(f"    from . import {', '.join(nss)}\n")
                    extra_objects = ",\n            ".join([f"\"{ns}\": {ns}" for ns in nss])

                f.write("    sys.modules[__name__] = LazyImporter(\n")
                f.write("        __name__,\n")
                f.write("        globals()[\"__file__\"],\n")
                f.write("        _import_structure,\n")
                f.write("        extra_objects={\n")
                f.write(f"            {extra_objects}\n")
                f.write("        }\n")
                f.write("    )\n")

    with open(DESTINATION_PATH / "all.py", "w", encoding="utf-8") as f:
        f.write(f"{notice}\n\n")
        f.write(f"{WARNING}\n\n")
        f.write(f"{LAZY_IMPORT_DICT}\n\n")
        f.write(f"layer = {layer}\n\n")
        f.write("objects = LazyLoadDict({")

        for c in combinators.values():
            f.write(f'\n    {c.id}: "pyrogram.raw.{c.section}.{c.qualname}",')

        f.write('\n    0xbc799737: "pyrogram.raw.core.BoolFalse",')
        f.write('\n    0x997275b5: "pyrogram.raw.core.BoolTrue",')
        f.write('\n    0x1cb5c415: "pyrogram.raw.core.Vector",')
        f.write('\n    0x73f1f8dc: "pyrogram.raw.core.MsgContainer",')
        f.write('\n    0xae500895: "pyrogram.raw.core.FutureSalts",')
        f.write('\n    0x0949d9dc: "pyrogram.raw.core.FutureSalt",')
        f.write('\n    0x3072cfa1: "pyrogram.raw.core.GzipPacked",')
        f.write('\n    0x5bb8e511: "pyrogram.raw.core.Message",')

        f.write("\n})\n")


if "__main__" == __name__:
    HOME_PATH = Path(".")
    DESTINATION_PATH = Path("../../pyrogram/raw")
    NOTICE_PATH = Path("../../NOTICE")

    start(format=False)
