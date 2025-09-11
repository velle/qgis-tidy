#!/usr/bin/env python3
import argparse
import io
import sys
import zipfile
import lxml.etree as ET
from pathlib import Path
from typing import List, Dict, BinaryIO
from enum import Enum, auto


class Dest(Enum):
    IN_PLACE = auto()


ATTR_STRIP = [
    "expanded",
    "checked",
    "saveDateTime",
]

SORT_RULES = [
    {
        "parent_xpath": "//customproperties",
        "child_xpath": "property",
        "key_xpath": "@key",
    },
    {"parent_xpath": "//variables", "child_xpath": "variable", "key_xpath": "@name"},
    {
        "parent_xpath": "//fieldConfiguration",
        "child_xpath": "field",
        "key_xpath": "@name",
    },
    {"parent_xpath": "//aliases", "child_xpath": "alias", "key_xpath": "@name"},
    {
        "parent_xpath": "//attributealiases",
        "child_xpath": "alias",
        "key_xpath": "@field",
    },
    {
        "parent_xpath": "//constraints",
        "child_xpath": "constraint",
        "key_xpath": "@field",
    },
    {
        "parent_xpath": "//excludedAttributes",
        "child_xpath": "attribute",
        "key_xpath": "text()",
    },
    {
        "parent_xpath": "//individual-layer-settings",
        "child_xpath": "layer-setting",
        "key_xpath": "@id",
    },
    # You can add renderer sorting in a config file if appropriate for your styles:
    # {"parent_xpath":"//renderer-v2/categorizedSymbol","child_xpath":"category","key_xpath":"@label"},
    # {"parent_xpath":"//renderer-v2/graduatedSymbol","child_xpath":"range","key_xpath":"@label"},
]


def strip_attrs(tree: ET._ElementTree, names: List[str]) -> None:
    if not names:
        return
    xpath = " | ".join(f"//@{n}" for n in names)
    for attr in tree.xpath(xpath):
        parent = attr.getparent()
        if parent is not None:
            try:
                del parent.attrib[attr.attrname]
            except Exception:
                pass


def sort_children(parent, child_xpath: str, key_xpath: str) -> None:
    children = parent.findall(child_xpath)
    if len(children) < 2:
        return

    def key_for(child):
        res = child.xpath(key_xpath)
        v = res[0] if isinstance(res, list) and res else res
        if isinstance(v, (bytes, bytearray)):
            v = v.decode("utf-8", "ignore")
        else:
            v = "" if v is None else str(v)
        try:
            return (0, float(v))
        except Exception:
            return (1, v)

    sorted_children = sorted(children, key=key_for)
    for ch in sorted_children:
        parent.remove(ch)
    for ch in sorted_children:
        parent.append(ch)


def apply_sort_rules(tree: ET._ElementTree, rules: List[Dict[str, str]]) -> None:
    for rule in rules or []:
        parents = tree.xpath(rule["parent_xpath"])
        for p in parents:
            sort_children(p, rule["child_xpath"], rule["key_xpath"])


def normalize_xml_bytes(data: bytes, attr_strip=None) -> bytes:
    # Parse with blank-text removal, strip attrs, apply sorts, c14n pass, then pretty print.
    parser = ET.XMLParser(remove_blank_text=True)
    root = ET.fromstring(data, parser=parser)
    tree = ET.ElementTree(root)
    if attr_strip is not None:
        strip_attrs(tree, attr_strip)
    apply_sort_rules(tree, SORT_RULES)

    c14n = ET.tostring(
        tree.getroot(), method="c14n", exclusive=False, with_comments=False
    )  # type: ignore
    root2 = ET.fromstring(c14n)
    pretty = ET.tostring(
        root2, pretty_print=True, xml_declaration=True, encoding="UTF-8"
    )
    return pretty


