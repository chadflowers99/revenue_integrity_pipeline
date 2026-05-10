import argparse
import re
from pathlib import Path


SECTION_PREFIXES = [
    "=== RAW PREVIEW ===",
    "=== DATA QUALITY REPORT ===",
    "=== REQUIRED COLUMN NULL COUNTS ===",
    "=== MALFORMED ROW DIAGNOSTICS ===",
    "=== BASELINE TREND",
    "=== PROJECTION CONTROLS ===",
    "=== ACTUAL POST-REVIEW ===",
    "=== LOSS PROJECTION",
]


def clean_info_lines(log_text):
    """Extracts INFO payload lines and strips step labels like [Cleanup]."""
    lines = []
    for raw_line in log_text.splitlines():
        if " - INFO - " not in raw_line:
            continue
        payload = raw_line.split(" - INFO - ", 1)[1]
        tag_match = re.match(r"^\[[^\]]+\]\s?(.*)$", payload)
        if tag_match:
            payload = tag_match.group(1)
        lines.append(payload.rstrip())
    return lines


def collect_sections(lines):
    """Collects blocks under '=== ... ===' headings."""
    sections = {}
    current_header = None

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("===") and stripped.endswith("==="):
            current_header = stripped
            sections[current_header] = []
            continue

        if current_header is not None:
            sections[current_header].append(line)

    return sections


def find_header_by_prefix(sections, prefix):
    for header in sections.keys():
        if header.startswith(prefix):
            return header
    return None


def trim_block(lines):
    """Trims leading/trailing blank lines and normalizes left spacing."""
    start = 0
    end = len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return [line.lstrip() for line in lines[start:end]]


def build_summary(log_text):
    info_lines = clean_info_lines(log_text)
    sections = collect_sections(info_lines)

    output_lines = []

    for prefix in SECTION_PREFIXES:
        header = find_header_by_prefix(sections, prefix)
        if not header:
            continue

        block_lines = trim_block(sections[header])

        if header == "=== RAW PREVIEW ===":
            filtered = []
            for line in block_lines:
                if not line.strip() and filtered:
                    break
                if line.strip():
                    filtered.append(line)
                if len(filtered) == 4:
                    break
            block_lines = filtered

        if header == "=== DATA QUALITY REPORT ===":
            keep_prefixes = (
                "Total rows:",
                "Rows with missing",
                "Rows remediated",
                "Rows needing review",
            )
            block_lines = [line for line in block_lines if line.startswith(keep_prefixes)]

        if header == "=== REQUIRED COLUMN NULL COUNTS ===":
            block_lines = [line for line in block_lines if line.endswith(" nulls")]

        if header == "=== MALFORMED ROW DIAGNOSTICS ===":
            keep_prefixes = (
                "Missing required:",
                "Validation failures:",
                "Corrupted rows:",
                "TOTAL malformed rows:",
            )
            block_lines = [line for line in block_lines if line.startswith(keep_prefixes)]

        if header.startswith("=== BASELINE TREND"):
            keep_prefixes = ("Months of data", "Avg monthly rev", "Monthly growth")
            block_lines = [line for line in block_lines if line.startswith(keep_prefixes)]

        if header == "=== PROJECTION CONTROLS ===":
            keep_prefixes = (
                "Requested mode",
                "Applied mode",
                "Baseline months",
                "Horizon (months)",
                "Max monthly growth",
                "Growth damping/mo",
            )
            block_lines = [line for line in block_lines if line.startswith(keep_prefixes)]

        if header == "=== ACTUAL POST-REVIEW ===":
            keep_prefixes = ("Months of data", "Avg monthly rev", "Total revenue")
            block_lines = [line for line in block_lines if line.startswith(keep_prefixes)]

        if header.startswith("=== LOSS PROJECTION"):
            filtered = []
            for line in block_lines:
                filtered.append(line)
                if line.startswith("Estimated total loss over"):
                    break
            block_lines = filtered

        output_lines.append(header)
        output_lines.extend(block_lines)
        output_lines.append("")
        output_lines.append("")

    return "\n".join(output_lines).rstrip() + "\n"


def find_latest_log(output_dir):
    logs = sorted(output_dir.glob("forensic_audit_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not logs:
        raise FileNotFoundError(f"No forensic audit logs found in: {output_dir}")
    return logs[0]


def main():
    parser = argparse.ArgumentParser(description="Generate forensic_gallery_output.txt from the latest pipeline audit log.")
    parser.add_argument("--client", default="client_name_001", help="Client folder under clients/ (default: client_name_001)")
    parser.add_argument("--log", default=None, help="Optional explicit log file path")
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parent
    client_output_dir = base_dir / "clients" / args.client / "output"

    log_path = Path(args.log).resolve() if args.log else find_latest_log(client_output_dir)
    log_text = log_path.read_text(encoding="utf-8", errors="replace")

    summary = build_summary(log_text)
    target_path = base_dir / "forensic_gallery_output.txt"
    target_path.write_text(summary, encoding="utf-8")

    print(f"Source log: {log_path}")
    print(f"Gallery summary written to: {target_path}")


if __name__ == "__main__":
    main()
