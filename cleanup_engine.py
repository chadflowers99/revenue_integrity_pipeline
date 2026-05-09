"""
Universal CSV cleanup engine.
Behavior is 100% driven by the job config.
"""

# cleanup_engine.py

import os
import re
from datetime import datetime
from typing import Dict
import pandas as pd
pd.set_option('display.max_columns', None)
pd.set_option('display.width', 2000)
pd.set_option('display.max_colwidth', None)
pd.set_option('display.expand_frame_repr', False)


# -----------------------------
# Text Hygiene Utilities
# -----------------------------
def normalize_encoding(text):
    if not isinstance(text, str):
        return text
    try:
        return text.encode("latin1").decode("utf-8")
    except Exception:
        return text

def patch_corrupted_chars(text):
    if not isinstance(text, str):
        return text
    subs = {
        r"â€“": "–", r"â€”": "—", r"â€˜": "‘", r"â€™": "’",
        r"â€œ": "“", r"â€": "”", r"â€¦": "…", r"â€": ""
    }
    for pat, rep in subs.items():
        text = re.sub(pat, rep, text)
    return text

def clean_text(text):
    return patch_corrupted_chars(normalize_encoding(text))


def diagnostic_currency_handler(value):
    """
    Silver-Layer currency parsing with explicit S5 flag routing.

    Returns:
      parsed_value (float | None), s5_flag (bool), remediated (bool)
    """
    if pd.isna(value) or value == "":
        return None, False, False

    original = str(value).strip()
    lowered = original.lower()

    clean_val = (lowered.replace('$', '')
                       .replace('cash', '')
                       .replace('mobile', '')
                       .replace('pay', '')
                       .replace('card', '')
                       .strip())
    remediated = clean_val != lowered

    try:
        return float(clean_val), False, remediated
    except ValueError:
        # Keep numeric column numeric; route suppression state to row flag column.
        return None, True, False


def is_safe_recompute_expression(expr: str, columns) -> bool:
    """
    Restrict recompute expressions to basic arithmetic over known columns.
    """
    if not isinstance(expr, str) or not expr.strip():
        return False

    if not re.fullmatch(r"[A-Za-z0-9_\s\+\-\*\/\(\)\.]+", expr):
        return False

    allowed_identifiers = set(columns)
    tokens = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expr))
    return tokens.issubset(allowed_identifiers)


# -----------------------------
# Header Normalization
# -----------------------------
def normalize_header(name: str) -> str:
    if not isinstance(name, str):
        name = str(name)
    name = clean_text(name)
    name = name.strip().lower()
    name = re.sub(r"[^0-9a-z]+", "_", name)
    name = re.sub(r"_+", "_", name)
    return name.strip("_")


def normalize_column_list(columns):
    return [normalize_header(c) for c in columns]


# -----------------------------
# Encoding Detection
# -----------------------------
def detect_encoding(path: str) -> str:
    for enc in ("utf-8", "latin-1"):
        try:
            with open(path, "r", encoding=enc) as f:
                f.read(1024)
            return enc
        except UnicodeDecodeError:
            continue
    return "utf-8"


def safe_write_csv(df: pd.DataFrame, target_path: str, label: str):
    """Writes CSV and falls back to a timestamped filename when the target is locked."""
    target_dir = os.path.dirname(target_path)
    if target_dir:
        os.makedirs(target_dir, exist_ok=True)

    try:
        df.to_csv(target_path, index=False, encoding="utf-8")
        print(f"{label} written to:", target_path)
        return target_path
    except PermissionError:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        root, ext = os.path.splitext(target_path)
        fallback_path = f"{root}_{stamp}{ext or '.csv'}"
        df.to_csv(fallback_path, index=False, encoding="utf-8")
        print(
            f"[WARN] {label} target is locked/open. Wrote fallback file to:",
            fallback_path,
        )
        return fallback_path


