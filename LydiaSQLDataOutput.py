# app.py
import sys
import pathlib
import io
import re
import json
import hashlib
import subprocess
import datetime
import html

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="Migreringsdata SQL", layout="wide")

# ---- Finn repo-root med DivClasses ----
THIS_FILE = pathlib.Path(__file__).resolve()
ROOT_DIR = THIS_FILE.parent
SQL_DIR = ROOT_DIR / "SQL"
CUSTOM_SQL_DIR = SQL_DIR / "_egne_sporringer"
CUSTOM_SQL_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR = ROOT_DIR / "Resultater"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

REPO_ROOT = None
for p in THIS_FILE.parents:
    if (p / "DivClasses").exists():
        REPO_ROOT = p
        break

if REPO_ROOT is None:
    st.error("Fant ikke DivClasses i noen overordnet mappe.")
    st.stop()

sys.path.insert(0, str(REPO_ROOT))

from DivClasses.SQLServerBase import SqlServerBaseCls


# ---- Konfig ----
USE_STAGING = st.sidebar.toggle("Bruk staging", value=True)
DB_PREFIX = "PFTSQL_" if USE_STAGING else "LYDIA_"

st.markdown("""
<style>
.block-container { padding-top: 1.5rem; }
div[data-testid="stSidebar"] { background-color: #101827; }

.sql-card {
    border: 1px solid #263244;
    border-radius: 14px;
    padding: 1rem;
    background: #111827;
}

.sql-outdated-label {
    margin: 0.15rem 0 0.25rem 0;
    padding: 0.35rem 0.5rem;
    border-left: 4px solid #ef4444;
    border-radius: 6px;
    background: rgba(239, 68, 68, 0.14);
    color: #fecaca;
    font-size: 0.84rem;
    line-height: 1.25;
}

.sql-outdated-main {
    margin: 0.25rem 0 0.75rem 0;
    padding: 0.65rem 0.8rem;
    border: 1px solid rgba(239, 68, 68, 0.45);
    border-left: 5px solid #ef4444;
    border-radius: 8px;
    background: rgba(239, 68, 68, 0.10);
    color: #fee2e2;
}
</style>
""", unsafe_allow_html=True)

SQL_SEPARATOR_RE = re.compile(
    r"^\s*--\s*===\s*(?P<kind>SQL_BASE|SQL-BASE|SQL_PREFIX|SQL-PREFIX|SQL_RESET|SQL-RESET|SQL)\s*:?\s*(?P<title>.*?)\s*===\s*$",
    re.IGNORECASE | re.MULTILINE,
)
SQL_STATUS_RE = re.compile(
    r"^\s*--\s*(?:(?:MIGRATION_)?STATUS\s*:\s*(?P<status>[A-ZÃÆØÅa-zÃ¦Ã¸Ã¥_-]+)(?:\s*[-:]\s*(?P<status_reason>.*))?|(?P<obsolete>UTDATERT|OBSOLETE)\s*:?\s*(?P<obsolete_reason>.*))\s*$",
    re.IGNORECASE | re.MULTILINE,
)

