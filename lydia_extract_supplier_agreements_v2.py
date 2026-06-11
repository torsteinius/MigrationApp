#!/usr/bin/env python3
"""
lydia_extract_v8.py  –  PRODUKSJONSVERSJON

Endelig korrekt feltmapping etter UDF-definisjonssjekk:
  Field1Number  = Total egnethet av lokasjon (1–5)
  Field3Number  = Politispesifikt areal (m²)
  Field5Number  = Fellesareal (m²)
  Field7Number  = Innvendig parkeringsareal (m²)
  Field9        = Opsjonsmulighet (dropdown-kode)
  Field10Text   = Opsjonsbeskrivelse/Kommentar
  Field11Date   = Opsjonsfrist i leiekontrakt
  Field19Date   = Opsjonsutløp
  Field32       = Kategori forvaltning (dropdown-kode)
  Field37Text   = Renhold beskrivelse
  Field38       = Kantine (dropdown-kode)
  Field6        = Renhold (dropdown-kode)
  Field8        = Energi inkludert i felleskost (dropdown-kode)

Output:
  - lydia_avtaler_migrasjon.txt
  - lydia_avtaler_migrasjon.csv
  - øvrige CSV-er for suppliers / companies / sites / buyers / organisations

Merk:
  - Ved USE_STAGING=True brukes DB-prefix PFTSQL_
  - Schema leses fra connection-config (.env), f.eks. PFTSQL_MSSQL_DEFAULT_SCHEMA
  - Organisasjonsuttrekket er rådata; IFS-kategorisering må kvalitetssikres separat
"""

import sys
import pathlib
import datetime
import csv


# ── KONFIGURASJON ─────────────────────────────────────────────────────────────
# True  = kjør mot staging-kilde via PFTSQL_-oppsett
# False = kjør direkte mot Lydia prod-kilden
USE_STAGING = True

DB_PREFIX = "PFTSQL_" if USE_STAGING else "LYDIA_"
# ─────────────────────────────────────────────────────────────────────────────


THIS_FILE = pathlib.Path(__file__).resolve()
REPO_ROOT = None
for p in THIS_FILE.parents:
    if (p / "DivClasses").exists():
        REPO_ROOT = p
        break

if REPO_ROOT is None:
    raise RuntimeError("Fant ikke DivClasses i noen overordnet mappe.")

for key in list(sys.modules.keys()):
    if key == "DivClasses" or key.startswith("DivClasses."):
        del sys.modules[key]
if str(REPO_ROOT) in sys.path:
    sys.path.remove(str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT))
pathlib.Path(REPO_ROOT / "DivClasses" / "__init__.py").touch()

import DivClasses
from DivClasses.SQLServerBase import SqlServerBaseCls


# ── KOMPLETT MIGRASJONSUTTREKK ────────────────────────────────────────────────
# SQL-filene ligger sammen med Streamlit-migreringsappen.
SQL_DIR = THIS_FILE.parent / "SQL" / "lydia_extract_supplier_agreements_v2"


def read_sql(name):
    return (SQL_DIR / name).read_text(encoding="utf-8-sig").strip()


SQL_MIGRATION = read_sql("01_migrasjon_komplett.sql")
SQL_KPI_LINES = read_sql("02_kpi_linjedetaljer.sql")
SQL_STATS = read_sql("03_statistikk.sql")
SQL_SUPPLIERS = read_sql("11_leverandorer.sql")
SQL_COMPANIES = read_sql("12_companies_politidistrikter.sql")
SQL_SITES = read_sql("13_sites_lokasjoner.sql")
SQL_BUYERS = read_sql("14_buyers_innkjopere.sql")
SQL_ORGS = read_sql("15_alle_organisasjoner.sql")


def fmt(val):
    if val is None:
        return ""
    if isinstance(val, datetime.datetime):
        return val.strftime("%Y-%m-%d")
    if isinstance(val, bool):
        return "Ja" if val else "Nei"
    if isinstance(val, (int, float)):
        if float(val) == 0:
            return "0"
        if isinstance(val, float) and val == int(val):
            return f"{int(val):,}"
        return f"{val:,.2f}"
    return str(val)


def fmt_csv(val):
    if val is None:
        return ""
    if isinstance(val, datetime.datetime):
        return val.strftime("%Y-%m-%d")
    if isinstance(val, bool):
        return "Ja" if val else "Nei"
    return (
        str(val)
        .replace("\r\n", " ")
        .replace("\n", " ")
        .replace("\r", " ")
        .replace("\t", " ")
        .strip()
    )


