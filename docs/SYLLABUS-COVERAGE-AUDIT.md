# Syllabus coverage audit: Physics, Chemistry, Biology

Date: 2026-11-09 (updated 2026-11-10 after scrape batches 1-8)
Compared against: **production topics** in the Turso DB (`turso://utmelab-api-ultimatekristency.aws-eu-west-1.turso.io`, tables `topics` + `subtopics`), query `subject IN ('physics','chemistry','biology')`.
Concept inventory at audit time: **110 concepts** in `data/concepts/` (57 maths incl. shared physics files, 24 phy, 20 che, 9 bio).
Machine-readable version: `data/concepts/audit-3sci.json` (gitignored staging).

## Post-scrape final coverage (2026-11-10)

**281 concepts, 32,000+ blocks, 1,700+ source figures** after scrape batches 1-8. Every scrapeable topic is now **covered**; the only remaining holes are the no-source topics below. No topic remains "thin" or "gap" where OpenStax offers a module.

| Subject  | Exam | topics | covered | thin | gap | no_source |
|----------|------|--------|---------|------|-----|-----------|
| physics  | JAMB | 39     | 37      | 0    | 0   | 2         |
| physics  | WAEC | 33     | 32      | 0    | 0   | 1         |
| chemistry| JAMB | 18     | 14      | 0    | 0   | 4         |
| chemistry| WAEC | 26     | 24      | 0    | 0   | 2         |
| biology  | JAMB | 23     | 21      | 0    | 0   | 2         |
| biology  | WAEC | 74     | 63      | 0    | 0   | 11        |

**No-source (14 total, unresolved):** physics - Simple Machines, Vapours/hygrometry; chemistry - Air, Water (hardness/town supply), Environmental Pollution, Chemistry and Industry; biology - Local (Nigerian) Biomes, Soil, and 11 applied/practical WAEC topics (dissection, water/fishing/food industry, biotechnology, sampling, drawing practice, biological-work procedure, hygiene detail, fibre optics). These need a peer-reviewed fallback publisher or a decision to hand-author; nothing will be fabricated.

The pre-scrape audit below is retained for history.

## Status legend

- **covered** — every subtopic area is served by ≥1 concept block content.
- **thin** — a concept is mapped, but named subtopics are missing or shallow.
- **gap** — no concept covers the topic. Candidates listed are OpenStax CNXML modules the scraper can source from directly.
- **no_source** — no reliable OpenStax source exists (needs a peer-reviewed fallback or a decision to hand-author); nothing will be fabricated.

Counts 213 topic rows:

| Subject  | Exam | topics | covered | thin | gap | no_source |
|----------|------|--------|---------|------|-----|-----------|
| physics  | JAMB | 39     | 5       | 15   | 17  | 2         |
| physics  | WAEC | 33     | 14      | 14   | 4   | 1         |
| chemistry| JAMB | 18     | 2       | 8    | 4   | 4         |
| chemistry| WAEC | 26     | 4       | 18   | 2   | 2         |
| biology  | JAMB | 23     | 4       | 6    | 11  | 2         |
| biology  | WAEC | 74     | 9       | 26   | 28  | 11        |

WAEC topics are the NECO-style syllabus plus exam-specific extras (Section A/B splits, applied/practical topics). WAEC physics coverage is strongest because the WAEC list folds SHM, nucleus, fields and atoms into fewer, wider topics that existing concepts already serve.

## JAMB Physics (39 topics): 17 gaps, 15 thin, 2 no-source

### Gaps — scrape candidates ready

| Topic | Candidate OpenStax modules |
|---|---|
| Friction | m58304 “Friction” |
| Elasticity | m58342 “Stress, Strain, and Elastic Modulus” |
| Thermal Expansion | m58386 “Thermal Expansion” |
| Quantity of Heat | m58387 “Heat Transfer, Specific Heat, and Calorimetry” |
| Change of State | m58388 “Phase Changes” |
| Structure of Matter and Kinetic Theory | m58391 “Molecular Model of an Ideal Gas”, m58392, m68758 |
| Heat Transfer | m58389 “Mechanisms of Heat Transfer” |
| Reflection of Light | m58509, m58527, m58528 |
| Refraction of Light | m58510, m58511, m58530 |
| Optical Instruments | m58531, m58534, m58532 |
| Dispersion of Light and Colours | m58512 “Dispersion”, m58503 “The Electromagnetic Spectrum” |
| Capacitors | m58448, m58449, m58450 |
| Electric Cells | m58453 “Electromotive Force”, m68825 “Batteries and Fuel Cells” |
| Current Electricity | m58729, m58731, m58732, m58455 “Kirchhoff's Rules” |
| Electrical Energy and Power | m58734 |
| Electromagnetic Induction | m58472 “Faraday's Law”, m58482, m58748, m58494 “Transformers”, m58480 |
| Introductory Electronics | m58600 “Semiconductors and Doping”, m58601 |

