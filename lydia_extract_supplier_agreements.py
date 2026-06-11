#!/usr/bin/env python3
"""
lydia_extract_supplier_agreements.py

Henter de viktigste feltene for Supplier Agreement-migrering fra Lydia
til IFS. Skriver resultatene til en lesbar .txt-fil for manuell verifisering.

Plassering: Repo/lydia/lydia_extract_supplier_agreements.py
Output:     lydia_supplier_agreements_dump.txt  (samme mappe som scriptet)

Bruk:
    python lydia_extract_supplier_agreements.py
"""

import sys
import pathlib
import datetime

# ── Prosjekt-root (parent av lydia/) ────────────────────────────────────────
ROOT_DIR = pathlib.Path(__file__).resolve().parent.parent

# ── Fjern evt. konflikterende DivClasses fra sys.modules ────────────────────
for key in list(sys.modules.keys()):
    if key == "DivClasses" or key.startswith("DivClasses."):
        del sys.modules[key]

if str(ROOT_DIR) in sys.path:
    sys.path.remove(str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR))

init_file = ROOT_DIR / "DivClasses" / "__init__.py"
if not init_file.exists():
    init_file.touch()

import DivClasses
from DivClasses.SQLServerBase import SqlServerBaseCls

TOP_N = 20

# ── Spørringer ───────────────────────────────────────────────────────────────

# Seksjon 1+2: Avtalehode – identifikasjon og hoveddatoer
SQL_AGREEMENT = f"""
SELECT TOP {TOP_N}
    a.Id,
    a.Num                       AS Avtalenr,
    a.Name                      AS Avtalenavn,
    a.AgreementTypeId,
    a.RentalAgreementTypeId,
    a.StartDate                 AS KontraktFra,
    a.EndDate                   AS KontraktTil,
    a.AgreementDate             AS Signaturdato,
    a.TakeOverDate              AS Overtagelsesdato,
    a.SupplierId,
    a.CustomerId,
    a.SubmitterId,
    a.CustomerContactId,
    a.OwnerId,
    a.LocId,
    a.CaseReference             AS Websak,
    a.AgreementPlace            AS Oppmøtested,
    a.Description,
    a.StatusId,
    a.EstimatedAgreementValue
FROM Agreement a
ORDER BY a.Id DESC
"""

# Seksjon 3: Avtalevilkår – opsjoner og oppsigelse
SQL_AGREEMENT_CONDITIONS = f"""
SELECT TOP {TOP_N}
    a.Id,
    a.Num                           AS Avtalenr,
    a.Name                          AS Avtalenavn,
    a.PrioritizedOption             AS Opsjonmulighet,
    a.RenewalTerms                  AS OpsjonBeskrivelse,
    a.RenewalPeriod                 AS Opsjonsperiode,
    a.ExtendedPeriodLimit,
    a.ExtendedPeriodDuration        AS OpsjonUtløp,
    a.ExtendedPeriodTerms,
    a.HaveTerminationClause         AS HarOppsigelse,
    a.TerminationPeriod             AS OppsigelsestidMND,
    a.TerminationNoticeDate         AS Oppsigelsesdato,
    a.TerminationClause             AS OppsigelsesVilkår,
    a.TerminationClausePeriod,
    a.PaymentTerm                   AS PayTermId,
    a.PaymentFrequency,
    a.Duration,
    a.NoticeInternal,
    a.NoticeInvoice
FROM Agreement a
ORDER BY a.Id DESC
"""

# Seksjon 4+5: Tjenester og tilleggsinfo – UserDefinedFieldsWide (Agreement-segmentet)
# Vi tar alle felt som ikke er NULL for å finne hvilke felt som faktisk er i bruk
SQL_UDF = f"""
SELECT TOP {TOP_N}
    u.Id,
    u.ParentId,
    u.SegType,
    u.Field1Type,  u.Field1Text,  u.Field1Number,  u.Field1DateTime,
    u.Field2Type,  u.Field2Text,  u.Field2Number,  u.Field2DateTime,
    u.Field3Type,  u.Field3Text,  u.Field3Number,  u.Field3DateTime,
    u.Field4Type,  u.Field4Text,  u.Field4Number,  u.Field4DateTime,
    u.Field5Type,  u.Field5Text,  u.Field5Number,  u.Field5DateTime,
    u.Field6Type,  u.Field6Text,  u.Field6Number,  u.Field6DateTime,
    u.Field7Type,  u.Field7Text,  u.Field7Number,  u.Field7DateTime,
    u.Field8Type,  u.Field8Text,  u.Field8Number,  u.Field8DateTime,
    u.Field9Type,  u.Field9Text,  u.Field9Number,  u.Field9DateTime,
    u.Field10Type, u.Field10Text, u.Field10Number, u.Field10DateTime
FROM UserDefinedFieldsWide u
WHERE u.SegType IN (
    SELECT DISTINCT a.AgreementTypeId FROM Agreement a WHERE a.AgreementTypeId IS NOT NULL
)
   OR u.ParentId IN (SELECT TOP 100 a.Id FROM Agreement a ORDER BY a.Id DESC)
ORDER BY u.Id DESC
"""

