# SOLUTION.md — Recurring LEV bleed-through, zone 002

Working document for the /loop investigation. Updated each iteration.

## VERDICT SO FAR

Zone 002's LEV (PEFY ducted unit on PUMY-P200YKM3) meters normally but does
not seal when commanded closed. Confirmed live in fan-only mode: coil pipes
~20 K below room, pinned at saturation, while LEV commanded to minimum.
History: unit body replaced once (fault returned), stator coil replaced once
(no change — coil swap cannot fix a seat that will not seal). Leading root-cause
candidates, in current order: (1) debris — brazing oxide seeded by the repairs
themselves or branch reservoir; (2) moisture — ice-plug at the seat (fits the
ETm/evap-temperature dependence: leak ~99% visible when evap < ~2.5 °C, ~15%
when evap ~9 °C) plus POE sludge; (3) seat wire-drawing erosion from
closed-under-dP duty; (4) board/driver fault (down-weighted: valve meters and
strokes normally in operation, but not excluded until the forced-close test).
The importer's external-LEV proposal is a sound repair *implementation* if the
forced-close test confirms a mechanical seat fault, and only with the
contamination package (strainers, bi-flow drier with desiccant, nitrogen
brazing, vacuum decay test, internal LEV locked full open).

## System facts (do not re-derive)

- ODU: PUMY-P200YKM3, R410A, 22.4 kW, factory charge 7.3 kg. MN Converter logs
  mis-label it "PUMY-P36/48NKMU1(-BS)"; converter clock has been wrong by a
  year — never trust log timestamps without operator confirmation.
- Zone 002: PEFY ducted City Multi unit, M-NET address 2. EXACT MODEL NUMBER
  UNKNOWN — blocks the part-number research (item a).
- Thermistors (PUMY): TH2=HIC pipe, TH3=outdoor liquid, TH4=discharge,
  TH6=suction, TH7=ambient, TH8=heatsink. Pressures 63HS/63LS in psi gauge.
- Baselines (analyzed captures):
  - ETm-6 log (OM_20250808_184734.CSV, actually Aug 2026): 002 leak-through
    99% of off-time, median depression 17.1 K, pipes at evap 55%; OU suction
    superheat 2.8 K during deep leak vs 6.2 K otherwise; HIC subcool 13.4 K
    (meets 10 K target — charge OK at this operating point); starvation
    episodes 177; compressor at min speed 68%.
  - ETm-12 log (OM_20260729_191459.CSV, Jul 2026): 002 leak visible 15%
    (night/cold-evap windows); HIC subcool 3.0 K vs 10 K target (88%
    undercharge signature — operating-point dependent, i.e. marginal charge);
    gurgling at zone 006 during this period (flash gas at its feeding valve);
    starvation episodes 39; min speed 74%.
  - Zone 006 is NOT bleeding (shallow ~6 K plateau ≈ 2x design-bleed baseline,
    never tracks saturation) — importer scope is one valve: zone 002.
- Live fan-only test (MN tool screenshot, 22:07): 002 TH2=3.8 °C vs room
  23.5 °C at LEV=60, sat ~0.3 °C, zone SH 15 K — leak confirmed flowing.

## Open items checklist

- [x] (a) RESOLVED AS FAR AS REMOTELY POSSIBLE (iter 2): unit identified as
      PEFY-P25VMX-E(1) ("ceiling concealed compact depth", family
      PEFY-P15..63VMX(L)-E, 1-phase 220-240 V). The LEV is internal, with
      strainers, per the family refrigerant diagrams, and PEFY service manuals
      document a "how to exchange the linear expansion valve" procedure — the
      valve IS an orderable service part. The exact part number lives in the
      PEFY-P VMX-E parts catalog (OCB-series document), which the manufacturer
      sites serve but are egress-blocked here; the importer (official channel)
      has it directly. ASK THE IMPORTER: "Quote the LEV assembly part number
      from the PEFY-P25VMX-E parts catalog, and confirm whether the external
      valve you propose is that OEM part relocated or a PKFY-style external
      LEV box." Standard P25-class pipe sizes for the strainer/drier spec:
      liquid 6.35 mm (1/4"), gas 12.7 mm (1/2") — verify on the datasheet.
      Sources: https://www.mitsubishi-electric.co.nz/commercial/c/11195/pefy-p-vmx-e ,
      https://www.mitsubishielectric.com.au/wp-content/uploads/2024/05/City-Multi-Indoor-PEFY-P-VMXL-E1-Specifications.pdf ,
      https://www.manualslib.com/manual/1580597/Mitsubishi-Electric-Pefy-Series.html
