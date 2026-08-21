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

- [ ] (a) OEM LEV service part number for the PEFY model.
      BLOCKED: need exact PEFY model number from the nameplate.
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
- [ ] (c) Field-test plan discriminating debris vs ice vs erosion vs board:
      drafted (forced-close via Drive Operation; heat-gun test during active
      leak; valve autopsy on removal) — needs execution results.
- [ ] (d) Analyze any NEW MN captures. Nothing new this iteration (only the
      two known CSVs + the already-processed screenshot in uploads).
- [ ] (e) Final repair package spec — drafted below, pending (a) and (b).
- [ ] (f) Post-repair verification capture confirming 002 seals
      (pipes at room while off; OU superheat ~6 K steady).

## Repair package spec (draft, pending part numbers)

1. Forced-close test FIRST (MN tool, Drive Operation → LEV 002 to 0 pulses,
   watch TH2/TH3 15-20 min, fan-only): seals → board/positioning fault, do NOT
   fit external LEV off the same driver without resolving; stays cold →
   mechanical, proceed.
2. Heat-gun test during active leak at low-ETm setting: leak stops when valve
   body warmed → moisture ice; fix is drying (drier + deep vacuum), valve may
   be fine.
3. External LEV: OEM part matched to the PEFY's internal LEV drive spec
   (pending item a), mounted in accessible branch piping, acoustically
   considerate location.
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