SQL_DATE_RE = re.compile(
    r"^\s*--\s*(?:DATO|DATE|SQL_DATO|SQL_DATE)\s*:\s*(?P<date>\d{4}-\d{2}-\d{2})\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def find_sql_files(base: pathlib.Path):
    if not base.exists():
        return []
    return sorted(base.rglob("*.sql"))


def sql_status(sql_text: str) -> dict:
    for match in SQL_STATUS_RE.finditer(sql_text):
        status = (match.group("status") or match.group("obsolete") or "").strip().lower()
        reason = (match.group("status_reason") or match.group("obsolete_reason") or "").strip()

        if status in {"utdatert", "obsolete"}:
            return {
                "outdated": True,
                "reason": reason,
            }

    return {
        "outdated": False,
        "reason": "",
    }


def sql_metadata_date(sql_text: str) -> str | None:
    match = SQL_DATE_RE.search(sql_text)
    return match.group("date") if match else None


def sql_file_date(path: pathlib.Path, sql_text: str | None = None) -> dict:
    if sql_text is None:
        sql_text = path.read_text(encoding="utf-8-sig")

    explicit_date = sql_metadata_date(sql_text)
    if explicit_date:
        return {
            "date": explicit_date,
            "source": "SQL-kommentar",
        }

    modified = datetime.datetime.fromtimestamp(path.stat().st_mtime)
    return {
        "date": modified.strftime("%Y-%m-%d"),
        "source": "Sist endret",
    }


def update_sql_outdated_marker(sql_text: str, outdated: bool, reason: str = "") -> str:
    lines = sql_text.splitlines()
    newline = "\n" if sql_text.endswith("\n") else ""

    replacement = None
    if outdated:
        replacement = "-- STATUS: UTDATERT"
        if reason.strip():
            replacement += f": {reason.strip()}"

    updated = []
    replaced = False

    for line in lines:
        if SQL_STATUS_RE.match(line):
            if replacement and not replaced:
                updated.append(replacement)
                replaced = True
            continue

        updated.append(line)

    if replacement and not replaced:
        insert_at = 0
        if updated and updated[0].startswith("\ufeff"):
            updated[0] = updated[0].lstrip("\ufeff")
        updated.insert(insert_at, replacement)

    return "\n".join(updated) + newline


@st.cache_data(show_spinner=False)
def read_sql_status(path_str: str) -> dict:
    return sql_status(pathlib.Path(path_str).read_text(encoding="utf-8-sig"))


@st.cache_data(show_spinner=False)
def read_sql_file_date(path_str: str) -> dict:
    path = pathlib.Path(path_str)
    return sql_file_date(path, path.read_text(encoding="utf-8-sig"))


def rel_to_root(path: pathlib.Path) -> str:
    try:
        return path.resolve().relative_to(ROOT_DIR).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def git_run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def git_current_commit() -> str:
    result = git_run(["rev-parse", "--short", "HEAD"])
    return result.stdout.strip() if result.returncode == 0 else "ukjent"


def git_status_for_paths(paths: list[pathlib.Path]) -> str:
    if not paths:
        return ""

    rel_paths = [rel_to_root(p) for p in paths]
    result = git_run(["status", "--short", "--", *rel_paths])
    return result.stdout.strip() if result.returncode == 0 else result.stderr.strip()


def git_log_for_path(path: pathlib.Path, limit: int = 12) -> str:
    result = git_run([
        "log",
        f"-{limit}",
        "--date=short",
        "--pretty=format:%h  %ad  %s",
        "--",
        rel_to_root(path),
    ])

    if result.returncode != 0:
        return result.stderr.strip()

    return result.stdout.strip() or "Ingen commits funnet for denne filen."


def git_commit_paths(paths: list[pathlib.Path], message: str) -> tuple[bool, str]:
    if not paths:
        return False, "Ingen filer å committe."

    rel_paths = [rel_to_root(p) for p in paths]

    add_result = git_run(["add", "--", *rel_paths])
    if add_result.returncode != 0:
        return False, add_result.stderr.strip() or add_result.stdout.strip()

    commit_result = git_run(["commit", "-m", message])
    output = "\n".join(
        part.strip()
        for part in [commit_result.stdout, commit_result.stderr]
        if part.strip()
    )

    if commit_result.returncode != 0:
        return False, output or "Git commit feilet."

    return True, output


def clean_df_for_export(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    for col in out.columns:
        if out[col].dtype == "object":
            out[col] = (
                out[col]
                .astype(str)
                .str.replace("\r\n", " ", regex=False)
                .str.replace("\n", " ", regex=False)
                .str.replace("\r", " ", regex=False)
                .str.replace("\t", " ", regex=False)
            )

    return out


@st.cache_data(show_spinner=False)
def read_sql_file(path_str: str) -> str:
    return pathlib.Path(path_str).read_text(encoding="utf-8-sig")


def build_all_sql_source_text(sql_files: list[pathlib.Path], sql_dir: pathlib.Path) -> str:
    chunks = [
        "SAMLET SQL-INNHOLD",
        "=" * 80,
        "",
    ]

    for path in sorted(sql_files):
        rel = path.relative_to(sql_dir)
        content = read_sql_file(str(path))

        chunks += [
            "-" * 80,
            f"PATH: {path}",
            f"RELATIV PATH: {rel}",
            f"FILNAVN: {path.name}",
            "-" * 80,
            content.strip(),
            "",
        ]

    return "\n".join(chunks).strip()


def run_sql(sql: str, db_prefix: str) -> pd.DataFrame:
    with SqlServerBaseCls(prefix=db_prefix) as db:
        return pd.read_sql(sql, db._conn)


def to_excel_bytes(df: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()

    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Resultat")

    return buffer.getvalue()


def safe_sql_filename(name: str) -> str:
    safe = name.strip().replace("\\", "/").split("/")[-1]

    if not safe:
        safe = "egen_sporring.sql"

    if not safe.lower().endswith(".sql"):
        safe += ".sql"

    return safe


def safe_file_part(name: str) -> str:
    safe = name.lower().strip()
    safe = re.sub(r"[^a-z0-9æøåÆØÅ_-]+", "_", safe)
    safe = safe.strip("_")
    return safe or "resultat"


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def dataframe_signature(df: pd.DataFrame) -> dict:
    quality = column_quality_df(df)

    return {
        "rows": int(len(df)),
        "columns": list(df.columns),
        "column_count": int(len(df.columns)),
        "quality": quality.to_dict(orient="records"),
    }


def latest_previous_manifest(base_name: str, current_run_dir: pathlib.Path | None = None) -> dict | None:
    base_safe = safe_file_part(base_name)
    manifests = sorted(RESULTS_DIR.glob(f"{base_safe}_*/manifest.json"), reverse=True)

    for manifest_path in manifests:
        if current_run_dir and manifest_path.parent == current_run_dir:
            continue

        try:
            return json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            continue

    return None


def compare_manifest_results(previous: dict | None, current: dict) -> str:
    if not previous:
        return "Ingen tidligere lagret kjøring funnet for samme base-navn."

    lines = [
        "# Endringer mot forrige lagrede kjøring",
        "",
        f"Forrige kjøring: {previous.get('run_id', 'ukjent')}",
        f"Denne kjøringen: {current.get('run_id', 'ukjent')}",
        "",
    ]

    previous_results = {r.get("title"): r for r in previous.get("results", [])}
    current_results = {r.get("title"): r for r in current.get("results", [])}

    removed_results = sorted(set(previous_results) - set(current_results))
    added_results = sorted(set(current_results) - set(previous_results))

    if added_results:
        lines += ["## Nye SQL-resultater", *[f"- {name}" for name in added_results], ""]

    if removed_results:
        lines += ["## Fjernede SQL-resultater", *[f"- {name}" for name in removed_results], ""]

    for title in sorted(set(previous_results) & set(current_results)):
        prev = previous_results[title]
        curr = current_results[title]
        prev_cols = set(prev.get("columns", []))
        curr_cols = set(curr.get("columns", []))
        added_cols = sorted(curr_cols - prev_cols)
        removed_cols = sorted(prev_cols - curr_cols)

        prev_quality = {row.get("Kolonne"): row for row in prev.get("quality", [])}
        curr_quality = {row.get("Kolonne"): row for row in curr.get("quality", [])}

        dramatic_quality = []
        for col in sorted(prev_cols & curr_cols):
            prev_pct = float(prev_quality.get(col, {}).get("Fylt %", 0))
            curr_pct = float(curr_quality.get(col, {}).get("Fylt %", 0))
            diff = round(curr_pct - prev_pct, 2)
            if abs(diff) >= 20:
                dramatic_quality.append((col, prev_pct, curr_pct, diff))

        row_diff = int(curr.get("rows", 0)) - int(prev.get("rows", 0))

        if added_cols or removed_cols or dramatic_quality or row_diff:
            lines += [f"## {title}", ""]
            lines.append(
                f"Rader: {prev.get('rows', 0):,} -> {curr.get('rows', 0):,} "
                f"({row_diff:+,})"
            )

            if added_cols:
                lines += ["", "Kolonner lagt til:", *[f"- {c}" for c in added_cols]]

            if removed_cols:
                lines += ["", "Kolonner fjernet:", *[f"- {c}" for c in removed_cols]]

            if dramatic_quality:
                lines += ["", "Datakvalitet endret med minst 20 prosentpoeng:"]
                lines += [
                    f"- {col}: {prev_pct:.2f}% -> {curr_pct:.2f}% ({diff:+.2f} pp)"
                    for col, prev_pct, curr_pct, diff in dramatic_quality
                ]

            lines.append("")

    if len(lines) == 5:
        lines.append("Ingen kolonneendringer eller dramatiske datakvalitetsendringer funnet.")

    return "\n".join(lines).strip()


def archive_result_analysis(results: list[dict], base_name: str, db_prefix: str) -> tuple[pathlib.Path, list[pathlib.Path], dict, str]:
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    run_id = f"{safe_file_part(base_name)}_{timestamp}"
    run_dir = RESULTS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    files_written: list[pathlib.Path] = []
    manifest = {
        "run_id": run_id,
        "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "db_prefix": db_prefix,
        "git_commit_before_archive": git_current_commit(),
        "base_name": base_name,
        "results": [],
    }

    for index, result in enumerate(results, start=1):
        title = result["title"]
        df = result["df"]
        sql_text = result["sql"]
        file_part = f"{index:02d}_{safe_file_part(title)}"

        quality_path = run_dir / f"{file_part}_datakvalitet.csv"
        columns_path = run_dir / f"{file_part}_kolonner.csv"

        column_quality_df(df).to_csv(quality_path, index=False, sep=";", encoding="utf-8-sig")
        pd.DataFrame(
            {
                "KolonneNr": range(1, len(df.columns) + 1),
                "Kolonne": list(df.columns),
                "Datatype": [str(df[col].dtype) for col in df.columns],
            }
        ).to_csv(columns_path, index=False, sep=";", encoding="utf-8-sig")

        files_written += [quality_path, columns_path]

        signature = dataframe_signature(df)
        manifest["results"].append(
            {
                "title": title,
                "source_file": result.get("source_file", ""),
                "sql_hash": content_hash(sql_text),
                "quality_file": quality_path.name,
                "columns_file": columns_path.name,
                **signature,
            }
        )

    previous = latest_previous_manifest(base_name, current_run_dir=run_dir)
    comparison_text = compare_manifest_results(previous, manifest)

    manifest_path = run_dir / "manifest.json"
    comparison_path = run_dir / "endringer_mot_forrige.md"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    comparison_path.write_text(comparison_text + "\n", encoding="utf-8")

    files_written += [manifest_path, comparison_path]

    return run_dir, files_written, manifest, comparison_text


def split_multi_sql(
    sql_text: str,
    active_prefix_blocks: list[str] | None = None,
    return_prefix_blocks: bool = False,
):
    matches = list(SQL_SEPARATOR_RE.finditer(sql_text))

    if active_prefix_blocks is None:
        active_prefix_blocks = []

    active_prefix_blocks = list(active_prefix_blocks)
    parts = []

    if not matches:
        clean = sql_text.strip()

        if clean:
            parts.append(("SQL 1", clean))

        if return_prefix_blocks:
            return parts, active_prefix_blocks

        return parts

    for i, match in enumerate(matches):
        kind = match.group("kind").upper().replace("-", "_")
        title = match.group("title").strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(sql_text)

        block_sql = sql_text[start:end].strip()

        if kind in ("SQL_BASE", "SQL_PREFIX"):
            if block_sql:
                active_prefix_blocks = [block_sql]
            continue

        if kind == "SQL_RESET":
            active_prefix_blocks = []
            continue

        if kind != "SQL":
            continue

        if not block_sql:
            continue

        if active_prefix_blocks:
            final_sql = "\n\n".join(active_prefix_blocks + [block_sql]).strip()
        else:
            final_sql = block_sql

        parts.append((title or f"SQL {len(parts) + 1}", final_sql))

    if return_prefix_blocks:
        return parts, active_prefix_blocks

    return parts
def df_to_paste_text(title: str, df: pd.DataFrame, max_rows: int = 200) -> str:
    sample = clean_df_for_export(df.head(max_rows))

    return (
        f"\n\n## {title}\n"
        f"Rader: {len(df):,}, Kolonner: {len(df.columns):,}\n\n"
        + sample.to_csv(index=False, sep="\t")
    )


def df_to_clipboard_text(df: pd.DataFrame) -> str:
    return clean_df_for_export(df).to_csv(index=False, sep="\t")


# ---- NY: datakvalitet ----
def column_quality_df(df: pd.DataFrame) -> pd.DataFrame:
    total = len(df)

    rows = []

    for col in df.columns:
        series = df[col]
        null_count = int(series.isna().sum())

        if series.dtype == "object":
            empty_string_count = int(
                series.fillna("")
                .astype(str)
                .str.strip()
                .eq("")
                .sum()
            )
            empty_string_only = max(0, empty_string_count - null_count)
        else:
            empty_string_only = 0

        not_filled = null_count + empty_string_only
        filled = total - not_filled

        rows.append(
            {
                "Kolonne": col,
                "Fylt": int(filled),
                "Ikke fylt": int(not_filled),
                "NULL": int(null_count),
                "Tom tekst": int(empty_string_only),
                "Fylt %": round((filled / total * 100), 2) if total else 0,
                "Ikke fylt %": round((not_filled / total * 100), 2) if total else 0,
                "Datatype": str(series.dtype),
            }
        )

    return pd.DataFrame(rows)
def quality_df_to_paste_text(title: str, df: pd.DataFrame) -> str:
    quality = column_quality_df(df)

    if quality.empty:
        return (
            f"\n\n## Datakvalitet: {title}\n"
            f"Rader: {len(df):,}\n"
            f"Kolonner: {len(df.columns):,}\n"
            "Ingen kolonner funnet.\n"
        )

    full_table = quality.sort_values(
        by=["Fylt %", "Kolonne"],
        ascending=[True, True]
    )

    worst_columns = full_table.head(20)

    return (
        f"\n\n## Datakvalitet: {title}\n"
        f"Rader: {len(df):,}\n"
        f"Kolonner: {len(df.columns):,}\n\n"
        f"### Kolonnefylling - dårligst utfylte kolonner\n"
        + worst_columns.to_csv(index=False, sep="\t")
        + "\n"
        f"### Kolonnefylling - alle kolonner\n"
        + full_table.to_csv(index=False, sep="\t")
    )
def column_status_to_paste_text(title: str, df: pd.DataFrame) -> str:
    quality = column_quality_df(df)

    if quality.empty:
        return (
            f"\n\n## Kolonnestatus: {title}\n"
            f"Rader: {len(df):,}\n"
            f"Kolonner: {len(df.columns):,}\n"
            "Ingen kolonner funnet.\n"
        )

    status = quality[
        [
            "Kolonne",
            "Fylt",
            "Ikke fylt",
            "NULL",
            "Tom tekst",
            "Fylt %",
            "Ikke fylt %",
            "Datatype",
        ]
    ].copy()

    status = status.sort_values(
        by=["Fylt %", "Kolonne"],
        ascending=[True, True]
    )

    return (
        f"\n\n## Kolonnestatus: {title}\n"
        f"Rader: {len(df):,}\n"
        f"Kolonner: {len(df.columns):,}\n\n"
        "Status for hvor mye av hver kolonne som er fylt i SQL-resultatet.\n\n"
        + status.to_csv(index=False, sep="\t")
    )


def null_bar_chart(df: pd.DataFrame) -> go.Figure:
    total = len(df)
    cols = list(df.columns)
    not_null = [int(df[c].notna().sum()) for c in cols]
    null_counts = [int(df[c].isna().sum()) for c in cols]

    fig = go.Figure()

    fig.add_trace(go.Bar(
        name="Ikke NULL",
        y=cols,
        x=not_null,
        orientation="h",
        marker_color="#22c55e",
        text=[f"{v:,} ({v/total*100:.1f}%)" if total else "0" for v in not_null],
        textposition="inside",
        insidetextanchor="start",
        textfont=dict(color="white", size=12),
        hovertemplate="%{y}: %{x:,} ikke-NULL<extra></extra>",
    ))

    fig.add_trace(go.Bar(
        name="NULL",
        y=cols,
        x=null_counts,
        orientation="h",
        marker_color="#374151",
        text=[f"NULL: {v:,}" if v > 0 else "" for v in null_counts],
        textposition="inside",
        insidetextanchor="end",
        textfont=dict(color="#9ca3af", size=11),
        hovertemplate="%{y}: %{x:,} NULL<extra></extra>",
    ))

    chart_height = max(300, 40 * len(cols) + 80)

    fig.update_layout(
        barmode="stack",
        height=chart_height,
        margin=dict(l=0, r=20, t=30, b=20),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#e5e7eb"),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.01,
            xanchor="left",
            x=0,
        ),
        xaxis=dict(
            showgrid=True,
            gridcolor="#1f2937",
            zeroline=False,
            title=f"Antall rader (totalt {total:,})",
        ),
        yaxis=dict(
            autorange="reversed",
            tickfont=dict(size=12),
        ),
    )

    return fig


def copy_button(label: str, text: str, key: str):
    payload = json.dumps(text)

    components.html(
        f"""
        <button id="copy_{key}" style="
            background:#2563eb;
            color:white;
            border:none;
            border-radius:8px;
            padding:0.55rem 0.9rem;
            font-weight:600;
            cursor:pointer;
            width:100%;
        ">
            {label}
        </button>

        <script>
        const btn = document.getElementById("copy_{key}");

        btn.onclick = async () => {{
            await navigator.clipboard.writeText({payload});

            const oldText = btn.innerText;
            btn.innerText = "Kopiert ✓";

            setTimeout(() => {{
                btn.innerText = oldText;
            }}, 1600);
        }};
        </script>
        """,
        height=45,
    )


# ---- Sidebar / trestruktur ----
st.sidebar.title("SQL-filer")

sql_files = find_sql_files(SQL_DIR)

if not sql_files:
    st.warning(f"Fant ingen .sql-filer i: {SQL_DIR}")
    sql_files = []

groups = {}

for f in sql_files:
    rel = f.relative_to(SQL_DIR)
    folder = str(rel.parent) if str(rel.parent) != "." else "Rot"
    groups.setdefault(folder, []).append(f)

selected_file = None

for folder, files in groups.items():
    with st.sidebar.expander(folder, expanded=(folder == "Rot")):
        for f in files:
            status = read_sql_status(str(f))
            date_info = read_sql_file_date(str(f))
            date_label = f"{date_info['date']} ({date_info['source']})"
            button_label = f.name

            if status["outdated"]:
                reason = status["reason"] or "Denne SQL-en er markert som utdatert."
                st.markdown(
                    (
                        "<div class='sql-outdated-label'>"
                        f"<strong>UTDATERT</strong><br>{html.escape(f.name)}"
                        f"<br><span>{html.escape(reason)}</span>"
                        "</div>"
                    ),
                    unsafe_allow_html=True,
                )
                button_label = f"UTDATERT - {f.name}"

            if st.button(
                button_label,
                key=str(f),
                use_container_width=True,
                help=(
                    f"{date_label}. {status['reason']}"
                    if status["outdated"] and status["reason"]
                    else date_label
                ),
            ):
                selected_file = f

            st.caption(date_label)

if sql_files and "selected_sql_file" not in st.session_state:
    st.session_state.selected_sql_file = str(sql_files[0])

if selected_file:
    st.session_state.selected_sql_file = str(selected_file)
    st.session_state.pop("result_df", None)
    st.session_state.pop("multi_results", None)

selected = None

if "selected_sql_file" in st.session_state:
    selected = pathlib.Path(st.session_state.selected_sql_file)


# ---- Hovedflate ----
st.title("Migreringsdata fra Lydia / DWH")
st.caption(f"Kilde: `{DB_PREFIX}`")

with st.expander("📦 Samle alle SQL-filer til én tekstfil / ChatGPT-kilde", expanded=False):
    include_custom = st.checkbox(
        "Inkluder _egne_sporringer",
        value=True,
        help="Hvis av, tas bare SQL-filer utenfor _egne_sporringer med."
    )

    files_for_export = sql_files

    if not include_custom:
        files_for_export = [
            f for f in sql_files
            if CUSTOM_SQL_DIR not in f.parents
        ]

    samlet_sql = build_all_sql_source_text(files_for_export, SQL_DIR)

    c1, c2, c3 = st.columns([1, 1, 3])

    with c1:
        st.metric("SQL-filer", len(files_for_export))

    with c2:
        st.metric("Tegn", f"{len(samlet_sql):,}".replace(",", " "))

    with c3:
        st.download_button(
            "Last ned samlet SQL-kilde",
            data=samlet_sql.encode("utf-8-sig"),
            file_name="samlet_sql_kilde.txt",
            mime="text/plain",
            use_container_width=True,
        )

    st.text_area(
        "Samlet SQL-innhold for copy/paste",
        value=samlet_sql,
        height=500,
    )

    copy_button(
        "Kopier samlet SQL-innhold",
        samlet_sql,
        "samlet_sql_kilde"
    )

mode = st.radio(
    "SQL-modus",
    ["Velg fra fil", "Skriv egen SQL"],
    horizontal=True,
)

sql = ""
base_name = "resultat"

if mode == "Velg fra fil":

    if selected is None:
        st.info("Ingen SQL-fil valgt.")
        st.stop()

    sql = read_sql_file(str(selected))
    base_name = selected.stem
    selected_status = sql_status(sql)
    selected_date = sql_file_date(selected, sql)

    st.caption(f"SQL-fil: `{selected.relative_to(SQL_DIR)}`")
    st.caption(f"Dato: `{selected_date['date']}` ({selected_date['source']})")

    with st.container(border=True):
        mark_outdated = st.toggle(
            "Marker som utdatert",
            value=selected_status["outdated"],
            key=f"outdated_toggle_{rel_to_root(selected)}",
            help="Lagrer statusen som en kommentar i SQL-filen.",
        )
        outdated_reason = st.text_input(
            "Forklaring",
            value=selected_status["reason"],
            placeholder="F.eks. Erstattet av masterdata/11_leverandorer.sql",
            key=f"outdated_reason_{rel_to_root(selected)}",
            disabled=not mark_outdated,
        )

        if st.button(
            "Lagre status i SQL-filen",
            key=f"save_outdated_status_{rel_to_root(selected)}",
            use_container_width=True,
        ):
            selected.write_text(
                update_sql_outdated_marker(sql, mark_outdated, outdated_reason),
                encoding="utf-8",
            )
            read_sql_status.clear()
            read_sql_file_date.clear()
            read_sql_file.clear()
            st.success("Statusen er lagret i SQL-filen.")
            st.rerun()

    if selected_status["outdated"]:
        reason = selected_status["reason"] or "Denne SQL-en er markert som utdatert."
        st.markdown(
            (
                "<div class='sql-outdated-main'>"
                "<strong>UTDATERT SQL</strong><br>"
                f"{html.escape(reason)}<br>"
                "<span>Merkingen kommer fra en kommentar i SQL-filen, for eksempel "
                "<code>-- STATUS: UTDATERT</code> eller <code>-- UTDATERT: forklaring</code>.</span>"
                "</div>"
            ),
            unsafe_allow_html=True,
        )

    with st.expander("Vis SQL"):
        st.code(sql, language="sql")

    with st.expander("Git-historikk for SQL-filen", expanded=False):
        st.code(git_log_for_path(selected), language="text")
        status_text = git_status_for_paths([selected])
        if status_text:
            st.caption("Ikke-committede endringer:")
            st.code(status_text, language="text")
            selected_commit_message = st.text_input(
                "Commit-melding",
                value=f"Oppdater SQL: {selected.relative_to(SQL_DIR)}",
                key=f"commit_message_{rel_to_root(selected)}",
            )
            if st.button(
                "Commit denne SQL-filen",
                key=f"commit_sql_file_{rel_to_root(selected)}",
                use_container_width=True,
            ):
                ok, output = git_commit_paths(
                    [selected],
                    selected_commit_message.strip() or f"Oppdater SQL: {selected.name}",
                )
                if ok:
                    st.success("SQL-filen er committet til git.")
                else:
                    st.warning("Git commit feilet.")
                st.code(output, language="text")
        else:
            st.caption("Ingen lokale endringer for denne SQL-filen.")

else:

    default_sql = """
-- === SQL: Test ===
SELECT TOP 100 *
FROM INFORMATION_SCHEMA.TABLES;
"""

    sql = st.text_area(
        "Skriv SQL",
        value=st.session_state.get("custom_sql_text", default_sql),
        height=430,
        key="custom_sql_text",
    )

    st.caption("Bruk separator: -- === SQL: Navn ===")

    save_name = st.text_input(
        "Filnavn ved lagring",
        value="egen_sporring.sql"
    )

    commit_sql = st.checkbox(
        "Commit SQL til git ved lagring",
        value=True,
        help="Gjør at hver lagrede SQL-endring får en egen historikk som kan rulles frem og tilbake."
    )

    commit_sql_message = st.text_input(
        "Commit-melding for SQL",
        value=f"Oppdater SQL: {safe_sql_filename(save_name)}",
    )

    c1, c2 = st.columns([1, 4])

    with c1:
        if st.button("Lagre SQL", use_container_width=True):
            safe_name = safe_sql_filename(save_name)
            target = CUSTOM_SQL_DIR / safe_name
            target.write_text(sql, encoding="utf-8")
            if commit_sql:
                ok, output = git_commit_paths([target], commit_sql_message.strip() or f"Oppdater SQL: {safe_name}")
                if ok:
                    st.success(f"Lagret og committet: {target.relative_to(SQL_DIR)}")
                    st.code(output, language="text")
                else:
                    st.warning(f"Lagret, men git commit feilet: {target.relative_to(SQL_DIR)}")
                    st.code(output, language="text")
            else:
                st.success(f"Lagret: {target.relative_to(SQL_DIR)}")
            st.rerun()

    base_name = pathlib.Path(safe_sql_filename(save_name)).stem


col1, col2, col3 = st.columns([1, 1, 4])

with col1:
    run_clicked = st.button("Kjør SQL", type="primary", use_container_width=True)

with col2:
    max_rows = st.number_input(
        "Maks visning",
        min_value=100,
        max_value=50000,
        value=5000,
        step=500,
    )
with col3:
    run_all_clicked = st.button(
        "Kjør alle SQL-filer",
        type="secondary",
        use_container_width=True,
        help="Kjører alle .sql-filer i SQL-mappen og lager samlet kolonnestatus."
    )

if run_clicked or run_all_clicked:
    try:
        run_items = []

        if run_all_clicked:
            active_prefix_blocks = []

            for path in sql_files:
                file_sql = read_sql_file(str(path))
                rel_path = path.relative_to(SQL_DIR)

                sql_parts, active_prefix_blocks = split_multi_sql(
                    file_sql,
                    active_prefix_blocks=active_prefix_blocks,
                    return_prefix_blocks=True,
                )

                for title, one_sql in sql_parts:
                    run_items.append(
                        {
                            "title": f"{rel_path} / {title}",
                            "sql": one_sql,
                            "source_file": str(rel_path),
                        }
                    )

            base_name = "alle_sql_filer"
        else:
            for title, one_sql in split_multi_sql(sql):
                run_items.append(
                    {
                        "title": title,
                        "sql": one_sql,
                        "source_file": str(selected.relative_to(SQL_DIR)) if selected else "egen_sql",
                    }
                )

        if not run_items:
            st.warning("Ingen SQL å kjøre.")
            st.stop()

        safe_run_items = []

        for item in run_items:
            sql_to_run = item["sql"].strip()

            if re.match(r"^\s*WITH\b", sql_to_run, flags=re.IGNORECASE) and not re.search(
                r"\)\s*SELECT\b",
                sql_to_run,
                flags=re.IGNORECASE | re.DOTALL,
            ):
                st.warning(f"Hopper over SQL_BASE uten SELECT: {item['title']}")
                continue

            safe_run_items.append(item)

        if not safe_run_items:
            st.warning("Ingen kjørbare SQL-resultater funnet. Fant bare SQL_BASE/prefix-blokker.")
            st.stop()

        results = []

        with st.spinner(f"Kjører {len(safe_run_items)} SQL-spørring(er)..."):
            for item in safe_run_items:
                try:
                    df = run_sql(item["sql"], DB_PREFIX)
                except Exception as sql_error:
                    st.error(f"SQL feilet for: {item['title']}")
                    st.code(item["sql"], language="sql")
                    raise sql_error

                results.append(
                    {
                        "title": item["title"],
                        "sql": item["sql"],
                        "df": df,
                        "source_file": item["source_file"],
                    }
                )
        st.session_state.multi_results = results
        st.session_state.result_base_name = base_name

        st.success(f"OK: {len(results)} SQL-spørring(er) kjørt.")

    except Exception as e:
        st.error("SQL feilet")
        st.code(str(e))
        st.stop()

if "multi_results" in st.session_state:

    results = st.session_state.multi_results
    base_name = st.session_state.get("result_base_name", base_name)

    with st.expander("Lagre resultatanalyse og datakvalitet i git", expanded=True):
        st.caption(
            "Arkivet lagrer bare analysefiler i "
            f"`{RESULTS_DIR.relative_to(ROOT_DIR)}`. Manifestet gjør det lett å se kolonner som er lagt til/fjernet "
            "og datakvalitet som har endret seg kraftig siden forrige lagrede kjøring, uten å lagre selve SQL-resultatene."
        )

        commit_results = st.checkbox(
            "Commit analysearkiv til git",
            value=True,
            help="Anbefalt når analysen skal følge samme historikk som SQL-filene."
        )
        result_commit_message = st.text_input(
            "Commit-melding for analyse",
            value=f"Lagre SQL-resultatanalyse: {base_name}",
        )

        if st.button("Lagre resultatanalyse", type="primary", use_container_width=True):
            try:
                run_dir, files_written, manifest, comparison_text = archive_result_analysis(results, base_name, DB_PREFIX)
                st.session_state.last_result_archive = {
                    "run_dir": str(run_dir),
                    "comparison_text": comparison_text,
                    "files": [str(p) for p in files_written],
                }

                st.success(f"Lagret analysearkiv: {run_dir.relative_to(ROOT_DIR)}")
                st.code(comparison_text, language="markdown")

                if commit_results:
                    ok, output = git_commit_paths(
                        files_written,
                        result_commit_message.strip() or f"Lagre SQL-resultatanalyse: {base_name}",
                    )
                    if ok:
                        st.success("Analysearkivet er committet til git.")
                    else:
                        st.warning("Analysearkivet er lagret, men git commit feilet.")
                    st.code(output, language="text")
            except Exception as archive_error:
                st.error("Klarte ikke å lagre analysearkivet.")
                st.code(str(archive_error), language="text")

        last_archive = st.session_state.get("last_result_archive")
        if last_archive:
            st.caption(f"Sist lagret: `{pathlib.Path(last_archive['run_dir']).relative_to(ROOT_DIR)}`")

    tabs = st.tabs([r["title"] for r in results])

    samlet_tekst = ""
    samlet_datakvalitet_tekst = ""
    samlet_kolonnestatus_tekst = ""

    for tab, result in zip(tabs, results):

        title = result["title"]
        df = result["df"]

        samlet_tekst += df_to_paste_text(title, df)

        with tab:

            c1, c2, c3 = st.columns(3)
            c1.metric("Rader", f"{len(df):,}")
            c2.metric("Kolonner", f"{len(df.columns):,}")
            c3.metric("Kilde", DB_PREFIX)

            quality_df = column_quality_df(df)
            quality_paste_text = quality_df_to_paste_text(title, df)
            samlet_datakvalitet_tekst += quality_paste_text
            column_status_text = column_status_to_paste_text(title, df)
            samlet_kolonnestatus_tekst += column_status_text

            st.plotly_chart(
                null_bar_chart(df),
                use_container_width=True,
                config={"displayModeBar": False},
            )
            with st.expander("📋 Kolonnestatus for denne SQL-en", expanded=False):
                st.caption(
                    "Dette er samme status som grafen viser, men som tekst/tabell for copy/paste."
                )

                st.text_area(
                    "Kolonnestatus som tekst",
                    value=column_status_text.strip(),
                    height=320,
                    key=f"column_status_text_{safe_file_part(title)}",
                )

                copy_button(
                    f"Kopier kolonnestatus - {title}",
                    column_status_text.strip(),
                    f"column_status_{safe_file_part(title)}"
                )
            with st.expander("📋 Utskrift av kolonnefylling til ChatGPT", expanded=True):
                st.text_area(
                    f"Kolonnefylling som tekst - {title}",
                    value=quality_paste_text.strip(),
                    height=360,
                    key=f"dq_top_text_{safe_file_part(title)}",
                )

                copy_button(
                    f"Kopier kolonnefylling til ChatGPT - {title}",
                    quality_paste_text.strip(),
                    f"dq_top_{safe_file_part(title)}"
                )
            with st.expander("SQL"):
                st.code(result["sql"], language="sql")

            st.dataframe(
                df.head(int(max_rows)),
                use_container_width=True,
                height=550
            )

            with st.expander("Datakvalitet – detaljtabell per kolonne", expanded=False):
                st.dataframe(
                    quality_df,
                    use_container_width=True,
                    hide_index=True,
                    height=min(500, 80 + len(quality_df) * 35),
                )

                st.text_area(
                    f"Datakvalitet som tekst - {title}",
                    value=quality_paste_text.strip(),
                    height=320,
                    key=f"dq_text_{safe_file_part(title)}",
                )

                copy_button(
                    f"Kopier datakvalitet til ChatGPT - {title}",
                    quality_paste_text.strip(),
                    f"dq_{safe_file_part(title)}"
                )

            copy_button(
                f"Kopier resultat med headere - {title}",
                df_to_clipboard_text(df),
                safe_file_part(title)
            )

            export_df = clean_df_for_export(df)

            csv_bytes = export_df.to_csv(
                index=False,
                sep=";",
                encoding="utf-8-sig"
            ).encode("utf-8-sig")

            excel_bytes = to_excel_bytes(export_df)

            file_part = safe_file_part(title)

            d1, d2 = st.columns(2)

            with d1:
                st.download_button(
                    f"Last ned CSV - {title}",
                    data=csv_bytes,
                    file_name=f"{base_name}_{file_part}.csv",
                    mime="text/csv",
                    use_container_width=True,
                )

            with d2:
                st.download_button(
                    f"Last ned Excel - {title}",
                    data=excel_bytes,
                    file_name=f"{base_name}_{file_part}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )

    st.subheader("Kopier alle resultater til ChatGPT")

    st.text_area(
        "Samlet resultat",
        value=samlet_tekst.strip(),
        height=420,
    )

    copy_button(
        "Kopier alle resultater med headere",
        samlet_tekst.strip(),
        "alle_resultater"
    )

    st.subheader("Kopier datakvalitet / kolonnefylling til ChatGPT")

    st.text_area(
        "Samlet datakvalitet",
        value=samlet_datakvalitet_tekst.strip(),
        height=420,
    )

    copy_button(
        "Kopier samlet datakvalitet",
        samlet_datakvalitet_tekst.strip(),
        "alle_datakvalitet"
    )
    st.subheader("Kopier kolonnestatus fra alle SQL-resultater")

    st.caption(
        "Denne inneholder kun fyllgrad per kolonne for alle SQL-spørringene som ble kjørt. "
        "Bruk denne når du skal sende status tilbake til ChatGPT."
    )

    st.text_area(
        "Samlet kolonnestatus fra alle SQL-er",
        value=samlet_kolonnestatus_tekst.strip(),
        height=520,
    )

    copy_button(
        "Kopier samlet kolonnestatus",
        samlet_kolonnestatus_tekst.strip(),
        "alle_kolonnestatus"
    )

else:
    st.info("Velg en SQL-fil eller skriv egen SQL, og trykk Kjør SQL.")
