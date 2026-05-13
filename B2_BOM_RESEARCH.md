# B2 — BOM Endpoint Research

## Summary

The Priority OData entity that holds the BOM for kits is **`PARTARCONE`** (Priority's classic "Part Tree" form, `PARTARC` aka *מבנה מוצר/Bill-of-Materials*). It exists in this tenant's metadata, has exactly the parent→child + quantity columns we need (`PARTNAME` → `SONNAME` with `SONQUANT`/`FATQUANT`/`COEF`), and would have answered the question — **except our API user is blocked from reading it.** Every call returns HTTP 400 with `"לא ניתן להפעיל API למסך זה"` ("API not enabled for this screen"). Two POS-side flat alternatives exist (`POS_KITCOMPPARTSFLAT`, `POS_KITITEMS`) but they are equally blocked (400) or not exposed as entity sets (404). Without an OData permission grant from Priority IT for `PARTARCONE` (or, as a fallback, exposing a Tammuz custom OData view that joins the BOM), B2 cannot proceed via OData. A workaround exists for this specific dataset: the SKU naming convention `<kit>-00` → `<kit>-0S/0M/0L` is consistent in the `TOPP_DEGEM` family, and `LOGPART.TOPP_SET = "Y"` flags kits — so the BOM can be **derived** from a pattern match on PARTNAME until IT grants the proper screen.

## Detailed findings

### Setup

- Base URL: `https://priority.newcinema.co.il/odata/Priority/tabula.ini/ncinema`
- Auth: `PRIORITY_AUTH_HEADER` loaded via `db_config`'s dotenv
- Total entity sets exposed in the service document: **2 221**
- The `$metadata` XML is ~13 MB and contains **4 739 EntityType definitions** — much larger than the entity-set list, meaning many types are defined but not bound to a queryable URL.

### HTTP-status semantics on this server

Three distinct codes mean different things:

| Code | Meaning |
|------|---------|
| 200 | Endpoint exists *and* our credential is allowed to read it |
| 400 | Endpoint exists in `$metadata` and is bound as an entity set, but the credential has no Form API permission. Response body: `{"error":{"code":"400","message":"לא ניתן להפעיל API למסך זה",...}}` |
| 404 | Entity set is not bound at the service root at all |
| 500 | Server error (`$expand=*` triggered one of these) |

This distinction is decisive: the BOM tables we want are 400, not 404. They are present, just not authorised for our user.

### Hypothesis sweep

| Endpoint | HTTP | Notes |
|---|---|---|
| `PARTREC` | 404 | Not in this tenant |
| `PARTARC` | 404 | Not the form name used here |
| `PARTARCONE` | **400** | **Exists, blocked.** This is the BOM form. |
| `MAKEAC` | 404 | — |
| `MAKEPARTCOST` | 400 | Cost-roll-up, not raw BOM |
| `PART` | 400 | Master parts file, blocked |
| `DOCDOC` | 404 | — |
| `LOGPART` | 200 | Logical parts view — see below |
| `LOGPARTREC` | 404 | — |
| `LOGFILE` | 200 | Transactions; **does not** explode kits into children when issued |
| `POS_KITS` | 400 | Blocked |
| `POS_KITCODES` | 400 | Blocked |
| `POS_KITCOMPPARTSFLAT` | **400** | **Exists, blocked.** Flat KITCODE→PARTNAME table — POS-side equivalent of PARTARCONE |
| `POS_KITCOMPPARTS` | 404 | (Type exists but no entity set) |
| `POS_KITITEMS` | 404 | (Type exists but no entity set) |
| `POS_SETPROPCOMPONENT` | 400 | Blocked |
| `POS_COMPONENTS` | 400 | Blocked |
| `POS_COMPONENTPACKAGE` | 400 | Blocked |
| `POS_FABRICCOMPONENTS` | 400 | Fabric-content table; not kit BOM |
| `POS_KITPRINTSETTING` | 400 | Print prefs, not data |
| `POS_KITSUSING` | 400 | Blocked |
| `RAWPARTARC` | 400 | Raw-material variant of PARTARC; blocked |
| `PARTPACKONE` | 400 | Pack-size for one PARTNAME, not BOM |
| `PACK` | 400 | Blocked |
| `TOPP_TAPUZPACK_FLAT` | 200 | Tapuz courier packages, unrelated |
| `BOM`, `BOMITEMS`, `KIT`, `KITS`, `PARTKIT`, `PARTKITS`, `PARTBOM`, `PARTSET`, `SET`, `SETS`, `PARTCHILD`, `PARTITEMS`, `COMPOSITION`, `STRUCT`, `PARTSTRUCT`, `LOGPARTREC` | 404 | None of these are bound |

### What `LOGPART` *does* tell us

`LOGPART` is queryable (HTTP 200) and holds **179** fields per part. It has no NavigationProperties (zero `<NavigationProperty>` tags in the `LOGPART` EntityType in `$metadata`), so we **cannot** `$expand` into a kit sub-form from here.

Two LOGPART columns confirm that kit-flagging exists at the part-master level and that our test SKU is correctly flagged:

| PARTNAME | TOPP_SET | TOPP_COLECTIONPART | TOPP_DEGEM | PARTDES |
|---|---|---|---|---|
| `DISPP03-001-00` | **Y** | Y | DISPP03-001 | סט מזוודות קשיחות 20' / 25' / 29' מורחבות Travel Club |
| `DISPP03-001-0S` | null | Y | (same family) | מזוודה קשיחה 20' מורחבת Travel Club BLK S |

So `TOPP_SET = "Y"` reliably marks a SKU as "this is a kit", and `TOPP_DEGEM` groups the kit and its sizes under the same model code. But neither of these gives us the parent→child mapping with quantities — they only tell us "this is a kit" and "this part belongs to model X".

### What `LOGFILE` *does not* tell us

`LOGFILE` (transaction log) returns rows for the kit SKU directly — e.g. `GR24000329` received 100 of `DISPP03-001-00` with `TOPP_DEGEM = DISPP03-001`. Priority does **not** auto-explode the kit into three child-line rows on this server. So we **cannot** reconstruct the BOM from transaction history either.

### `PARTBAL` ground truth at branch 800 (today)

| WARHSNAME | PARTNAME | TBALANCE |
|---|---|---|
| 800 | DISPP03-001-00 | **+7** |
| 800 | DISPP03-001-0S | -20 |
| 800 | DISPP03-001-0M | -6 |
| 800 | DISPP03-001-0L | -32 |

Total of children-after-mistakes is far more negative than the kit count is positive; this is exactly the scenario the user described.

## Schema diagram for the winning endpoint (`PARTARCONE`)

This is the entity we *would* use if the permission grant were in place. Pulled directly from `$metadata`:

```
PARTARCONE   (Hebrew form name: עץ מוצר / Part Tree)
├── PARTNAME      string(22)   parent SKU         "מק\"ט אב"        [KEY-ish]
├── REVNUM        ...          parent revision    "מהדורה של מוצר"
├── SONNAME       string(22)   child SKU          "מק\"ט בן"
├── SONREVNAME    ...          child revision     "מהדורה רכיב בן"
├── FATQUANT      decimal      parent quantity    "כמות אב"
├── SONQUANT      decimal      child quantity     "כמות בן"
├── COEF          decimal      coefficient        "מקדם"
├── OP            string(1)    add/sub/fixed      "תוסיף,חסר,קבוע"
├── VARNAME       string       variant            "ואריאנט"
├── SCRAP         decimal(%)   waste percentage   "פחת (%)"
├── ACTNAME       string       parent activity    "פעולה אב"
├── SONACTNAME    string       child activity     "פעולה בן"
├── SETEXPDATE    date         child set-expiry   "תוקף חלק בן"
├── INFOONLY      flag         informational only "ערכי מידע"
├── USERLOGIN     string       updater login
├── UDATE         datetime     last update
├── RVFROMDATE    datetime     revision-from date
├── ACT           int          activity ID
├── PART          int          parent SKU ID
├── SON           int          child SKU ID
└── SONACT        int          child activity ID
```

Read pattern for B2 (once unblocked):

```
GET /PARTARCONE?$filter=PARTNAME eq 'DISPP03-001-00'
                 &$select=PARTNAME,SONNAME,SONQUANT,FATQUANT,COEF,OP
                 &$top=1000
```

Expected rows for our test kit: three rows with `SONNAME` ∈ {`DISPP03-001-0S`, `DISPP03-001-0M`, `DISPP03-001-0L`} and `SONQUANT = 1` each.

The structure **does support nested kits** — `SONNAME` is itself a PARTNAME and could be queried recursively (and PARTARCONE has revision and activity fields that would make the recursion sensitive to active-revision rules). The fields `SETEXPDATE`/`RVFROMDATE` let kits be versioned, but for retail-luggage use the recursion is shallow (kit → size variants, no further nesting).

## Alternate winning endpoint (also blocked): `POS_KITCOMPPARTSFLAT`

POS-side flat view of the same data. If `PARTARCONE` cannot be unblocked but the POS module can, this is the next best target:

```
POS_KITCOMPPARTSFLAT
├── KITCODE        string   kit master code       "קוד מארז/בנדל"
├── KITDES         string   kit description
├── COMPCODE       string   component-group code  "קוד רכיב"
├── COMPDESC       string   component description
├── PARTNAME       string   child SKU             "פריט"
├── PARTDES        string   child description
├── UNITNAME       string   unit
├── MINQUANT       decimal  min quantity
├── MAXQUANT       decimal  max quantity
├── VALIDQUANT     decimal  valid quantity
├── MAXTOTPRICE    decimal  max total price
├── KIT1           int      kit ID
└── (other policy flags: SALEFLAG, COMPUSETYPE, PPCONTRACTFLAG, NOVALID, NOVALID2, MANUAL, LIMITTYPE, GENERAL, COMPCODE1)
```

Note: this table is keyed by `KITCODE`, not `PARTNAME`. If kits are configured in the POS module, `KITCODE` for our test would likely be `DISPP03-001-00` (matching the master SKU), but this needs to be confirmed once the endpoint is unblocked.

## Recommendation for next steps

1. **The blocker is a permission grant, not a code change.** B2 implementation is straightforward (one OData GET + a join in our DB) once Priority IT enables Form API permissions on `PARTARCONE` for the user behind `PRIORITY_AUTH_HEADER`. Recommended ask:
   > "Please enable Form API (OData read) permission for our integration user on screens `PARTARCONE` (עץ מוצר) and, if used in your POS configuration, `POS_KITCOMPPARTSFLAT`. Read-only is sufficient."

2. **Fallback while waiting on IT — pattern-match heuristic, not a real BOM.** For this specific catalogue, the kit↔children relationship is encoded in the SKU pattern that the user described and that we verified end-to-end: `<MPARTNAME>-<NN>-00` is a kit, with size variants at `-0S` / `-0M` / `-0L`. We can:
   - Filter `LOGPART` for `TOPP_SET eq 'Y'` to enumerate all kit SKUs.
   - For each, derive expected children by suffix substitution `-00` → `-0S`, `-0M`, `-0L` and verify they exist in `LOGPART`.
   - Use this synthetic BOM (parent + 3 children, qty 1 each) until the real one is available.

   This is fragile and luggage-specific — non-luggage kit SKUs (e.g. accessories) will not match this pattern, and any kit with a different size set will be wrong. Treat it as a temporary stop-gap.

3. **Do not waste cycles trying more endpoints.** The metadata sweep is exhaustive — every BOM-shaped table in this tenant is either a 400 (blocked) or a 404 (not bound), with the single useful exception of `LOGPART`, which doesn't carry parent→child data.

4. **If Tammuz refuses or delays the permission grant**, ask whether they can build a small Tammuz custom flat-view (their convention seems to be `TOPP_*`-prefixed or `RETL_*`-prefixed flat tables — see `TOPP_TAPUZPACK_FLAT`, `RETL_INFPARTSTRUCT`, `POS_KITCOMPPARTSFLAT` for precedent). A view joining `PARTARC` to `PART` and exposing `KITPARTNAME / COMPPARTNAME / QUANT` would unblock B2 without a security-policy debate.

## Files produced for this investigation (not committed)

- `c:\tmp\priority_metadata.xml` — full `$metadata` (13 MB) for offline inspection
- `c:\tmp\priority_entitysets.json` — list of all 2 221 bound entity sets
- `c:\tmp\bom_probe_summary.json` — Phase-1 probe results
- `c:\tmp\bom_probe[1-9].py` — probe scripts