def _process_qgz_file(
    src: Path | BinaryIO,
    dst: Path | BinaryIO | Dest = Dest.IN_PLACE,
    dsttype: str = 'qgs',
    attr_strip: list[str] | None = None,
) -> int:
    """
    Read a .qgz (zip) from Path or BinaryIO, normalize the contained .qgs via
    normalize_xml_bytes(attr_strip), rewrite the archive deterministically,
    and write the resulting bytes to Path or BinaryIO dst.

    Returns 1 if content changed, 0 otherwise.
    """

    if dsttype is None:
        dsttype = "qgz"

    # Read source bytes
    if isinstance(src, Path):
        src_bytes = src.read_bytes()
    else:
        buf = src.read()
        if not isinstance(buf, (bytes, bytearray, memoryview)):
            raise TypeError("src must be a binary stream opened in 'rb'")
        src_bytes = bytes(buf)

    # Open as ZIP from memory
    import io

    zin = zipfile.ZipFile(io.BytesIO(src_bytes), "r")

    # Collect member names (files only; skip directories for determinism)
    infolist = zin.infolist()
    names = [
        zi.filename
        for zi in infolist
        if not getattr(zi, "is_dir", lambda: zi.filename.endswith("/"))()
    ]

    # Identify main .qgs (must be exactly one)
    qgs_names = [n for n in names if n.lower().endswith(".qgs")]
    assert len(qgs_names) == 1, "Expected exactly one .qgs in the .qgz archive"

    normalized_xml = None

    # Build new ZIP deterministically in memory
    out_buf = io.BytesIO()
    with zipfile.ZipFile(
        out_buf, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as zout:
        for name in sorted(names):
            data = zin.read(name)
            if name.lower().endswith(".qgs"):
                normalized_xml = normalize_xml_bytes(data, attr_strip)
                data = normalized_xml
                sys.stderr.write('FOO' + str(normalized_xml[:20]))
            # Deterministic ZipInfo (stable timestamp, unix creator, deflated)
            zi = zipfile.ZipInfo(filename=name)
            zi.date_time = (1980, 1, 1, 0, 0, 0)
            zi.create_system = 3  # Unix
            zi.compress_type = zipfile.ZIP_DEFLATED
            zout.writestr(zi, data)

    if dsttype == 'qgs':
        out_bytes = normalized_xml
        sys.stderr.write(f'a1\n')
    elif dsttype == 'qgz':
        out_bytes = out_buf.getvalue()
        sys.stderr.write(f'a2\n')
    else:
        raise ValueError()

    # Write destination
    sys.stderr.write(f'hello %{dst}\n')
    if dst == Dest.IN_PLACE:
        if dsttype != 'qgz':
            raise ValueError("if dst=IN_PLACE, then dsttype must be qgz")
        if not isinstance(src, Path):
            raise ValueError("In-place editing requires src to be a file path")
        else:
            src.write_bytes(out_bytes)
    elif isinstance(dst, Path):
        dst.write_bytes(out_bytes)
    elif isinstance(dst, io.BufferedIOBase):
        sys.stderr.write(f'xxx %{dst}\n')
        dst.write(out_bytes)
    else:
        raise TypeError("dst must be Path, BinaryIO, or Dest.IN_PLACE")

def _process_qgs_file(
    src: Path | BinaryIO,
    dst: Path | BinaryIO | Dest = Dest.IN_PLACE,
    attr_strip: list[str] | None = None,
) -> int:
    if isinstance(src, Path):
        src_bytes = src.read_bytes()
    else:
        buf = src.read()
        if not isinstance(buf, (bytes, bytearray, memoryview)):
            raise TypeError("src must be a binary stream opened in 'rb'")
        src_bytes = bytes(buf)
    src_bytes.decode("utf-8")  # raises UnicodeDecodeError if not UTF-8

    out_bytes = normalize_xml_bytes(src_bytes, attr_strip)
    changed = out_bytes != src_bytes

    # Write destination
    if dst == Dest.IN_PLACE:
        if not isinstance(src, Path):
            raise ValueError("In-place editing requires src to be a file path")
        else:
            src.write_bytes(out_bytes)
    elif isinstance(dst, Path):
        dst.write_bytes(out_bytes)
    elif isinstance(dst, io.BufferedIOBase):
        dst.write(out_bytes)
    else:
        raise TypeError("dst must be Path, BinaryIO, or Dest.IN_PLACE")

    return 1 if changed else 0


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="qgis-tidy",
        add_help=True,
        description=(
            "qgis-tidy tidies the XML in (.qgs or .qgz).\n"
            "qgz files contains more than just XML,\n"
            "but other files are repacked without change.\n"
            "It can rewrite files in place, output a cleaned version,\n"
            "or act as a textconv tool for Git diffs."
        ),
    )
    p.add_argument("src", help=".qgs or .qgz")
    p.add_argument(
        "-o",
        "--output",
        dest="dst",
        default=Dest.IN_PLACE,
        help="Output file path (default is in-place), use '-' for stdout",
    )
    p.add_argument(
        "--lax",
        action="store_true",
        help="Removes selected attributes (defined in `attr_strip`) before diffing.",
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Prints status/diagnostics to stderr",
    )
    args = p.parse_args(argv)

    if args.src == "-":
        raise NotImplementedError(
            "Support for reading from stdin not implemented yet; use files instead."
        )

    args.src = Path(args.src)
    assert args.src.is_file(), f"Input file does not exist: {args.src}"

    filetype = args.src.suffix.lower()[1:]  # qgs, qgz
    assert filetype in ["qgs", "qgz"], "Input file must be .qgs or .qgz"

    if args.dst == Dest.IN_PLACE:
        pass  # args.dst = Dest.IN_PLACE
    elif args.dst == "-":
        args.dst = sys.stdout.buffer
    else:
        args.dst = Path(args.dst)

    if filetype == "qgz":
        _process_qgz_file(
            args.src, args.dst, attr_strip=ATTR_STRIP if args.lax else None
        )
    else:
        _process_qgs_file(
            args.src, args.dst, attr_strip=ATTR_STRIP if args.lax else None
        )
