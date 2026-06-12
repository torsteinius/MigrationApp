# DBMigration

Streamlit-app for aa kjoere, dokumentere og kvalitetssikre SQL-sporringer brukt i databasemigrering og datakvalitetsarbeid.

Appen lar deg velge SQL-filer fra `SQL/`, skrive egne sporringer, kjoere ett eller flere SQL-resultater, eksportere data til CSV/Excel og lagre datakvalitetsanalyse i `Resultater/` uten aa versjonere selve uttrekksdataene.

## Hovedfunksjoner

- Viser SQL-filer i en sokbar trestruktur i sidepanelet.
- Kan markere SQL-filer som utdaterte direkte fra UI-et.
- Kan kjoere SQL fra fil eller fra fritekstfelt.
- Kan knytte hver SQL til konkret database med `-- DATABASE: ...`.
- Stotter flere SQL-resultater i samme fil med separator-kommentarer.
- Kan kjoere alle SQL-filer samlet og lage samlet kolonnestatus.
- Viser radtall, kolonnetall, resultatdata og datakvalitet per kolonne.
- Eksporterer resultater til CSV og Excel.
- Lager copy/paste-vennlige tekster for ChatGPT eller dokumentasjon.
- Kan lagre metadata, kolonnelister og datakvalitetsmaal i `Resultater/`.
- Har innebygde git-operasjoner for SQL-filer og analysearkiv.

## Katalogstruktur

```text
Migration/
+-- DBMigration.py            # Streamlit-appen
+-- SQL/                       # SQL-filer som vises i appen
|   +-- _egne_sporringer/      # SQL lagret fra "Skriv egen SQL"
|   +-- avtaler/
|   +-- masterdata/
|   +-- ...
+-- Resultater/                # Analysearkiv, ikke selve resultatdata
```

`SQL/_egne_sporringer/` og `Resultater/` opprettes automatisk hvis de mangler.

## Forutsetninger

Appen forventer at den ligger i et repo hvor en overordnet mappe inneholder `DivClasses/`. Ved oppstart leter appen oppover fra `DBMigration.py` etter denne mappen og importerer:

```python
from DivClasses.SQLServerBase import SqlServerBaseCls
```

Du maa derfor kjoere appen fra et miljoe som har tilgang til repoet, `DivClasses`, SQL Server-tilkobling og nodvendige Python-pakker.

Typiske Python-avhengigheter:

```text
streamlit
pandas
plotly
openpyxl
st-ant-tree
```

Tree-select-komponenten installeres med:

```powershell
python -m pip install st-ant-tree
```

## Starte appen

Fra denne mappen:

```powershell
streamlit run DBMigration.py
```

Appen bruker bred layout og vises med tittelen `DBMigration`.

## Databaser

I sidepanelet finnes valget `Standard database`. Dette brukes bare som fallback naar en SQL ikke selv angir database.

Stottede databaseverdier:

- `PFTSQL`: SQL Server staging via `SqlServerBaseCls(prefix="PFTSQL_")`
- `LYDIA`: SQL Server Lydia via `SqlServerBaseCls(prefix="LYDIA_")`
- `IFS_ORACLE`: Oracle IFS via `OracleBaseCls(owner_default="IFSAPP")`

Legg database i SQL-filen slik:

```sql
-- DATABASE: IFS_ORACLE
```

Appen kjenner ogsaa igjen aliaser som `IFS`, `IFSAPP`, `ORACLE`, `STAGING`, `PFTSQL_` og `LYDIA_`.

For SQL Server haandteres tilkobling av `SqlServerBaseCls`. For IFS/Oracle haandteres tilkobling av `OracleBaseCls`, som forventer Oracle-konfig i env/secrets:

```text
ORACLE_DSN
ORACLE_HOST
ORACLE_PORT
ORACLE_SERVICE_NAME
ORACLE_USER
ORACLE_PASSWORD
```

Det holder aa sette enten `ORACLE_DSN` eller kombinasjonen `ORACLE_HOST`, `ORACLE_PORT` og `ORACLE_SERVICE_NAME`, i tillegg til bruker/passord.

## Bruke SQL-filer

Legg `.sql`-filer under `SQL/`. Appen finner filer rekursivt og viser dem i en trestruktur i venstre sidepanel.

Trevelgeren er bygget slik:

```text
mappe
+-- undermappe
|   +-- sporring.sql
|       +-- database
```

Det nederste nivaaet er databasen som SQL-en er knyttet til. Naar du velger database-bladet, velges SQL-filen i appen.

SQL-filer sorteres etter dato. Dato hentes forst fra en SQL-kommentar:

```sql
-- DATO: 2026-06-11
```

Hvis ingen dato-kommentar finnes, brukes filens sist endret-dato.

