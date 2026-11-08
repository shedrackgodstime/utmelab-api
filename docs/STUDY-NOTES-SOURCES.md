# Study Notes Curriculum Sources and Editorial Standard

This document records the official curriculum sources, reference literature, pedagogical principles, and attribution standards for UTMELAB study notes.

---

## 1. Official Examination Body Syllabuses

All study notes map directly to the approved syllabuses of West African examining bodies:

1. **Joint Admissions and Matriculation Board (JAMB)**
   - Official Unified Tertiary Matriculation Examination (UTME) Syllabus.
   - Reference portal: Integrated Brochure and Syllabus System (`ibass.jamb.gov.ng`).
   - Annual Information and Guideline for Candidates (Use of English, Mathematics, Physics).

2. **West African Examinations Council (WAEC)**
   - West African Senior School Certificate Examination (WASSCE) Regulations and Syllabuses for Senior High Schools.
   - Annual WAEC Chief Examiners' Reports (General Comments, Candidate Weaknesses, and Suggested Remedies in English Language and General Mathematics).

3. **National Examinations Council (NECO)**
   - Senior School Certificate Examination (SSCE) Specifications.

---

## 2. Standard Reference Textbooks

Every definition, mathematical derivation, phonetic transcription, and grammatical rule derives from accredited secondary and tertiary textbooks adopted across Nigeria and Ghana:

### Mathematics
- *New General Mathematics for Senior Secondary Schools (Books 1, 2, and 3)* by M.F. Macrae, A.O. Kalejaiye, Z.I. Chima, et al. (Pearson / Longman).
- *Comprehensive Mathematics for Senior Secondary Schools* by D.B. Adu (Johnson Publishers).
- *Engineering Mathematics (Foundation Sections)* by K.A. Stroud and Dexter Booth (Bloomsbury).

### English Language and Phonology
- *Intensive English for Senior Secondary Schools (Books 1, 2, and 3)* by Benson O.A. Oluikpe, et al. (African First Publishers).
- *English Pronouncing Dictionary (18th Edition)* by Daniel Jones, edited by Peter Roach, Jane Setter, and John Esling (Cambridge University Press).
- *A University Grammar of English* by Randolph Quirk and Sidney Greenbaum (Longman).
- *Countdown to Senior Secondary Certificate Examination (SSCE) English Language* by Ogunsanwo et al. (Evans Brothers).
- *Oral English for Schools and Colleges* by Sam Onuigbo (Africana First).

### Physics
- *Senior Secondary School Physics* by P.N. Okeke and M.W. Anyakoha (Africana First Publishers).
- *Principles of Physics for Senior Secondary Schools* by M. Nelkon (Longman).

---

## 3. Pedagogical Structure and Editorial Constraints

Every note in the catalog enforces seven strict pedagogical components:

1. **Key Takeaway**: One clear sentence summarizing the governing principle.
2. **Concept Sections**: Chunked reading units broken into 2 to 4 digestible sections with bold key terms and formatted inline highlights.
3. **Structured Callouts**: Highlighting critical concepts, warnings against frequent traps, or examiner tips.
4. **Worked Step-by-Step Examples**: Real exam-style problems decomposed into explicit sequential steps, expressions, and final answers.
5. **Formal Formulas and Rules**: LaTeX expressions defining variables, units, and boundary conditions.
6. **Active Recall Checks**: Two interactive multiple-choice items testing immediate concept retention with complete pedagogical explanations for both correct choices and common misconceptions.
7. **Examiner Traps**: Documented errors directly sourced from WAEC Chief Examiners' Reports, addressing why students repeatedly lose marks on that specific concept.

---

## 4. Technical Constraints

- **Payload Bound**: Maximum 16 KiB per note to preserve low memory footprints and rapid mobile transfer.
- **Clean Writing Standard**: Zero em dashes or en dashes. No hyphen substitutes. Active voice. Simple Saxon words over Latinate bloat.
- **Offline Replica Parity**: Stored locally in libSQL tables (`topic_notes`) and queried in under 15 milliseconds without external network calls.
