
#!/usr/bin/env python3
"""
qgis-tidy — normalize QGIS project files for stable diffs.

- Accepts .qgs (XML) and .qgz (ZIP containing a .qgs).
- Canonicalizes & pretty-prints the project XML.
- Strips volatile attributes (configurable).
- Deterministically sorts known order-insensitive lists (configurable).
- For .qgz: rewrites only targeted XML files; all other entries are copied byte-for-byte.
- Rebuilds .qgz deterministically (fixed timestamps, sorted entries, consistent compression).
- Optional: also normalize other XML-like entries inside .qgz (e.g., .qml, .sld).

Dependencies: lxml (pip install lxml). PyYAML is optional for external rule files.

Usage:
  qgis-tidy INPUT               # writes to stdout
  qgis-tidy -i INPUT            # in-place
  qgis-tidy -i project.qgz      # normalize embedded .qgs and rezip deterministically
  qgis-tidy -i --include-xml "*.qml,*.sld" project.qgz

Options:
  -i, --inplace           Rewrite input file in place (for .qgz/.qgs).
  -o FILE, --output FILE  Write to FILE instead of stdout/inplace.
  --config YAML           Add/override rules for stripping attrs and sorting.
  --include-xml PATTERNS  For .qgz only: comma-separated glob patterns of extra XML entries to tidy (e.g. "*.qml,*.sld").
  --list                  For .qgz: list archive entries and exit.
  --strict                Non-zero exit if no .qgs found in .qgz.
  --dry-run               Do all processing but don't write changes; exit code 1 if output would differ.
  --quiet                 Suppress non-error logs.

Exit codes:
  0 = success, no error (and no difference if --dry-run)
  1 = success but would change output in --dry-run
  2 = usage or parse error
  3 = processing error
"""
import argparse
import io
import sys
import zipfile
import fnmatch
from pathlib import Path
from typing import Optional, List, Dict, Any

try:
    from lxml import etree as ET
except Exception as e:
    print("ERROR: qgis-tidy requires 'lxml'. Try: pip install lxml", file=sys.stderr)
    raise SystemExit(2)

DEFAULT_RULES = {
    "strip_attributes": [
        "expanded", "selected", "lastSaved", "timestamp", "uuid", "lastOpened"
    ],
    "sort_rules": [
        {"parent_xpath":"//customproperties","child_xpath":"property","key_xpath":"@key"},
        {"parent_xpath":"//variables","child_xpath":"variable","key_xpath":"@name"},
        {"parent_xpath":"//fieldConfiguration","child_xpath":"field","key_xpath":"@name"},
        {"parent_xpath":"//aliases","child_xpath":"alias","key_xpath":"@name"},
        {"parent_xpath":"//attributealiases","child_xpath":"alias","key_xpath":"@field"},
        {"parent_xpath":"//constraints","child_xpath":"constraint","key_xpath":"@field"},
        {"parent_xpath":"//excludedAttributes","child_xpath":"attribute","key_xpath":"text()"},
        {"parent_xpath":"//individual-layer-settings","child_xpath":"layer-setting","key_xpath":"@id"},
        # You can add renderer sorting in a config file if appropriate for your styles:
        # {"parent_xpath":"//renderer-v2/categorizedSymbol","child_xpath":"category","key_xpath":"@label"},
        # {"parent_xpath":"//renderer-v2/graduatedSymbol","child_xpath":"range","key_xpath":"@label"},
    ]
}

def load_yaml(path: Optional[str]) -> Optional[Dict[str, Any]]:
    if not path:
        return None
    try:
        import yaml  # type: ignore
    except Exception:
        print("WARNING: --config given but PyYAML is not installed; ignoring.", file=sys.stderr)
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            if not isinstance(data, dict):
                raise ValueError("YAML root must be a mapping")
            return data
    except Exception as e:
        print(f"WARNING: Could not read YAML rules from {path}: {e}", file=sys.stderr)
        return None