Database hentes fra siste database-kommentar i SQL-en:

```sql
-- DATABASE: PFTSQL
```

Hvis kommentaren mangler, brukes standarddatabasen valgt i sidepanelet. I visningen for valgt SQL-fil kan databasevalget lagres tilbake til filen.

### Markere SQL som utdatert

SQL kan markeres som utdatert i UI-et. Da lagres en kommentar i filen, for eksempel:

```sql
-- STATUS: UTDATERT: Erstattet av masterdata/11_leverandorer.sql
```

Appen kjenner ogsaa igjen:

```sql
-- UTDATERT: Forklaring
-- OBSOLETE: Explanation
```

Utdaterte filer vises tydelig i sidepanelet og i hovedvisningen.

## Flere SQL-resultater i samme fil

Appen kan splitte en SQL-fil i flere navngitte sporringer. Bruk separatorer paa egen linje:

```sql
-- DATABASE: PFTSQL

-- === SQL: Leverandorer ===
SELECT ...

-- DATABASE: IFS_ORACLE
-- === SQL: Lokasjoner ===
SELECT ...
```

Hver blokk kjoeres som eget resultat og vises i egen fane. Hvis en blokk har egen `-- DATABASE:`-kommentar, overstyrer den filens database.

### Felles SQL-prefix

Hvis flere sporringer trenger samme CTE eller felles innledning, kan du bruke `SQL_BASE` eller `SQL_PREFIX`:

```sql
-- === SQL_BASE: Felles CTE ===
WITH aktive_avtaler AS (
    SELECT ...
)

-- === SQL: Oversikt ===
SELECT *
FROM aktive_avtaler;
```

Prefix-blokken legges foran etterfolgende `SQL`-blokker. Bruk `SQL_RESET` for aa stoppe gjenbruk av prefix:

```sql
-- === SQL_RESET ===
```

## Skrive og lagre egen SQL

Velg `Skriv egen SQL` i appen for aa skrive en sporring direkte. Ved lagring skrives filen til:

```text
SQL/_egne_sporringer/
```

Appen kan samtidig committe SQL-filen til git, hvis valget `Commit SQL til git ved lagring` er aktivert.

## Kjoere SQL

Knappen `Kjor SQL` kjoerer valgt SQL-fil eller SQL fra tekstfeltet.

Knappen `Kjor alle SQL-filer` kjoerer alle `.sql`-filer under `SQL/` og lager samlet kolonnestatus. Dette er nyttig naar man vil sammenligne helheten i migreringsgrunnlaget.

For hvert resultat viser appen:

- antall rader
- antall kolonner
- kildeprefix
- graf for utfylte og manglende verdier per kolonne
- resultatdata
- detaljert datakvalitet per kolonne
- SQL-en som ble kjoert
- nedlasting som CSV og Excel

## Resultatanalyse

Etter en kjoering kan du lagre analysearkiv under `Resultater/`.

Analysearkivet lagrer metadata og kvalitetstall, ikke de fulle SQL-resultatene. Hver kjoering faar en egen mappe, for eksempel:

```text
Resultater/alle_sql_filer_20260611_143000/
+-- 01_navn_datakvalitet.csv
+-- 01_navn_kolonner.csv
+-- manifest.json
+-- endringer_mot_forrige.md
```

`manifest.json` inneholder blant annet:

- tidspunkt for kjoering
- standarddatabase
- database per SQL-resultat
- git-commit for repoet for arkivering
- kildefil
- SQL-hash
- radtall
- kolonnenavn
- datakvalitet per kolonne

`endringer_mot_forrige.md` sammenligner med forrige lagrede analyse for samme base-navn og viser blant annet:

- nye eller fjernede SQL-resultater
- nye eller fjernede kolonner
- radtallsendringer
- datakvalitetsendringer paa minst 20 prosentpoeng

## Git-stotte i appen

Appen kan:

- vise git-historikk for valgt SQL-fil
- vise lokale endringer for valgt SQL-fil
- committe valgt SQL-fil
- committe lagret egen SQL
- committe analysearkiv fra `Resultater/`

Git-operasjonene kjoeres fra appmappen.

## Tips for SQL-filer

- Gi SQL-filer tydelige navn og legg dem i relevant undermappe.
- Bruk `-- DATO: YYYY-MM-DD` naar datoen skal styres manuelt.
- Bruk `-- STATUS: UTDATERT: ...` i stedet for aa slette gamle sporringer som fortsatt kan vaere nyttige historisk.
- Bruk `SQL_BASE` for felles CTE-er naar flere resultater bygger paa samme grunnlag.
- Lagre resultatanalyse naar SQL-endringer skal dokumenteres over tid.