- [x] (b) RESOLVED (iter 1): externally mounted indoor-unit LEVs are factory
      precedent within City Multi. Small wall units (PKFY-P VLM / PKFY-M-NLMU
      family) ship with the LEV in a separate "External LEV Box" outside the
      chassis, wired back to the unit board — same architecture the importer
      proposes for zone 002. Additionally, LEV bleed into shut-down indoor
      coils is a recognized City Multi failure mode, and Mitsubishi's
      pre-commissioning manual mandates nitrogen brazing specifically because
      pipe oxidation blocks LEVs. No PEFY-specific retrofit bulletin found —
      ask the importer which part they use (likely the PKFY-style external LEV
      box or the OEM PEFY LEV assembly relocated). Sources:
      https://www.mitsubishicomfort.com/products/cm-series/pkfy-m-nlmu ,
      https://planetaklimata.com.ua/instr/Mitsubishi_Electric/Mitsubishi_Electric_PKFY-P_VLM-E_VKM-E_Data_Book_Eng.pdf ,
      https://americanhvac.nyc/how-to-fix-mitsubishi-city-multi-vrf-heating-in-cool-mode-or-when-turned-off/ ,
      http://www.bdt.co.nz/download/CityMulti_PreCommissioningManual_v2.1_YLM_201509.pdf
- [~] (c) USER REPORTS UNAVAILABLE: forced-close / heat-gun tests cannot be
      run before the repair. Consequence: the mechanical-vs-board question
      stays formally open, and ROOT-CAUSE ASSIGNMENT MOVES TO THE VALVE
      AUTOPSY at repair time (step 8 of the package). Mitigation for the board
      risk baked into the package: after fitting the external LEV, verify
      seal with a capture BEFORE closing up — if the new valve also fails to
      seal on the same driver, the fault is control-side and the importer is
      on site to see it.
- [~] (d) USER REPORTS UNAVAILABLE: no new captures expected before the
      repair. Post-repair capture remains the acceptance gate (item f).
- [x] (e) RESOLVED (iter 2): final repair package spec below, updated with
      pipe sizes; only the part-number line awaits the importer's quote.
- [ ] (f) Post-repair verification capture confirming 002 seals
      (pipes at room while off; OU superheat ~6 K steady).

## Repair package spec (FINAL — one line pending importer's part quote)

Pre-repair tests (forced-close, heat-gun) reported unavailable; root cause is
assigned by the autopsy (step 8) and the board-fault risk is covered by the
on-site verification (step 9a).

1. [unavailable — skipped] Forced-close test via Drive Operation.
2. [unavailable — skipped] Heat-gun ice test.
3. External LEV for PEFY-P25VMX-E: OEM part per the importer's quote from the
   VMX-E parts catalog (or PKFY-style external LEV box — importer to state
   which), mounted in accessible branch piping (liquid 6.35 mm / gas 12.7 mm),
   acoustically considerate location.
4. Internal LEV driven FULL OPEN and verified before its connector moves to
   the external valve (else series restriction starves the zone).
5. 100-mesh strainers both sides of the new LEV (heat-pump flow reversal).
6. Bi-flow liquid-line filter-drier WITH desiccant (captures moisture, not
   just particles).
7. Nitrogen-purged brazing; deep vacuum with decay test.
8. Autopsy the removed/bypassed valve: debris on seat vs polished
   wire-drawing groove vs clean seat — assigns final root cause.
9. Post-repair MN capture at the low-ETm setting (max leak visibility):
   002 off, pipes at room temp, OU superheat ~6 K steady → sealed.
   9a. Verify BEFORE the tech leaves site: if the NEW external valve also
   fails to seal on the same board driver, the fault is control-side
   (board/harness) — the one candidate the skipped tests left open — and it
   is diagnosed on the spot instead of in two years.
10. After confirmation, retest at higher ETm for the efficiency setting and
    confirm no gurgling at 006 (subcool should improve with the leak sealed).

## Iteration log

- Iter 1: created this file; checked uploads (no new captures — only the two
  known CSVs and the processed live-test screenshot). Resolved item (b):
  external LEV mounting has factory precedent (PKFY external LEV box), and the
  bleed-into-off-coil fault is a documented City Multi failure mode. Importer's
  proposal upgraded from "plausible regional practice" to "consistent with
  factory architecture". Next iteration priorities: (a) needs the PEFY model
  number from the user (still BLOCKING); (c) awaits forced-close / heat-gun
  test execution; (d) awaits new captures.
- Iter 2: user supplied model = PEFY-P25VMX-E(1) and reported pre-repair tests
  and new captures unavailable. Resolved (a) as far as remotely possible
  (family identified; LEV is a documented service part; exact number must come
  from the importer's VMX-E parts catalog — manufacturer sites egress-blocked
  here). Marked (c)/(d) unavailable; root-cause assignment moved to the valve
  autopsy; added on-site verification step 9a to cover the board-fault branch.
  Finalized the repair package (e). REMAINING: importer's part quote, the
  repair itself, autopsy result, and the post-repair acceptance capture (f).