def write_section(f, title, rows, col_names):
    f.write("\n" + "=" * 120 + "\n")
    f.write(f"  {title}\n")
    f.write("=" * 120 + "\n")
    if not rows:
        f.write("  (ingen rader)\n")
        return

    widths = [min(len(c), 38) for c in col_names]
    formatted = []

    for row in rows:
        frow = [fmt(v) for v in row]
        formatted.append(frow)
        for i, v in enumerate(frow):
            widths[i] = min(max(widths[i], len(v)), 38)

    def trunc(s, w):
        return s[: w - 1] + "…" if len(s) > w else s

    f.write("  " + "  ".join(trunc(c, widths[i]).ljust(widths[i]) for i, c in enumerate(col_names)) + "\n")
    f.write("  " + "  ".join("-" * w for w in widths) + "\n")
    for frow in formatted:
        f.write("  " + "  ".join(trunc(v, widths[i]).ljust(widths[i]) for i, v in enumerate(frow)) + "\n")
    f.write(f"\n  → {len(rows)} rader\n")


def write_csv(path, col_names, rows, label, sample=25):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(col_names)
        for row in rows:
            writer.writerow([fmt_csv(v) for v in row])
    print(f"  CSV: {path}  ({len(rows)} rader) – {label}")

    sample_path = path.with_stem(path.stem + "_sample")
    with open(sample_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(col_names)
        for row in rows[:sample]:
            writer.writerow([fmt_csv(v) for v in row])
    print(f"  CSV: {sample_path}  ({min(len(rows), sample)} rader) – {label} [sample]")


def run(db, label, sql):
    print(f"  Henter: {label} ...")
    try:
        cursor = db._conn.cursor()
        cursor.execute(sql)
        col_names = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        cursor.close()
        print(f"    → {len(rows)} rader")
        return col_names, list(rows)
    except Exception as e:
        msg = str(e)[:160]
        print(f"    ⚠️  Feil: {msg}")
        return ["feil"], [[msg]]


def main():
    base = pathlib.Path(__file__).parent
    txt_file = base / "lydia_avtaler_migrasjon.txt"
    csv_main = base / "lydia_avtaler_migrasjon.csv"
    csv_kpi = base / "lydia_kpi_linjer.csv"
    csv_suppliers = base / "lydia_suppliers.csv"
    csv_companies = base / "lydia_companies.csv"
    csv_sites = base / "lydia_sites.csv"
    csv_buyers = base / "lydia_buyers.csv"
    csv_orgs = base / "lydia_organisations.csv"

    if USE_STAGING:
        sql_migration = SQL_MIGRATION
        sql_kpi_lines = SQL_KPI_LINES
        sql_stats = SQL_STATS
        sql_suppliers = SQL_SUPPLIERS
        sql_companies = SQL_COMPANIES
        sql_sites = SQL_SITES
        sql_buyers = SQL_BUYERS
        sql_orgs = SQL_ORGS
    else:
        sql_migration = (
            SQL_MIGRATION
            .replace("STAGING_Lydia.", "")
            .replace("OrgHierk", "OrgUnit")
            .replace("sup.Navn", "sup.DisplayName")
            .replace("sup.ORGNR", "sup.OrganizationNumber")
            .replace("cus.Navn", "cus.DisplayName")
            .replace("cus.Nr", "cus.Num")
            .replace("POSTADR", "PostalArea")
            .replace("pa.Uniktnr", "pa.Id")
            .replace("pa.POSTNR", "pa.Num")
            .replace("pa.POSTSTED", "pa.Name")
            .replace("sup.Uniktnr", "sup.Id")
            .replace("cus.Uniktnr", "cus.Id")
        )

        sql_kpi_lines = SQL_KPI_LINES.replace("STAGING_Lydia.", "")
        sql_stats = SQL_STATS.replace("STAGING_Lydia.", "")

        sql_suppliers = (
            SQL_SUPPLIERS
            .replace("STAGING_Lydia.", "")
            .replace("OrgHierk", "OrgUnit")
            .replace("sup.Uniktnr", "sup.Id")
            .replace("sup.ORGNR", "sup.OrganizationNumber")
            .replace("sup.Nr", "sup.Num")
            .replace("sup.Navn", "sup.DisplayName")
            .replace("sup.ADRESSE", "sup.Address")
            .replace("sup.POSTNR", "sup.PostalCode")
        )

        sql_companies = (
            SQL_COMPANIES
            .replace("STAGING_Lydia.", "")
            .replace("OrgHierk", "OrgUnit")
            .replace("cus.Uniktnr", "cus.Id")
            .replace("cus.Nr", "cus.Num")
            .replace("cus.Navn", "cus.DisplayName")
            .replace("cus.ADRESSE", "cus.Address")
            .replace("cus.POSTNR", "cus.PostalCode")
        )

        sql_sites = (
            SQL_SITES
            .replace("STAGING_Lydia.", "")
            .replace("POSTADR", "PostalArea")
            .replace("pa.Uniktnr", "pa.Id")
            .replace("pa.POSTNR", "pa.Num")
            .replace("pa.POSTSTED", "pa.Name")
        )

        sql_buyers = (
            SQL_BUYERS
            .replace("STAGING_Lydia.", "")
            .replace("OrgHierk", "OrgUnit")
            .replace("b.Uniktnr", "b.Id")
            .replace("b.Nr", "b.Num")
        )

        sql_orgs = (
            SQL_ORGS
            .replace("STAGING_Lydia.", "")
            .replace("OrgHierk", "OrgUnit")
            .replace("o.Uniktnr", "o.Id")
            .replace("o.Nr", "o.Num")
            .replace("o.Navn", "o.DisplayName")
            .replace("o.ORGNR", "o.OrganizationNumber")
            .replace("o.ADRESSE", "o.Address")
            .replace("o.POSTNR", "o.PostalCode")
        )

    kilde = "staging" if USE_STAGING else "Lydia prod"
    print(f"Kobler til SQL Server (prefix={DB_PREFIX}, kilde={kilde}) ...")

    with SqlServerBaseCls(prefix=DB_PREFIX) as db:
        print(f"  Server: {db.server}  DB: {db.database}\n")

        schema = getattr(db, "default_schema", None) or getattr(db, "schema", None) or ""
        schema_prefix = f"{schema}." if schema else ""

        def apply_schema(sql):
            return sql.replace("STAGING_Lydia.", schema_prefix)

        main_cols, main_rows = run(db, "Komplett migrasjonsuttrekk", apply_schema(sql_migration))
        kpi_cols, kpi_rows = run(db, "KPI-linjedetaljer", apply_schema(sql_kpi_lines))
        stat_cols, stat_rows = run(db, "Statistikk", apply_schema(sql_stats))
        sup_cols, sup_rows = run(db, "Leverandører", apply_schema(sql_suppliers))
        comp_cols, comp_rows = run(db, "Companies/Politidistrikter", apply_schema(sql_companies))
        site_cols, site_rows = run(db, "Sites/Lokasjoner", apply_schema(sql_sites))
        buyer_cols, buyer_rows = run(db, "Buyers/Innkjøpere", apply_schema(sql_buyers))
        org_cols, org_rows = run(db, "Alle organisasjoner", apply_schema(sql_orgs))

    with open(txt_file, "w", encoding="utf-8") as f:
        f.write("LYDIA → IFS  –  Supplier Agreement migrasjonsuttrekk\n")
        f.write(f"Generert: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        write_section(f, "STATISTIKK", stat_rows, stat_cols)
        write_section(f, "KOMPLETT MIGRASJONSVISNING", main_rows, main_cols)
        write_section(f, "KPI-LINJEDETALJER", kpi_rows, kpi_cols)
        write_section(f, "LEVERANDØRER", sup_rows, sup_cols)
        write_section(f, "COMPANIES / POLITIDISTRIKTER", comp_rows, comp_cols)
        write_section(f, "SITES / LOKASJONER", site_rows, site_cols)
        write_section(f, "BUYERS / INNKJØPERE", buyer_rows, buyer_cols)
        write_section(f, "ALLE ORGANISASJONER", org_rows, org_cols)
        f.write("\n" + "=" * 120 + "\n  SLUTT\n" + "=" * 120 + "\n")

    if main_rows:
        write_csv(csv_main, main_cols, main_rows, "Avtaler")
    if kpi_rows:
        write_csv(csv_kpi, kpi_cols, kpi_rows, "KPI-linjer")
    if sup_rows:
        write_csv(csv_suppliers, sup_cols, sup_rows, "Leverandører")
    if comp_rows:
        write_csv(csv_companies, comp_cols, comp_rows, "Companies")
    if site_rows:
        write_csv(csv_sites, site_cols, site_rows, "Sites")
    if buyer_rows:
        write_csv(csv_buyers, buyer_cols, buyer_rows, "Buyers")
    if org_rows:
        write_csv(csv_orgs, org_cols, org_rows, "Organisasjoner")

    print(f"\n✅  TXT: {txt_file}")


if __name__ == "__main__":
    main()
