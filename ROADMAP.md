# Outlook & Next Steps

Where Seabed Sentinel is today: a working proof of concept — physics rules + unsupervised ML,
live and historic modes, vessel enrichment — running on real, sovereign European data. This is
the path to an operational capability. Status: ✅ built · 🟡 partial · ⬜ planned.

---

## 1. Geographic ground truth

**Real cable & pipeline routes** — measure against the true asset, not a placeholder line.
- 🟡 EMODnet WFS import built (`import_cable.py`) — pulls actual routes where EMODnet covers.
- ⬜ Baltic-east (Estlink / Gulf of Finland) is an EMODnet coverage gap → source exact routes from
  operators (Fingrid, Elering, Energinet), KIS-ORCA, and national hydrographic offices; store a
  per-spot cable geometry.
- ⬜ Add pipelines and offshore-wind export cables; weight the corridor by asset criticality.

**Seabed depth / bathymetry** — reject the physically impossible.
- ✅ EMODnet DTM depth-gate built — suppresses anchor-drag alerts where water is too deep to reach
  the seabed.
- ⬜ Depth-aware risk instead of a hard cutoff: model draggable depth from anchor + chain scope per
  vessel size; add a seabed-type layer (mud vs rock changes drag behaviour); fuse multibeam /
  survey data near high-value cables.

## 2. Satellite cross-check — the SAR layer (highest-impact next step)

AIS only sees *cooperative* vessels; the threat vessels switch AIS off. Radar sees them anyway.

- ⬜ **Sentinel-1 SAR** (free, all-weather, day/night): CFAR ship detection on GRD imagery →
  radar contacts; associate contacts with AIS positions; **an unassociated radar contact = a dark
  vessel**. Cross-cue with the AIS go-dark events this system already flags: a vessel that goes
  dark over the cable *and* shows up as an unmatched SAR contact is a high-confidence threat.
- ⬜ Commercial SAR tasking (ICEYE / Capella) for revisit — Sentinel-1's revisit is days, so
  free SAR confirms rather than continuously watches; tasked SAR closes the gap.
- ⬜ Optical (Sentinel-2 / Planet) as a third cross-check; automated tip-and-cue from an AIS
  anomaly to a tasking request.

This is the single biggest capability jump and turns "suspicious AIS behaviour" into
"corroborated across independent sensors".

## 3. Scale the movement model — the big training run

- ✅ Portable behaviour model (Isolation Forest on place-independent motion features) +
  per-spot self-calibrating route model.
- ⬜ Train the behaviour model on a **large multi-spot, multi-month AIS corpus** (all Danish +
  wider Baltic + North Sea days) for a robust baseline that generalises.
- ⬜ **Vessel-type-conditioned normalcy** — cargo, tanker, fishing and passenger have different
  "normal"; score each against its own class.
- ⬜ **Temporal / sequence models** — a trajectory autoencoder or LSTM whose reconstruction error
  flags manoeuvre patterns the rules can't express (loiter-then-drag, repeated passes).
- ⬜ Richer features — acceleration, turn-rate, dwell time in the corridor, interaction geometry
  with the cable.
- ⬜ MLOps — reproducible training pipeline, model registry/versioning, drift monitoring as new
  spots and seasons come online.

## 4. Evaluation & validation

- ⬜ Build a labelled test set: the known incidents (Balticconnector, C-Lion1 / BCS East-West,
  Estlink 2) plus benign look-alikes (fishing, anchoring, cable-maintenance vessels).
- ⬜ Report real metrics — detection rate, **false-positives per day over a multi-day baseline**
  (today's "1 alert/day" is one day, one corridor), and **detection lead time** before the cut.
- ⬜ Incident reconstruction once historical Gulf-of-Finland AIS is secured (commercial history or
  a national data agreement) — the strongest single proof point.

## 5. Operational hardening

- ⬜ Streaming architecture — rolling window → an event store / time-series DB; multiple corridors
  monitored at national scale.
- ⬜ Integration — push alerts into an operator SOC, EU **CISE**, or naval C2 via API / webhooks;
  24/7 operation.
- ⬜ Provenance & audit — every alert reproducible from its exact inputs, for operator trust and
  legal attribution.
- ⬜ Data agreements — a design-partner's operational AIS feed (the key unlock), plus commercial
  AIS history and SAR tasking.

## 6. Additional sensing (longer horizon)

- ⬜ In-cable fibre-optic / distributed acoustic sensing (partner integration) — detects physical
  contact with the cable directly.
- ⬜ Seabed acoustic sensors and inspection drones for confirmation.
- ⬜ Space-based RF geolocation (e.g. Unseenlabs) to catch AIS spoofing — a vessel broadcasting a
  false position is a different, and detectable, anomaly.

---

**Prioritisation.** #2 (SAR cross-check) is the highest-value single step and is achievable on
free Sentinel-1 data; #1 and #3 are enablers already partly in place; #4 and #5 are what make it
operational. The gating factor is not the algorithms — it's **data access**: a design-partner's
operational feed, and one modest paid source (SAR tasking or AIS history) to unlock continuous
coverage and incident-level validation.