# Seksjon 6: Linjedata – AgreementItem (priser og artikler)
SQL_AGREEMENT_ITEM = f"""
SELECT TOP {TOP_N}
    ai.Id,
    ai.AgreementId,
    a.Num                       AS Avtalenr,
    a.Name                      AS Avtalenavn,
    ai.LineNumber               AS LinjeNr,
    ai.Num                      AS Artikkelnr,
    ai.Name                     AS Beskrivelse,
    ai.ItemType,
    ai.Amount                   AS Pris,
    ai.OnAccountAmount,
    ai.FromDate                 AS FraDato,
    ai.ToDate                   AS TilDato,
    ai.StatusId,
    ai.PaymentFrequencyType     AS Frekvens,
    ai.RegulationType,
    ai.PriceRegulationMethodId,
    ai.UnitId,
    ai.AreaType,
    ai.ValueAddedTaxStatusId
FROM AgreementItem ai
JOIN Agreement a ON a.Id = ai.AgreementId
ORDER BY ai.AgreementId DESC, ai.LineNumber
"""

# Seksjon 7: Indeksregulering – AgreementItemAdjustmentLine
SQL_INDEX_REG = f"""
SELECT TOP {TOP_N}
    al.Id,
    al.ParentId                 AS AgreementItemId,
    ai.AgreementId,
    a.Num                       AS Avtalenr,
    ai.LineNumber               AS LinjeNr,
    ai.Name                     AS LinjeNavn,
    ai.RegulationType,
    al.FromDate                 AS GjelderFra,
    al.ToDate                   AS GjelderTil,
    al.OnAccountAmount          AS StartIndex,
    al.ActualAmount             AS ReferanseIndex,
    al.AdjustmentAmount         AS Prosent,
    al.Type                     AS JusteringsType,
    al.ApprovedDate
FROM AgreementItemAdjustmentLine al
JOIN AgreementItem ai ON ai.Id = al.ParentId
JOIN Agreement a      ON a.Id  = ai.AgreementId
ORDER BY al.Id DESC
"""


# ── Hjelpefunksjoner ─────────────────────────────────────────────────────────

def fmt(val):
    """Formater en enkelt verdi til lesbar streng."""
    if val is None:
        return ""
    if isinstance(val, datetime.datetime):
        return val.strftime("%Y-%m-%d")
    if isinstance(val, float):
        return f"{val:,.2f}"
    return str(val)


def write_section(f, title, rows, col_names):
    """Skriv én seksjon til filen med lesbar tabell-formatering."""
    f.write("\n")
    f.write("=" * 100 + "\n")
    f.write(f"  {title}\n")
    f.write("=" * 100 + "\n")

    if not rows:
        f.write("  (ingen rader)\n")
        return

    # Beregn kolonnebredder
    widths = [len(c) for c in col_names]
    formatted = []
    for row in rows:
        frow = [fmt(v) for v in row]
        formatted.append(frow)
        for i, v in enumerate(frow):
            widths[i] = max(widths[i], len(v))

    # Kapp bredde for å unngå altfor brede kolonner
    widths = [min(w, 40) for w in widths]

    def trunc(s, w):
        return s[:w-1] + "…" if len(s) > w else s

    # Header
    header = "  " + "  ".join(trunc(c, widths[i]).ljust(widths[i]) for i, c in enumerate(col_names))
    f.write(header + "\n")
    f.write("  " + "  ".join("-" * w for w in widths) + "\n")

    # Rader
    for frow in formatted:
        line = "  " + "  ".join(trunc(v, widths[i]).ljust(widths[i]) for i, v in enumerate(frow))
        f.write(line + "\n")

    f.write(f"\n  → {len(rows)} rader vist (TOP {TOP_N})\n")


def run_query(db, label, sql):
    """Kjør spørring og returner (kolonnenavn, rader)."""
    print(f"  Henter: {label} ...")
    try:
        rows = db.fetchall(sql)
        # Hent kolonnenavn via cursor
        cursor = db._conn.cursor()
        cursor.execute(sql)
        col_names = [desc[0] for desc in cursor.description]
        cursor.close()
        print(f"    → {len(rows)} rader")
        return col_names, rows
    except Exception as e:
        print(f"    ⚠️  Feil: {e}")
        return [], []


# ── Hovedprogram ─────────────────────────────────────────────────────────────

def main():
    output_file = pathlib.Path(__file__).parent / "lydia_supplier_agreements_dump.txt"

    print("Kobler til SQL Server (prefix=LYDIA_) ...")
    with SqlServerBaseCls(prefix="LYDIA_") as db:
        print(f"  Server: {db.server}  DB: {db.database}\n")

        sections = [
            ("Seksjon 1+2 – Avtalehode (identifikasjon og datoer)",  SQL_AGREEMENT),
            ("Seksjon 3   – Avtalevilkår (opsjoner og oppsigelse)",   SQL_AGREEMENT_CONDITIONS),
            ("Seksjon 4+5 – Egendefinerte felt (UserDefinedFieldsWide)", SQL_UDF),
            ("Seksjon 6   – Linjedata / AgreementItem",               SQL_AGREEMENT_ITEM),
            ("Seksjon 7   – Indeksregulering / AdjustmentLine",       SQL_INDEX_REG),
        ]

        results = []
        for label, sql in sections:
            col_names, rows = run_query(db, label, sql)
            results.append((label, col_names, rows))

    # ── Skriv til fil ────────────────────────────────────────────────────────
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("LYDIA → IFS  –  Supplier Agreement datadump\n")
        f.write(f"Generert: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"TOP {TOP_N} rader per seksjon\n")

        for label, col_names, rows in results:
            if col_names:
                write_section(f, label, rows, col_names)
            else:
                f.write(f"\n{'='*100}\n  {label}\n{'='*100}\n  (spørring feilet)\n")

        f.write("\n" + "=" * 100 + "\n")
        f.write("  SLUTT PÅ DUMP\n")
        f.write("=" * 100 + "\n")

    print(f"\n✅  Skrevet til: {output_file}")


if __name__ == "__main__":
    main()