### Thin — top-up candidates

| Topic | Mapped | Add |
|---|---|---|
| Motion | phy_position/velocity/acceleration, math_dynamics_forces, phy_first_law, phy_shm | m58291 (Projectile Motion), m58305 (Centripetal Force) |
| Gravitational Field | phy_gravity | m58345, m58346 |
| Work, Energy and Power | phy_work_energy, phy_kinetic_energy | m58310 (Power) |
| Pressure | phy_fluid_pressure | m58353, m58355 |
| Liquids At Rest | phy_fluid_pressure | m58356 (Archimedes' Principle and Buoyancy) |
| Gas Laws | che_gases | m68751, m68759 |
| Waves | phy_waves | m58372, m58373, m58381 |
| Characteristics of Sound Waves | phy_sound | m58377, m58378, m58379, m58380 |
| Light Energy | phy_light_propagation | (pin-hole camera/shadows: no dedicated module) |
| Electrostatics | phy_coulomb | m58412, m58413, m58430, m58778 |
| Magnets and Magnetic Fields | phy_magnetic_fields | m58466 (Earth's field detail) |
| Force on Current-Carrying Conductor | phy_magnetic_force_charge | m58742, m58745 |
| Simple A.C. Circuits | phy_ac_circuits | m58484, m58490 |
| Conduction Through Liquids and Gases | che_solubility | m68827 (Electrolysis) |
| Elementary Modern Physics | phy_hydrogen_atom, phy_nuclear, phy_photoelectric | m58609 (Radioactive Decay), m58610, m58611 |

### No-source (2)

- **Simple Machines** — mechanical advantage/velocity ratio has no OpenStax module. Needs a peer-reviewed fallback publisher or a decision to hand-author.
- **Vapours** — SVP partially inside m58388 Phase Changes; dew/humidity/hygrometry (wet-and-dry-bulb) have no module.

## JAMB Chemistry (18 topics): 4 gaps, 8 thin, 4 no-source

### Gaps

| Topic | Candidates |
|---|---|
| Electrolysis | m68827 “Electrolysis”, m68822 “Galvanic Cells”, m68823 |
| Chemical Equilibrium | m68797, m68799 “Shifting Equilibria: Le Chatelier's Principle” |
| Non-Metals and Their Compounds | m68832 (nonmetals), m68833 (hydrogen), m68837 (oxygen), m68835 (nitrogen), m68836 (phosphorus), m68838 (sulfur), m68839 (halogens), m68840 (noble gases), m68834 (carbonates) |
| Metals and Their Compounds | m68830, m68842, m68843, m68826 “Corrosion” |

### Thin

| Topic | Mapped | Add |
|---|---|---|
| Separation of Mixtures | che_separation_solubility, che_colloids, che_physical_properties | (technique enumeration is thin; no better module) |
| Chemical Combination | che_stoichiometry | m68700 (Formula Mass and the Mole Concept) |
| Kinetic Theory and Gas Laws | che_gases | m68751, m68758, m68754, m68759 |
| Atomic Structure and Bonding | che_atomic_theory, che_periodic, che_bonding | m68734, m68738, m68742, m68851, m68852, m68854 |
| Acids, Bases and Salts | che_acids_bases, che_lewis_acids | m68804, m68809, m68808 |
| Energy Changes | che_energy | m68816 (Spontaneity), m68817 (Entropy) |
| Rates of Reaction | che_kinetics | m68787, m68793 (Collision Theory) |
| Organic Compounds | che_hydrocarbons, che_carbon_groups, che_amines_polymers | m68847 (Alcohols and Ethers) |

### No-source (4)

- **Air** (composition; % O2 measurement)
- **Water** (hardness/softening, town-supply treatment; colligative/osmotic partial via m68783)
- **Environmental Pollution** (partial via conservation-biology modules m66709)
- **Chemistry and Industry** (industry types, biotechnology)

Covered: Solubility, Oxidation and Reduction.

## JAMB Biology (23 topics): 11 gaps, 6 thin, 2 no-source

### Gaps

| Topic | Candidates |
|---|---|
| Evolution Among Organisms (kingdoms) | m66530 (taxonomy), m66545 (prokaryotes), m66554 (protists), m66558 (fungi), m66570 (seedless plants) |
| Internal Structure of Flowering Plant and Mammal | m66596 “The Plant Body” (plant side; mammal side no-source outside A&P) |
| Transport | m66650, m66651, m66653 (circulation), m66600 “Transport of Water and Solutes in Plants” |
| Respiration | m66466 (Glycolysis), m66467 (Krebs), m66468, m66646 (Gas Exchange) |
| Excretion | m66658 (Kidneys), m66659 |
| Support and Movement | m66635 (Skeletal Systems), m66639, m66643, m66601 (Plant Responses) |
| Reproduction | m66668, m66607, m66608, m66609, m66673, m66674 |
| Coordination and Control | m66620, m66621, m66622, m66623, m66626 (Hormones), m66613 (Homeostasis), m66402 (Sensory Processes) |
| Factors Affecting Distribution | m66419 “Climate and the Effects of Global Climate Change” |
| Symbiotic Interactions | m66698 (Community Ecology), m66702 (Energy Flow), m66705 (Biogeochemical Cycles) |
| Natural Habitats | m66417 (Aquatic Biomes), m66420 (Terrestrial Biomes) |

### Thin

Variety of Organisms (bio_adaptive), Growth (bio_plant-candidates), Ecology of Populations (m66686/m66691/m66690 demography+dynamics needed), Variation in Population (m66487), Heredity (m66487/m66488/m66491/m66494), Evidence of Evolution (m66531).

### No-source (2)

- **Local (Nigerian) Biomes** — generic terrestrial biomes only (m66420).
- **Soil** — types/components/fertility.

Covered: Living Organisms, Nutrition, Humans and Environment, Theories of Evolution.

## Notable WAEC-only differences

- WAEC progressive/optics topics bundle more (e.g. `waec-light-waves` = reflection + refraction + lenses + dispersion) — same candidates as JAMB optics.
- `waec-heat-energy` bundles gas laws + heat capacity + latent heat + humidity — big topic, candidates m58387/88/89 + m68751; humidity subtopic no-source.
- Applied/practical biology topics (dissection, water/fishing/food industry, biotechnology, sampling, drawing/sectioning, procedure for biological work) are **no_source** — 11 WAEC biology topics. A hand-authoring or fallback decision is needed for them together.
- waec-fibre-optics, waec-simple-machines, waec-soil, waec-local-biomes, waec-air, waec-water-treatment: no-source flags above.

## Proposed next scrape order (closes the most topics per module)

1. **Physics wave/heat block** — m58304, m58342, m58386, m58387, m58388, m58389 (6 modules → Friction, Elasticity, Thermal Expansion, Quantity of Heat, Change of State, Heat Transfer + kinetic theory partial)
2. **Physics electricity block** — m58448..50, m58453, m58729..32, m58455, m58734, m58472, m58494, m58480, m58600..01 (capacitors→electronics; closes 7 JAMB topics)
3. **Physics optics block** — m58509..12, m58527..32, m58534, m58503 (closes reflection, refraction, optical instruments, dispersion)
4. **Chemistry descriptive block** — m68827+m68822/23/26, m68797/99, m68830..40 selection (closes electrolysis, equilibrium, non-metals, metals)
5. **Chemistry depth block** — m68700, m68734, m68738, m68742, m68804/08/09, m68816/17, m68787, m68793, m68847 (turns 8 thin topics covered)
6. **Biology organ-systems block** — m66466..68, m66645/46, m66650/51/53, m66600, m66658/59, m66620..23, m66626, m66613 (closes respiration, transport, excretion, coordination)
7. **Biology reproduction/ecology block** — m66668, m66607/08/09, m66673, m66635..43, m66698, m66702, m66705, m66417/20, m66419, m66530/45/54/58/70/96 (closes the rest of the gaps)
8. **Physics shared top-ups** — m58291, m58305, m58345/46/47, m58310, m58353/55/56, m58361(optional), m58372/73, m58377..81, m58484, m58742, m58490, m4couple EM waves extras (turns 15 thin topics covered)