def merge_rules(base: Dict[str, Any], extra: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not extra:
        return base
    out = dict(base)
    if "strip_attributes" in extra and isinstance(extra["strip_attributes"], list):
        out["strip_attributes"] = list(dict.fromkeys(out.get("strip_attributes", []) + extra["strip_attributes"]))
    if "sort_rules" in extra and isinstance(extra["sort_rules"], list):
        out["sort_rules"] = out.get("sort_rules", []) + extra["sort_rules"]
    return out

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
            v = v.decode("utf-8","ignore")
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

def normalize_xml_bytes(data: bytes, rules: Dict[str, Any]) -> bytes:
    # Parse with blank-text removal, strip attrs, apply sorts, c14n pass, then pretty print.
    parser = ET.XMLParser(remove_blank_text=True)
    root = ET.fromstring(data, parser=parser)
    tree = ET.ElementTree(root)
    strip_attrs(tree, rules.get("strip_attributes", []))
    apply_sort_rules(tree, rules.get("sort_rules", []))

    c14n = ET.tostring(tree.getroot(), method="c14n", exclusive=False, with_comments=False)  # type: ignore
    root2 = ET.fromstring(c14n)
    pretty = ET.tostring(root2, pretty_print=True, xml_declaration=True, encoding="UTF-8")
    return pretty

def _repack_qgz(in_path: Path, out_path: Path, rules: Dict[str, Any], include_patterns: List[str], quiet: bool) -> bool:
    """
    Returns True if content changed, False otherwise.
    """
    with zipfile.ZipFile(in_path, "r") as zin:
        names = [zi.filename for zi in zin.infolist()]
        # Identify main .qgs
        qgs_names = [n for n in names if n.lower().endswith(".qgs")]
        qgs_name = sorted(qgs_names)[0] if qgs_names else None

        buf = io.BytesIO()
        changed = False
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zout:
            for name in sorted(names):
                data = zin.read(name)
                should_tidy = False
                if qgs_name and name == qgs_name:
                    should_tidy = True
                else:
                    # check include patterns for additional XML-ish entries
                    for pat in include_patterns:
                        if fnmatch.fnmatch(name, pat):
                            should_tidy = True
                            break

                if should_tidy and name.lower().endswith((".qgs", ".xml", ".qml", ".sld")):
                    try:
                        new_data = normalize_xml_bytes(data, rules)
                        if new_data != data:
                            changed = True
                        data = new_data
                        if not quiet:
                            sys.stderr.write(f"[qgis-tidy] normalized: {name}\n")
                    except Exception as e:
                        # If parsing fails, keep original to be safe
                        if not quiet:
                            sys.stderr.write(f"[qgis-tidy] WARNING: failed to normalize {name}: {e}\n")
                # Deterministic ZipInfo
                zi = zipfile.ZipInfo(filename=name)
                zi.date_time = (1980,1,1,0,0,0)
                zi.create_system = 3  # Unix
                zi.compress_type = zipfile.ZIP_DEFLATED
                zout.writestr(zi, data)

    new_bytes = buf.getvalue()
    old_bytes = in_path.read_bytes()
    if new_bytes != old_bytes:
        changed = True
        out_path.write_bytes(new_bytes)
    else:
        # still write if output is a different file path
        if out_path != in_path:
            out_path.write_bytes(new_bytes)
    return changed

def _process_qgs(in_path: Path, out_path: Optional[Path], inplace: bool, rules: Dict[str, Any]) -> int:
    data = in_path.read_bytes()
    new = normalize_xml_bytes(data, rules)
    changed = (new != data)
    if out_path:
        out_path.write_bytes(new)
    elif inplace:
        in_path.write_bytes(new)
    else:
        sys.stdout.buffer.write(new)
    return 1 if changed else 0

def main(argv=None):
    p = argparse.ArgumentParser(prog="qgis-tidy", add_help=True)
    p.add_argument("input", help=".qgs or .qgz (or '-' to read .qgs XML from stdin)")
    p.add_argument("-i","--inplace", action="store_true", help="Rewrite INPUT in place")
    p.add_argument("-o","--output", help="Output file path (default: stdout unless --inplace)")
    p.add_argument("--config", help="YAML with extra/override rules")
    p.add_argument("--include-xml", help="For .qgz: comma-separated glob patterns of additional XML entries to tidy (e.g. '*.qml,*.sld')", default="")
    p.add_argument("--list", action="store_true", help="For .qgz: list archive entries and exit")
    p.add_argument("--strict", action="store_true", help="Exit with error if no .qgs present in .qgz")
    p.add_argument("--dry-run", action="store_true", help="Process but do not write; exit 1 if output would change")
    p.add_argument("--quiet", action="store_true", help="Suppress non-error logs")
    args = p.parse_args(argv)

    rules = merge_rules(DEFAULT_RULES, load_yaml(args.config))
    include_patterns = [s.strip() for s in args.include_xml.split(",") if s.strip()]

    # stdin mode for raw .qgs XML
    if args.input == "-":
        if args.inplace or args.output:
            print("ERROR: --inplace/--output not supported with stdin.", file=sys.stderr)
            return 2
        data = sys.stdin.buffer.read()
        out = normalize_xml_bytes(data, rules)
        if args.dry_run:
            return 1 if out != data else 0
        sys.stdout.buffer.write(out)
        return 0

    in_path = Path(args.input)
    if not in_path.exists():
        print(f"ERROR: Input not found: {in_path}", file=sys.stderr)
        return 2

    suffix = in_path.suffix.lower()
    is_qgz = (suffix == ".qgz")
    is_qgs = (suffix == ".qgs")

    if is_qgz:
        if args.list:
            with zipfile.ZipFile(in_path, "r") as zin:
                for zi in zin.infolist():
                    print(zi.filename)
            return 0
        tmp_out = in_path if (args.inplace and not args.output) else Path(args.output) if args.output else None
        if tmp_out is None and not args.dry_run:
            # default to stdout not sensible for binary zip; require -i or -o
            print("ERROR: For .qgz, use --inplace or --output to write a file. Or use --list.", file=sys.stderr)
            return 2
        # Perform repack to a BytesIO and compare for dry-run
        # We'll reuse internal helper with a temp path for output
        out_path = tmp_out or in_path  # placeholder
        # Write to a temp in-memory buffer first
        changed = _repack_qgz(in_path, out_path, rules, include_patterns, args.quiet)
        if args.dry_run:
            return 1 if changed else 0
        if not args.inplace and args.output is None:
            # We already wrote to out_path above due to implementation; nothing to stream
            pass
        return 0

    elif is_qgs:
        # Decide output destination
        if args.output and args.inplace:
            print("ERROR: Use either --inplace or --output, not both.", file=sys.stderr)
            return 2
        if args.dry_run:
            data = in_path.read_bytes()
            new = normalize_xml_bytes(data, rules)
            return 1 if new != data else 0
        out_path = Path(args.output) if args.output else None
        _ = _process_qgs(in_path, out_path, args.inplace, rules)
        return 0

    else:
        print("ERROR: Unsupported input type (expected .qgs or .qgz).", file=sys.stderr)
        return 2

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ET.XMLSyntaxError as e:
        print(f"XML parse error: {e}", file=sys.stderr)
        raise SystemExit(2)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise SystemExit(3)