# -----------------------------
# Main Cleanup Engine
# -----------------------------
def run_cleanup(config: Dict):

    base_dir = config.get("base_dir") or os.getcwd()
    base_dir = os.path.abspath(base_dir)

    input_path = config["input_path"]
    output_path = config["output_path"]

    if not os.path.isabs(input_path):
        input_path = os.path.join(base_dir, input_path)
    if not os.path.isabs(output_path):
        output_path = os.path.join(base_dir, output_path)

    delimiter = config.get("delimiter", ",")
    mode = config.get("mode", "strict").lower()

    required = normalize_column_list(config.get("required_columns", []))
    optional = normalize_column_list(config.get("optional_columns", []))

    text_columns = normalize_column_list(config.get("text_columns", []))
    numeric_columns = normalize_column_list(config.get("numeric_columns", []))
    date_columns = normalize_column_list(config.get("date_columns", []))

    recompute = config.get("recompute", {})
    validation_rules = config.get("validation_rules", [])

    print("RUNNING:", os.path.abspath(__file__))

    # -----------------------------
    # Load CSV
    # -----------------------------
    encoding = detect_encoding(input_path)
    df = pd.read_csv(input_path, sep=delimiter, engine="python", encoding=encoding)

    print("\n=== RAW PREVIEW ===")
    print(df.head(3).to_string(index=False))

    # -----------------------------
    # Normalize headers
    # -----------------------------
    normalized = [normalize_header(c) for c in df.columns]

    # Ensure uniqueness
    unique = []
    counts = {}
    for name in normalized:
        if name not in counts:
            counts[name] = 0
            unique.append(name)
        else:
            counts[name] += 1
            unique.append(f"{name}_{counts[name]}")

    df.columns = unique
    print("\nNormalized headers:", df.columns.tolist())

    # -----------------------------
    # Ensure required + optional exist
    # -----------------------------
    for col in required + optional:
        if col not in df.columns:
            df[col] = pd.NA

    # Reorder
    ordered = [c for c in required + optional if c in df.columns]
    others = [c for c in df.columns if c not in ordered]
    df = df[ordered + others]

    # -----------------------------
    # Text cleaning
    # -----------------------------
    for col in text_columns:
        if col in df.columns:
            df[col] = df[col].astype(str).apply(clean_text).str.strip()

    # -----------------------------
    # Title-case normalization
    # -----------------------------
    title_columns = config.get("title_columns", [])
    for col in title_columns:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip().str.title()

    # -----------------------------
    # Value normalization (maps)
    # -----------------------------
    value_maps = config.get("value_maps", {})
    for raw_col, mapping in value_maps.items():
        col = normalize_header(raw_col)
        if col in df.columns:
            df[col] = df[col].replace(mapping)

    # -----------------------------
    # Conditional mapping (cross-column derivations)
    # -----------------------------
    conditional_maps = config.get("conditional_maps", [])
    for rule in conditional_maps:
        target_col = normalize_header(rule.get("target_column", ""))
        source_col = normalize_header(rule.get("source_column", ""))
        lookup = rule.get("lookup", {})
        only_if_target_missing = bool(rule.get("only_if_target_missing", True))

        if not target_col or not source_col:
            print("[WARN] conditional_maps rule missing target_column/source_column; skipped")
            continue
        if target_col not in df.columns or source_col not in df.columns:
            print(
                f"[WARN] conditional_maps columns not found: target={target_col}, source={source_col}; skipped"
            )
            continue
        if not isinstance(lookup, dict) or not lookup:
            continue

        source_values = df[source_col].astype(str).str.strip().str.title()
        mapped = source_values.map(lookup)

        if only_if_target_missing:
            target_missing = df[target_col].isna() | (df[target_col].astype(str).str.strip() == "")
            apply_mask = target_missing & mapped.notna()
        else:
            apply_mask = mapped.notna()

        applied_count = int(apply_mask.sum())
        if applied_count > 0:
            df.loc[apply_mask, target_col] = mapped[apply_mask]
            print(
                f"[DERIVE] {target_col}: applied {applied_count} conditional fills from {source_col}"
            )

    # -----------------------------
    # Numeric cleaning
    # -----------------------------
    for col in numeric_columns:
        if col in df.columns:
            df[col] = (
                df[col].astype(str)
                .str.replace(r"[^0-9.\-]", "", regex=True)
                .replace("", pd.NA)
            )
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # -----------------------------
    # ZIP code validation
    # -----------------------------
    zip_columns = normalize_column_list(config.get("zip_columns", []))
    for col in zip_columns:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()
            invalid = ~df[col].str.match(r"^\d{5}$", na=False)
            invalid_count = invalid.sum()
            if invalid_count > 0:
                print(f"[ZIP] {col}: {invalid_count} invalid values replaced with 'Unknown'")
            df.loc[invalid, col] = "Unknown"

    # -----------------------------
    # Currency cleaning (forensic)
    # -----------------------------
    currency_columns = normalize_column_list(config.get("currency_columns", []))
    s5_threshold = config.get("s5_threshold", 0.05)
    row_flag_column = normalize_header(config.get("row_flag_column", "_row_flag"))
    if row_flag_column not in df.columns:
        df[row_flag_column] = pd.NA

    remediation_stats = {}
    s5_any_mask = pd.Series(False, index=df.index)
    for col in currency_columns:
        if col in df.columns:
            print(f"[DEBUG] Applying currency handler to: {col}")
            parsed = df[col].apply(diagnostic_currency_handler)
            parsed_values = parsed.apply(lambda x: x[0])
            parsed_s5 = parsed.apply(lambda x: x[1])
            parsed_remediated = parsed.apply(lambda x: x[2])

            df[col] = pd.to_numeric(parsed_values, errors="coerce")
            remediated = int(parsed_remediated.sum())
            s5_count = int(parsed_s5.sum())
            s5_any_mask |= parsed_s5

            if s5_count > 0:
                df.loc[parsed_s5, row_flag_column] = "S5_REVIEW_REQUIRED"

            remediation_stats[col] = int(remediated)
            if s5_count > 0:
                pct = s5_count / len(df)
                flag = "[CRITICAL]" if pct > s5_threshold else "[WARN]"
                print(f"{flag} {col}: {s5_count} rows ({pct:.1%}) diverted to S5 Forensic Buffer.")
        else:
            print(f"[WARN] Configured currency column not found after normalization: {col}")

    # -----------------------------
    # Date parsing
    # -----------------------------
    for col in date_columns:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    # -----------------------------
    # Recompute expressions
    # -----------------------------
    allow_unsafe_recompute = bool(config.get("allow_unsafe_recompute", False))
    for col, expr in recompute.items():
        try:
            if not allow_unsafe_recompute and not is_safe_recompute_expression(expr, df.columns):
                print(
                    f"[WARN] recompute skipped for {col}: unsafe expression '{expr}'. "
                    "Enable allow_unsafe_recompute to bypass."
                )
                continue
            df[col] = df.eval(expr, engine="python")
        except Exception as e:
            print(f"[WARN] recompute failed for {col}: {e}")

    # -----------------------------
    # Data Quality Report
    # -----------------------------
    quality_columns = normalize_column_list(
        config.get("quality_columns", numeric_columns + date_columns)
    )
    if quality_columns:
        print("\n=== DATA QUALITY REPORT ===")
        print(f"Total rows: {len(df)}")
        needs_review_mask = pd.Series(False, index=df.index)
        for col in quality_columns:
            if col in df.columns:
                null_count = df[col].isna().sum()
                print(f"  Rows with missing {col}: {null_count}")
                if null_count > 0:
                    needs_review_mask |= df[col].isna()
        for col, count in remediation_stats.items():
            print(f"  Rows remediated in {col}: {count}")
        print(f"  Rows needing review (any quality column null): {needs_review_mask.sum()}")

    # -----------------------------
    # Required column null diagnostics
    # -----------------------------
    if required:
        print("\n=== REQUIRED COLUMN NULL COUNTS ===")
        for col in required:
            if col in df.columns:
                print(col, df[col].isna().sum(), "nulls")
            else:
                print(col, "missing entirely")

    # -----------------------------
    # Validation rules
    # -----------------------------
    validation_fail_mask = pd.Series(False, index=df.index)
    for rule in validation_rules:
        try:
            passed = df.eval(rule, engine="python")
            validation_fail_mask |= ~passed
        except Exception as e:
            print(f"[WARN] validation rule failed '{rule}': {e}")

    # -----------------------------
    # Malformed row detection
    # -----------------------------
    print("\nMode:", mode.upper())

    print("\n=== MALFORMED ROW DIAGNOSTICS ===")

    # Missing required
    if required:
        existing = [c for c in required if c in df.columns]
        malformed_required = df[existing].isna().any(axis=1)
    else:
        malformed_required = pd.Series(False, index=df.index)

    print("Missing required:", malformed_required.sum())

    # Validation failures
    print("Validation failures:", validation_fail_mask.sum())

    # Corruption detection
    def is_corrupted_value(val):
        if not isinstance(val, str):
            return False
        return any(bad in val for bad in ["Â", "â", "¨", "‚", "…", "???"])

    corruption_mask = df.apply(
        lambda row: any(is_corrupted_value(str(v)) for v in row.values),
        axis=1
    )
    print("Corrupted rows:", corruption_mask.sum())

    # Combine
    malformed_mask = malformed_required | validation_fail_mask | corruption_mask
    malformed_rows = df[malformed_mask].copy()

    print("TOTAL malformed rows:", malformed_mask.sum())

    # -----------------------------
    # Strict mode drops malformed
    # -----------------------------
    if mode == "strict":
        df = df[~malformed_mask].copy()
        print("Strict mode: dropped", malformed_mask.sum(), "rows")

    # -----------------------------
    # Export malformed rows
    # -----------------------------
    if malformed_rows.shape[0] > 0:
        malformed_path = os.path.splitext(output_path)[0] + "_malformed_rows.csv"
        safe_write_csv(malformed_rows, malformed_path, "Malformed rows")
    else:
        print("No malformed rows detected.")

    # --- Drop rows that are fully empty ---
    df = df.dropna(how="all")

    # --- Drop stray unnamed columns ---
    df = df.loc[:, ~df.columns.str.startswith("unnamed")]

    # --- Export cleaned file ---
    output_dir = os.path.dirname(output_path)
    safe_write_csv(df, output_path, "Cleaned file")

    # --- Bifurcated export (Gold + S5 forensic buffer) ---
    currency_col_for_split = currency_columns[0] if currency_columns else None
    if currency_col_for_split and currency_col_for_split in df.columns:
        mask_quarantine = df[currency_col_for_split].isna() | s5_any_mask
    else:
        print("[WARN] No currency column found for S5 quarantine split.")
        mask_quarantine = s5_any_mask.copy()

    df_gold = df[~mask_quarantine].copy()
    df_s5 = df[mask_quarantine].copy()

    gold_filename = config.get("gold_output_filename", "cafe_sales_GOLD.csv")
    s5_filename = config.get("s5_output_filename", "S5_FORENSIC_BUFFER.csv")

    gold_path = os.path.join(output_dir, gold_filename)
    written_gold = safe_write_csv(df_gold, gold_path, "[EXPORT] Gold Layer")
    print(f"[EXPORT] Gold Layer rows: {len(df_gold)}")

    if not df_s5.empty:
        s5_path = os.path.join(output_dir, s5_filename)
        safe_write_csv(df_s5, s5_path, "[EXPORT] S5 Forensic Buffer")
        print(f"[EXPORT] S5 Forensic Buffer rows: {len(df_s5)}")
        print("         Action required: Client review needed for missing revenue signals.")

    