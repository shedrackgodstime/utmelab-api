#!/usr/bin/env python3
"""Physics tagging, 2026-10-14: every untagged physics row gets a subtopic.

All 105 physics rows shipped with `subtopic_id: null`, so they served fine but
sat in no drill path and counted as unattributed in readiness (D68). This
assigns each row the syllabus subtopic its question actually tests.

Rules, in the order they were applied:
* the slug must exist in `data/subtopics.json` and belong to a physics topic —
  the script refuses to write otherwise, so nothing is forced into a near miss;
* a row already tagged is left alone (idempotent: re-running writes nothing);
* a row with no honest home stays null, as 74094/74200 did. The list of those
  is printed at the end so the gap stays visible instead of hidden.

Run: `python3 tools/physics_tag_2025_10_14.py [--dry-run]`
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

BANK = Path("data/questions.json")
SUBS = Path("data/subtopics.json")
TOPICS = Path("data/topics.json")

SHM = "simple-harmonic-motion-shm-period-frequency-amplitude-veloci"
LIN = "linear-motion-speed-velocity-acceleration-equations-of-unifo"
NLM = "newton-s-laws-of-motion-inertia-mass-impulse-momentum-and-co"

# id suffix (the source page number, or the authored row's tail) -> subtopic
TAGS = {
    # simple harmonic motion
    "m_001": SHM,
    "m_002": SHM,
    "74574": SHM,
    "74658": LIN,
    # light
    "74347": "propagation-of-light-speed-frequency-and-wavelength",
    "74563": "propagation-of-light-speed-frequency-and-wavelength",
    "74359": "dispersion-of-white-light-by-a-triangular-prism",
    "74481": "electromagnetic-spectrum-sources-detection-and-uses-of-the-v",
    "76117": "electromagnetic-spectrum-sources-detection-and-uses-of-the-v",
    "74541": "linear-magnification",
    "74564": "laws-of-reflection-and-their-applications",
    "74568": "formation-of-shadows-and-eclipses",
    "74547": "the-pin-hole-camera",
    "74495": "nuclear-energy-solar-energy-solar-collectors-and-solar-panel",
    "74356": "principles-of-the-microscope-telescope-projector-camera-and",
    "74554": "sight-defects-and-their-corrections",
    "74567": "near-and-far-points",
    "74348": "power-of-a-lens-angular-magnification",
    # refraction
    "74371": "critical-angle-and-total-internal-reflection",
    "74486": "real-and-apparent-depth-lateral-displacement",
    "74493": "laws-of-refraction-and-refractive-index",
    "74660": "laws-of-refraction-and-refractive-index",
    # sound and waves
    "74353": "production-and-propagation-wave-motion-vibrating-systems-as",
    "74491": "superposition-of-waves-interference-beats-and-doppler-effect",
    "74661": "classification-mechanical-and-electromagnetic-longitudinal-a",
    "74562": "relationship-between-frequency-wavelength-and-wave-velocity",
    "74382": "disadvantages-of-echoes-and-reverberation",
    "74494": "speed-of-sound-in-solids-liquids-and-air",
    "74545": "speed-of-sound-in-solids-liquids-and-air",
    # mechanics
    "74357": "relative-motion-and-causes-of-motion",
    "74349": "resolution-of-vectors-into-two-perpendicular-directions-incl",
    "74360": "coefficient-of-limiting-friction-and-its-determination",
    "74476": "static-and-dynamic-friction",
    "75421": "static-and-dynamic-friction",
    "74571": "qualitative-treatment-of-viscosity-and-terminal-velocity",
    "74363": "newton-s-law-of-universal-gravitation",
    "74573": "newton-s-law-of-universal-gravitation",
    "74570": "acceleration-due-to-gravity-g-gm-r-and-its-variation-on-the",
    "74552": NLM,
    "74561": NLM,
    "74377": "principle-of-moments-moment-of-a-force-couple-and-torque-app",
    "74492": "principle-of-moments-moment-of-a-force-couple-and-torque-app",
    "74542": "resolution-and-composition-of-forces-resultant-and-equilibra",
    "74380": "mechanical-advantage-velocity-ratio-and-efficiency",
    "74366": "definitions-of-work-energy-and-power-and-their-forms",
    "74378": "definitions-of-work-energy-and-power-and-their-forms",
    "74550": "conservation-of-energy-and-qualitative-transformations-betwe",
    # matter and its properties
    "74488": "dimensions-definition-and-examples",
    "74560": "fundamental-physical-quantities",
    "74352": "kinetic-theory-assumptions-and-use-to-explain-gas-pressure-b",
    "74386": "molecular-theory-brownian-motion-diffusion-surface-tension-c",
    "74551": "molecular-theory-brownian-motion-diffusion-surface-tension-c",
    "74478": "definition-of-relative-density",
    "74381": "archimedes-principle-and-the-law-of-flotation-and-their-appl",
    "74383": "upthrust-on-bodies-immersed-in-a-liquid",
    "74482": "hooke-s-law-and-young-s-modulus",
    "74686": "work-done-per-unit-volume-in-springs-and-elastic-strings",
    # heat
    "74350": "anomalous-expansion-of-water",
    "74364": "solids-linear-area-and-volume-expansivity-definition-and-det",
    "74553": "solids-linear-area-and-volume-expansivity-definition-and-det",
    "74355": "thermometric-properties",
    "74546": "types-of-thermometer-and-conversion-between-scales",
    "74432": "ideal-gas-equation-pv-nrt",
    "74365": "general-gas-equation-pv-t-constant",
    "74372": "charles-law-isobaric-process",
    "74572": "charles-law-isobaric-process",
    "74367": "determination-by-the-method-of-mixtures-and-electrical-metho",
    "74376": "determination-by-the-method-of-mixtures-and-electrical-metho",
    "74388": "heat-capacity-and-specific-heat-capacity-of-solids-and-liqui",
    "74480": "heat-capacity-and-specific-heat-capacity-of-solids-and-liqui",
    "74544": "heat-capacity-and-specific-heat-capacity-of-solids-and-liqui",
    "74369": "latent-heat-specific-latent-heats-of-fusion-and-vaporisation",
    "74483": "latent-heat-specific-latent-heats-of-fusion-and-vaporisation",
    "74368": "conductivities-of-common-materials",
    "74384": "temperature-gradient-thermal-conductivity-and-heat-flux",
    # pressure
    "74362": "transmission-of-pressure-in-liquids-pascal-s-principle-and-a",
    "74490": "pressure-in-liquids-relationship-between-pressure-depth-and",
    # electricity and magnetism
    "74354": "electromotive-force-emf-potential-difference-p-d-current-int",
    "74484": "the-metre-bridge",
    "74387": "faraday-s-laws-of-electrolysis-and-applications-electroplati",
    "74479": "faraday-s-laws-of-electrolysis-and-applications-electroplati",
    "74358": "the-magnetic-field-fields-due-to-a-permanent-magnet-current",
    "74569": "charging-a-body-by-friction-contact-and-induction",
    "74549": "coulomb-s-inverse-square-law-electric-field-and-potential",
    "74543": "the-parallel-plate-capacitor-and-capacitance",
    "74565": "capacitors-in-series-and-in-parallel",
    "74558": "daniell-cell-and-leclanch-cell-wet-and-dry",
    "74566": "arrangement-and-efficiency-of-cells",
    "74659": "arrangement-and-efficiency-of-cells",
    "74556": "natural-and-artificial-magnets-magnetic-properties-of-soft-i",
    "74662": "methods-of-making-and-demagnetising-magnets",
    "74477": "the-magnetic-field-fields-due-to-a-permanent-magnet-current",
    "74373": "the-d-c-motor-electromagnets-the-carbon-microphone",
    "74487": "force-on-a-moving-charge-in-a-magnetic-field",
    "74559": "faraday-s-laws-of-electromagnetic-induction-and-factors-affe",
    "74379": "inductance-explanation-unit-and-energy-stored-in-an-inductor",
    "74485": "explanation-of-a-c-current-and-voltage-peak-and-r-m-s-values",
    "74489": "resistance-and-impedance-effective-voltage-in-r-l-c-circuits",
    "74361": "concepts-of-electrical-energy-and-power",
    "74679": "concepts-of-electrical-energy-and-power",
    "74555": "commercial-units-of-energy-and-power",
    "74370": "intrinsic-and-extrinsic-semiconductors-n-type-and-p-type-sem",
    # modern physics
    "74374": "radioactivity-properties-and-applications-of-alpha-beta-and",
    "74557": "radioactivity-properties-and-applications-of-alpha-beta-and",
    "74548": "wave-particle-paradox-duality-of-matter-electron-diffraction",
}


# Rows whose id tail does not identify them (authored rows share the 001/002
# pattern across subjects), keyed by full id instead.
ID_TAGS = {
    "q_authored_physics_shm_001": SHM,
    "q_authored_physics_shm_002": SHM,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    rows = json.loads(BANK.read_text())
    subtopics = {s["slug"]: s for s in json.loads(SUBS.read_text())}
    physics_topics = {
        t["slug"] for t in json.loads(TOPICS.read_text()) if t["subject"] == "physics"
    }

    problems = []
    for slug in set(TAGS.values()) | set(ID_TAGS.values()):
        if slug not in subtopics:
            problems.append(f"{slug}: not in data/subtopics.json")
        elif subtopics[slug]["topic"] not in physics_topics:
            problems.append(f"{slug}: belongs to {subtopics[slug]['topic']}, not physics")
    if problems:
        print("ABORT: bad slugs")
        for p in problems:
            print(f"  {p}")
        return 1

    tagged, skipped, unmatched = 0, [], []
    for row in rows:
        if row["subject"] != "physics" or row.get("subtopic_id"):
            continue
        slug = ID_TAGS.get(row["id"]) or TAGS.get(row["id"].rsplit("_", 1)[-1])
        if slug is None:
            unmatched.append(row["id"])
            continue
        if args.dry_run:
            print(f"  {row['id']} -> {slug}")
        row["subtopic_id"] = slug
        tagged += 1

    if unmatched:
        print(f"\nno subtopic assigned ({len(unmatched)}):")
        for qid in unmatched:
            text = next(r for r in rows if r["id"] == qid)["text"]
            print(f"  {qid}: {(text['text'] if isinstance(text, dict) else text)[:80]}")

    print(f"\ntagged {tagged}, left null {len(unmatched)}")
    spread = Counter(TAGS.values())
    print(f"{len(spread)} distinct subtopics used; busiest:")
    for slug, n in spread.most_common(6):
        print(f"  {n:3}  {subtopics[slug]['name'][:64]}")

    if not args.dry_run:
        BANK.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n")
        print("data/questions.json written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())