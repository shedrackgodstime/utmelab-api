# Study Notes Source Manifest

**Access date for all URLs below:** 2026-11-09.
**Scope:** The 26 production notes snapshotted in
`data/notes-snapshots/2026-11-09-production-notes.json` (captured
2026-11-09T12:37:41Z from production `topic_notes`). This manifest records,
per note, the placement, audit verdict, exact sources, locators, and which
claims each source supports, plus the claims that were withdrawn for lack of
source support.

Authority order (per `docs/STUDY-NOTES-SPEC.md` section 3):

1. Official examining-body syllabus or regulation document.
2. Official examiner report or marking scheme.
3. Recognised educational reference or textbook (OpenStax, Cambridge
   Dictionary, Cambridge Phonetics textbook, Purdue OWL, British Council,
   FCT EMIS secondary guide).

A source counts only if it is a live page or document that directly states
the claim. Search-result snippets and homepages do not count. The WAEC
syllabus mirror at `rachel.worldpossible.org` is used only because the
direct WAEC PDF URL was not found; the document itself is the WAEC WASSCE
English syllabus. The FCT EMIS PDF is a secondary guide that reproduces the
mark allocation; it is never used to support a penalty figure.

Verdicts: **Rewrite** = structure and most facts sound, add sources, strip
duplicated numeric heading prefixes, recompute read time. **Replace** =
factual or syllabus-scope error present, rewritten in full with sources.
**Keep** = none: every snapshot note lacks `sources` and carries the
duplicated-heading and inflated-read-time defects.

Structural normalisations applied to every note: headings lose their manual
`N.` prefix (`section_number` already carries the number); read time is
recomputed from word count as `ceil(total_words / 150)`, bounded 1 to 6
minutes; `sources` is populated with at least one `NoteSource`; callout
kinds are restricted to `key_concept`, `examiner_tip`, `warning`, `law`,
`definition`.

## JAMB Mathematics (5)

### note_math_jamb_ap — Rewrite

Placement: JAMB / mathematics / progression / sum-of-arithmetic-progression-a-p.
Verdict: Rewrite. Note states the correct formulas; no factual error found.

| Title | URL | Locator | Supports |
| --- | --- | --- | --- |
| College Algebra 2e, Section 9.2: Arithmetic Sequences | https://openstax.org/books/college-algebra-2e/pages/9-2-arithmetic-sequences | Section 9.2 | AP definition, nth term `T_n = a + (n-1)d`, sum formulas |
| JAMB Mathematics syllabus | https://ibass.jamb.gov.ng/static/media/Mathematics.c0621f4b8b674e75fd05.pdf | Syllabus, progression topics | Syllabus placement |

### note_math_jamb_differentiation — Rewrite

Placement: JAMB / mathematics / differentiation /
differentiation-of-explicit-algebraic-and-simple-trigonometr.
Verdict: Rewrite.

| Title | URL | Locator | Supports |
| --- | --- | --- | --- |
| Calculus Volume 1, Section 3.3: Differentiation Rules | https://openstax.org/books/calculus-volume-1/pages/3-3-differentiation-rules | Section 3.3 | Power rule, derivatives of constants and polynomials |
| Calculus Volume 1, Section 3.5: Derivatives of Trigonometric Functions | https://openstax.org/books/calculus-volume-1/pages/3-5-derivatives-of-trigonometric-functions | Section 3.5 | `d/dx sin x = cos x`, `d/dx cos x = -sin x` |
| JAMB Mathematics syllabus | https://ibass.jamb.gov.ng/static/media/Mathematics.c0621f4b8b674e75fd05.pdf | Syllabus, differentiation topics | Syllabus placement |

### note_math_jamb_laws_of_indices — Rewrite

Placement: JAMB / mathematics / indices-logarithms-and-surds / laws-of-indices.
Verdict: Rewrite.

| Title | URL | Locator | Supports |
| --- | --- | --- | --- |
| College Algebra 2e, Section 1.2: Exponents and Scientific Notation | https://openstax.org/books/college-algebra-2e/pages/1-2-exponents-and-scientific-notation | Product, quotient, power, zero, negative rules | Index laws for common bases, zero and negative exponents |
| College Algebra 2e, Section 1.3: Radicals and Rational Exponents | https://openstax.org/books/college-algebra-2e/pages/1-3-radicals-and-rational-exponents | Rational exponents | `a^(m/n) = (a^(1/n))^m` |
| JAMB Mathematics syllabus | https://ibass.jamb.gov.ng/static/media/Mathematics.c0621f4b8b674e75fd05.pdf | Syllabus, indices topics | Syllabus placement |

### note_math_jamb_surds — Rewrite

Placement: JAMB / mathematics / indices-logarithms-and-surds / surds.
Verdict: Rewrite.

| Title | URL | Locator | Supports |
| --- | --- | --- | --- |
| College Algebra 2e, Section 1.3: Radicals and Rational Exponents | https://openstax.org/books/college-algebra-2e/pages/1-3-radicals-and-rational-exponents | Product rule, rationalising denominators (conjugate) | Simplify surds, like surds, rationalise binomial denominators |
| JAMB Mathematics syllabus | https://ibass.jamb.gov.ng/static/media/Mathematics.c0621f4b8b674e75fd05.pdf | Syllabus, surds | Syllabus placement |

### note_math_jamb_trig_ratios — Rewrite

Placement: JAMB / mathematics / trigonometry / trigonometrical-ratios-of-angles.
Verdict: Rewrite.

| Title | URL | Locator | Supports |
| --- | --- | --- | --- |
| Algebra and Trigonometry, Section 7.2: Right Triangle Trigonometry | https://openstax.org/books/algebra-and-trigonometry/pages/7-2-right-triangle-trigonometry | Section 7.2 | SOH CAH TOA, special-angle values, `sin^2 + cos^2 = 1` |
| JAMB Mathematics syllabus | https://ibass.jamb.gov.ng/static/media/Mathematics.c0621f4b8b674e75fd05.pdf | Syllabus, trigonometry topics | Syllabus placement |

## JAMB Physics (2)

### note_phys_jamb_motion — Replace

Placement: JAMB / physics / motion (topic note, no subtopic).
Verdict: Replace. Snapshot has 2 sections, 62 words, no worked example, one
recall check. Rewritten with 3 sections, 2 worked examples, full formula set,
2 recall checks, and sources.

| Title | URL | Locator | Supports |
| --- | --- | --- | --- |
| College Physics 2e, Section 2.1: Displacement | https://openstax.org/books/college-physics-2e/pages/2-1-displacement | Section 2.1 | Distance vs displacement, vectors and scalars |
| College Physics 2e, Section 2.5: Motion Equations for Constant Acceleration in One Dimension | https://openstax.org/books/college-physics-2e/pages/2-5-motion-equations-for-constant-acceleration-in-one-dimension | Section 2.5 | Kinematic equations `v = u + at`, `s = ut + at^2/2`, `v^2 = u^2 + 2as` |
| JAMB Physics syllabus | https://ibass.jamb.gov.ng/static/media/Physics.16527a294cb7e7a87a35.pdf | Syllabus, motion topics | Syllabus placement |

### note_phys_jamb_projectile_motion — Rewrite

Placement: JAMB / physics / motion /
projectiles-range-maximum-height-time-of-flight-and-applicat.
Verdict: Rewrite. Physics content is sound; add sources and fix headings.

| Title | URL | Locator | Supports |
| --- | --- | --- | --- |
| College Physics 2e, Section 3.4: Projectile Motion | https://openstax.org/books/college-physics-2e/pages/3-4-projectile-motion | Section 3.4 | Independence of motion, max height, range, time of flight |
| JAMB Physics syllabus | https://ibass.jamb.gov.ng/static/media/Physics.16527a294cb7e7a87a35.pdf | Syllabus, projectiles | Syllabus placement |

## JAMB Use of English (12)

All 12 map to the JAMB Use of English syllabus three-section structure:
Section A Comprehension and Summary, Section B Lexis and Structure,
Section C Oral Forms. Exam structure (60 marks): comprehension 5, summary 5,
cloze 10, reading text 5, sentence interpretation 5, antonyms 5, synonyms 5,
basic grammar 10, vowels 2, consonants 2, rhymes 2, word stress 2, emphatic
stress 2. Source for that structure:
`https://ibass.jamb.gov.ng/static/media/Use-of-English.885e843b1f51e6a3d062.pdf`,
locator Detailed Contents and the marking breakdown.

### note_eng_jamb_antonyms — Rewrite

Placement: JAMB / use-of-english / lexis-and-structure / antonyms.
Verdict: Rewrite. Negative-prefix generalisations tightened; contextual
opposition retained.

| Title | URL | Locator | Supports |
| --- | --- | --- | --- |
| Cambridge Dictionary, antonym | https://dictionary.cambridge.org/dictionary/english/antonym | antonym | Antonym as word of opposite meaning; context dependence |
| Cambridge Dictionary, Prefixes | https://dictionary.cambridge.org/grammar/british-grammar/prefixes | Prefixes | `un-`, `im-`/`il-`/`ir-` assimilation noted as a tendency, not an exceptionless law |

### note_eng_jamb_synonyms — Rewrite

Placement: JAMB / use-of-english / lexis-and-structure / synonyms.
Verdict: Rewrite.

| Title | URL | Locator | Supports |
| --- | --- | --- | --- |
| Cambridge Dictionary, synonym | https://dictionary.cambridge.org/dictionary/english/synonym | synonym | Synonym as word with similar meaning; sense and register differences |
| Cambridge Dictionary, Word classes and phrase classes | https://dictionary.cambridge.org/grammar/british-grammar/word-classes-and-phrase-classes | Word classes | Replacement must match word class to stay grammatical |

### note_eng_jamb_concord — Replace

Placement: JAMB / use-of-english / lexis-and-structure / basic-grammar.
Verdict: Replace. Error fixed: the snapshot claims "I and you always select
plural verb forms". That is false for the verb `be`: `I am`, `I was` are
singular, while `you are`, `you were` are plural even for one person.
`I have`, `you have` are correct; `I has` is wrong; `I am`, not `I are`,
is right. The rule is person-and-number agreement, not a blanket plural
claim. Proximity with `either...or` / `neither...nor` retained, with the
note that proximity is the dominant exam rule for agreement with the nearer
subject, not a universal law of grammar.

| Title | URL | Locator | Supports |
| --- | --- | --- | --- |
| Cambridge Dictionary, Subject-verb agreement | https://dictionary.cambridge.org/grammar/british-grammar/subject-verb-agreement | Subject-verb agreement | Person and number of the subject determine the verb; `he hates` vs `we go`, `you are` not `you is` |
| Purdue OWL, Subject-Verb Agreement | https://owl.purdue.edu/owl/general_writing/grammar/subject_verb_agreement.html | Subject-verb agreement | Intervening phrases, indefinite pronouns `each`, `everyone` take singular verbs |

### note_eng_jamb_comprehension — Replace

Placement: JAMB / use-of-english / comprehension / comprehension.
Verdict: Replace. Error fixed: "Every well-structured academic paragraph
contains one central idea articulated in a topic sentence" overgeneralises.
Many paragraphs state the point implicitly, split it across sentences, or
reveal it through examples. Rewritten to present the topic sentence as a
common helpful signal, not a guaranteed component, and to ground the note in
the syllabus task: identify main points/topic sentences, determine implied
meanings, identify grammatical functions, infer author mood, attitude, and
opinion.

| Title | URL | Locator | Supports |
| --- | --- | --- | --- |
| JAMB Use of English syllabus | https://ibass.jamb.gov.ng/static/media/Use-of-English.885e843b1f51e6a3d062.pdf | Section A, Detailed Contents (a)-(d) and objectives | Comprehension tasks: main points, implied meaning, grammatical functions, inference of attitude |
| Cambridge Grammar, Clauses | https://dictionary.cambridge.org/grammar/british-grammar/clauses | Clauses | Clause and sentence structure for "grammatical functions" items |

### note_eng_jamb_cloze — Rewrite

Placement: JAMB / use-of-english / comprehension / cloze.
Verdict: Rewrite.

| Title | URL | Locator | Supports |
| --- | --- | --- | --- |
| Cambridge Dictionary, cloze test | https://dictionary.cambridge.org/dictionary/english/cloze-test | cloze test | Definition: text with words missing that you have to fill in |
| JAMB Use of English syllabus | https://ibass.jamb.gov.ng/static/media/Use-of-English.885e843b1f51e6a3d062.pdf | Section A | One of the three passages set is a cloze test, about 200 words, various disciplines |

### note_eng_jamb_sentence_interpretation — Rewrite

Placement: JAMB / use-of-english / lexis-and-structure / sentence-interpretation.
Verdict: Rewrite. Tightened: `it is high time` + past form expresses present
urgency, not past time; `could have done` means unfulfilled past ability.

| Title | URL | Locator | Supports |
| --- | --- | --- | --- |
| Cambridge Dictionary, Conditionals: if | https://dictionary.cambridge.org/grammar/british-grammar/conditionals-if | Conditionals: if | First, second, third conditionals; third conditional = past counterfactual |
| Cambridge Dictionary, Past verb forms referring to the present | https://dictionary.cambridge.org/grammar/british-grammar/past-verb-forms-referring-to-the-present | Past forms for present meaning | `It is high time we left` uses past form for present/future urgency |
| Cambridge Dictionary, subjunctive | https://dictionary.cambridge.org/dictionary/english/subjunctive | subjunctive | Subjunctive mood: hypothetical or contingent situations |

### note_eng_jamb_vowels — Replace

Placement: JAMB / use-of-english / oral-forms / vowels.
Verdict: Replace. Gap filled: the JAMB syllabus lists vowels, diphthongs,
and triphthongs; the snapshot covers only monophthongs and diphthongs.
Triphthong section added (Cambridge: a vowel sound spanning three vowel
positions, e.g. `fire` as a triphthong in some descriptions; RP sequences
like `/aɪə/`, `/eɪə/` are treated as triphthongal in the syllabus tradition).

| Title | URL | Locator | Supports |
| --- | --- | --- | --- |
| Roach et al., English Phonetics and Phonology, Chapter 4: Vowels | https://www.cambridge.org/highereducation/books/english-phonetics-and-phonology/70DA321F274B7A14D475C9856D23F490/vowels/A063D0CC7431222FA127EE0C881B6131 | Chapter 4 | 12 monophthongs, articulatory classification |
| Roach et al., Chapter 5: Diphthongs and Pre-rhotic and Weak Vowels | https://www.cambridge.org/highereducation/books/english-phonetics-and-phonology/70DA321F274B7A14D475C9856D23F490/diphthongs-and-pre-rhotic-and-weak-vowels/C6CEB97C8A8EDFC669D4FF16CEE32FDA | Chapter 5 | 8 diphthongs, centering and closing types |
| Cambridge Dictionary, triphthong | https://dictionary.cambridge.org/dictionary/english/triphthong | triphthong | Triphthong definition (three-position vowel glide) |
| JAMB Use of English syllabus | https://ibass.jamb.gov.ng/static/media/Use-of-English.885e843b1f51e6a3d062.pdf | Section C, Oral Forms | Vowels, diphthongs, triphthongs all examinable |

### note_eng_jamb_consonants — Replace

Placement: JAMB / use-of-english / oral-forms / consonants.
Verdict: Replace. Error fixed: the snapshot states silent `p` occurs before
`s` or `n`, then lists `receipt` (where `p` precedes `t`). Corrected to two
distinct patterns: initial `ps-` in Greek-derived words (`psychology`,
`pneumonia`, `psalm`) and `p` before `t` in `receipt`, `receipts`, `dept`?
no, `debt` has silent `b`; `receipt` keeps the pattern `p` + `t`. `TH`
voicing stated as a tendency: function words (`this`, `that`) usually take
`/ð/`, content words usually `/θ/`, with exceptions (`thesis`, `smooth`
contains `/ð/`).

| Title | URL | Locator | Supports |
| --- | --- | --- | --- |
| Roach et al., Chapter 3: Consonants | https://www.cambridge.org/highereducation/books/english-phonetics-and-phonology/70DA321F274B7A14D475C9856D23F490/consonants/5424C673637BCB29B31C0AFFCC6C2637 | Chapter 3 | Consonant inventory, voicing pairs, `/θ/` vs `/ð/` |
| British Council, Silent letters | https://africa.teachingenglish.org.uk/classroom/pronunciation/silent-letters | Silent letters | Silent `k` (`know`, `knee`), silent `w` (`write`, `sword`), silent `t` (`listen`), silent `b` (`climb`), silent `g` (`sign`) |

### note_eng_jamb_rhymes — Rewrite

Placement: JAMB / use-of-english / oral-forms / rhymes.
Verdict: Rewrite. Auditory criterion retained; eye rhymes illustrated.

| Title | URL | Locator | Supports |
| --- | --- | --- | --- |
| Cambridge Dictionary, rhyme | https://dictionary.cambridge.org/dictionary/english/rhyme | rhyme | Rhyme as matching terminal sounds (end rhyme, internal rhyme) |
| Cambridge Dictionary, homophone | https://dictionary.cambridge.org/dictionary/english/homophone | homophone | Homophones: same sound, different spelling/meaning |

### note_eng_jamb_word_stress — Replace

Placement: JAMB / use-of-english / oral-forms / word-stress.
Verdict: Replace. Error fixed: the disyllabic noun/verb stress shift
(`REcord` noun, `reCORD` verb) was presented as a reliable rule. It is a
common pattern with exceptions and does not hold for many pairs
(`answer` noun/verb, `visit`, `practice` noun in some varieties). Rewritten
to flag the pattern as a tendency and to keep the suffix rules, which are
more dependable, while noting they are tendencies too.

| Title | URL | Locator | Supports |
| --- | --- | --- | --- |
| Roach et al., Chapter 11: Word Stress | https://www.cambridge.org/highereducation/books/english-phonetics-and-phonology/70DA321F274B7A14D475C9856D23F490/word-stress/7F95B124452EA1CA023560EDF2E00924 | Chapter 11 | Primary stress, suffix influence (`-tion`, `-ic`, `-ity`) |
| BBC Learning English, Pronunciation Lounge Episode 8 transcript | https://downloads.bbc.co.uk/learningenglish/features/the_pronunciation_lounge/pron_lounge_episode_8_transcript_.pdf | Pronunciation Lounge 8 | Stress in polysyllabic words for learners |
| JAMB Use of English syllabus | https://ibass.jamb.gov.ng/static/media/Use-of-English.885e843b1f51e6a3d062.pdf | Section C, Oral Forms | Word stress (monosyllabic and polysyllabic), emphatic stress in connected speech |

### note_eng_jamb_emphatic_stress — Rewrite

Placement: JAMB / use-of-english / oral-forms / emphatic-stress.
Verdict: Rewrite.

| Title | URL | Locator | Supports |
| --- | --- | --- | --- |
| Roach et al., Chapter 13: Intonation | https://www.cambridge.org/highereducation/books/english-phonetics-and-phonology/70DA321F274B7A14D475C9856D23F490/intonation/3CEF1DFB2F4BB6D81E8136F2CE7D5C7B | Chapter 13 | Prominence and contrast in connected speech |
| Cambridge Dictionary, emphatic | https://dictionary.cambridge.org/dictionary/english/emphatic | emphatic | Emphatic word = stressed, given more force than others; `WEALTH IS power` example |

### note_eng_jamb_fiction — Replace

Placement: JAMB / use-of-english / comprehension / fiction.
Verdict: Replace. Scope corrected: the JAMB Use of English syllabus does
not list `fiction` as a comprehension passage type. The set types are
description, narration, exposition, and argumentation/persuasion, plus an
approved reading text and synthesis tasks. The note is reframed as narrative
comprehension: figures of speech, idioms, and story elements as they appear
inside those passage types.

| Title | URL | Locator | Supports |
| --- | --- | --- | --- |
| JAMB Use of English syllabus | https://ibass.jamb.gov.ng/static/media/Use-of-English.885e843b1f51e6a3d062.pdf | Section A (a)-(d), objectives | Passage types are description, narration, exposition, argumentation/persuasion; figures of speech and idioms tested inside them |
| Purdue OWL, Reading a Novel or Story | https://owl.purdue.edu/owl/subject_specific_writing/writing_in_literature/writing_in_literature_detailed_discussion/reading_a_novel_or_story.html | Reading a Novel or Story | Theme, plot, character, point of view as reading tools |
| Britannica, Fiction (literature) | https://www.britannica.com/art/fiction-literature | Fiction | Fiction as invented prose narrative; used only for the framing definition, not for a JAMB task type |

## WAEC English Language (7)

WAEC English syllabus structure (Paper 2, 2 hours, 100 marks): Section A
Essay writing 50 marks (50 minutes, answer one of five topics, minimum 450
words; content, organisation, expression, mechanical accuracy); Section B
Comprehension 20 marks (30 minutes, one passage of at least 350 words,
answer all questions); Section C Summary 30 marks (40 minutes, prose passage
of about 500 words). Source:
`https://rachel.worldpossible.org/mods/en-wassce/WASSCESYLABUS/ENGLISH_LANGUAGE.pdf`,
locator Paper 2, Sections A-C. The conflicting third-party claims of
Summary 20 or Comprehension 30 are inconsistent with this breakdown and are
not used.

### note_waec_eng_essay_marking_rubric — Replace

Placement: WAEC / english-language / waec-essay-writing /
waec-organization-formal-features-where-applicable-good-paragraph.
Verdict: Replace. Withdrawn claims: the 0.5-mark-per-ringed-error deduction
and the worked calculation built on it are not in any official source
located. The FCT EMIS guide allocates marks and lists error categories but
states no per-error rate, and reports only that when a composition falls
appreciably short of 450 words "the maximum mark for MA will be
proportionately reduced". The note now teaches the supported facts:
10/10/20/10 allocation, the four criteria, the 450-word minimum, and the
shortfall consequence in those hedged terms. The numeric formula and the
proportional penalty as a fixed rule are removed.

| Title | URL | Locator | Supports |
| --- | --- | --- | --- |
| WAEC WASSCE English Language syllabus (mirror) | https://rachel.worldpossible.org/mods/en-wassce/WASSCESYLABUS/ENGLISH_LANGUAGE.pdf | Paper 2, Section A | Essay 50 marks, 50 minutes, 450-word minimum, four marking criteria |
| FCT EMIS, WAEC English marking guide (Jan 2024) | https://fctemis.org/notes/871_9%20January%202024.pdf | Mark Allocation, Length of Composition, Mechanical Accuracy | Content 10, Organisation 10, Expression 20, Mechanical Accuracy 10; error categories (grammar, punctuation, spelling); shortfall reduces MA maximum |
| WAEC e-learning, English Paper 2 May-June 2015, Weaknesses | https://www.waeconline.org.ng/e-learning/English/Engl224mw.html | Candidates' Weaknesses | Recurring weaknesses: wrong tenses and number, weak paragraphing, inability to restate in own words, "mindless lifting" |

### note_waec_eng_summary_writing — Replace

Placement: WAEC / english-language / waec-summary /
waec-summarize-the-points-demanded-in-clear-concise-english-avoid.
Verdict: Replace. Withdrawn claims: the exact 5 / 2.5 fragment award and the
formula presenting "half marks" as a fixed per-point rate. Official WAEC
reports establish the substance (write in complete sentences, do not lift
verbatim, separate main ideas from details and illustrations, avoid
extraneous material and wordy preambles) but no official source located
states a fixed numeric per-point award. The half-mark figure appears in
third-party lesson materials, which are not official and are not cited. The
note teaches the official substance without a numeric award table.

| Title | URL | Locator | Supports |
| --- | --- | --- | --- |
| WAEC WASSCE English Language syllabus (mirror) | https://rachel.worldpossible.org/mods/en-wassce/WASSCESYLABUS/ENGLISH_LANGUAGE.pdf | Paper 2, Section C (30 marks, 40 minutes, about 500 words) | Extract relevant information; summarise in clear concise English; avoid repetition and redundancy |
| WAEC e-learning, English Paper 2 May-June 2023, Summary | https://waeconline.org.ng/e-Learning/English/Engl240mq7.html | Question 7, Summary | Some lifted sentences verbatim; many could not separate main ideas from details and illustrations; some included extraneous materials |
| WAEC e-learning, English Paper, Aug-Sept 2018, Summary | https://www.waeconline.org.ng/e-learning/English/Engl227aq7.html | Question 7, Observation | Many wrote answers in phrases instead of sentences as demanded; summarise in own words |
| WAEC e-learning, English Paper 2 May-June 2015, Summary | https://www.waeconline.org.ng/e-learning/English/Engl224mq7.html | Observation | Some used preambles that, with the answers, did not make sentences; copying copiously is not summary writing |
| WAEC e-learning, English Language Paper 1 Nov/Dec 2012, Summary | https://www.waeconline.org.ng/e-learning/English/Engl121Nq8.html | Question 8, observation | Summarise in own words; lifting portions verbatim is far from summary writing; problems separating main ideas from details |
| WAEC e-learning, English Paper 2 May-June 2015, Weaknesses | https://www.waeconline.org.ng/e-learning/English/Engl224mw.html | Candidates' Weaknesses | "Mindless lifting of portions of the set passages as answers" listed as a recurring weakness |
| Purdue OWL, Quoting, Paraphrasing, and Summarizing | https://owl.purdue.edu/owl/research_and_citation/using_research/quoting_paraphrasing_and_summarizing/index.html | Quoting, Paraphrasing, and Summarizing | Summarising = main idea(s) in your own words, significantly shorter, broad overview |

### note_waec_eng_letter_writing — Replace

Placement: WAEC / english-language / waec-essay-writing / waec-letter.
Verdict: Replace. Claim softened: the snapshot says "never 'Dear
Sir/Madam'". That absolute is not a WAEC rule found in any source located.
The defensible rule is the salutation-subscription pairing: `Dear Sir` /
`Dear Madam` with `Yours faithfully`; a personal salutation with `Yours
sincerely` or `Yours affectionately`. The `Dear Sir/Madam` form is treated
as a non-standard variant to avoid, not as a universally "never" rule.

| Title | URL | Locator | Supports |
| --- | --- | --- | --- |
| Purdue OWL, Basic Business Letters | https://owl.purdue.edu/owl/subject_specific_writing/professional_technical_writing/basic_business_letters/index.html | Basic Business Letters | Formal letter parts: sender address, date, salutation, subject, body, closing (`Yours faithfully` / `Sincerely`) |
| WAEC WASSCE English Language syllabus (mirror) | https://rachel.worldpossible.org/mods/en-wassce/WASSCESYLABUS/ENGLISH_LANGUAGE.pdf | Paper 2, Section A | Letter is one of the essay forms; formal features count under Organisation |

### note_waec_eng_grammatical_structures — Rewrite

Placement: WAEC / english-language / waec-comprehension /
waec-identify-and-label-basic-grammatical-structures-words-phrase.
Verdict: Rewrite.

| Title | URL | Locator | Supports |
| --- | --- | --- | --- |
| WAEC WASSCE English Language syllabus (mirror) | https://rachel.worldpossible.org/mods/en-wassce/WASSCESYLABUS/ENGLISH_LANGUAGE.pdf | Paper 2, Section B | Comprehension test includes identifying and labelling basic grammatical structures, words, phrases, clauses and explaining their functions |
| Cambridge Dictionary, Clauses | https://dictionary.cambridge.org/grammar/british-grammar/clauses | Clauses | Clause = subject + verb phrase; main vs subordinate clauses |
| Cambridge Dictionary, Word classes and phrase classes | https://dictionary.cambridge.org/grammar/british-grammar/word-classes-and-phrase-classes | Phrase classes | Phrases vs clauses; noun, adjective, adverb phrases |

### note_waec_eng_pure_vowels — Rewrite

Placement: WAEC / english-language / waec-vowels / waec-pure-vowels.
Verdict: Rewrite. Overlap with `note_eng_jamb_vowels` is structural, not an
error: JAMB tests vowel quality generally; WAEC Paper 3 tests minimal vowel
contrasts in isolated words. The note keeps the 12 monophthongs and adds the
minimal-pair framing the syllabus states.

| Title | URL | Locator | Supports |
| --- | --- | --- | --- |
| Roach et al., Chapter 4: Vowels | https://www.cambridge.org/highereducation/books/english-phonetics-and-phonology/70DA321F274B7A14D475C9856D23F490/vowels/A063D0CC7431222FA127EE0C881B6131 | Chapter 4 | 12 monophthongs (7 short, 5 long) |
| WAEC WASSCE English Language syllabus (mirror) | https://rachel.worldpossible.org/mods/en-wassce/WASSCESYLABUS/ENGLISH_LANGUAGE.pdf | Paper 3, Oral English | Vowels, diphthongs, consonant clusters, stress and intonation tested in isolated words |

### note_waec_eng_consonant_clusters — Rewrite

Placement: WAEC / english-language / waec-consonants /
waec-consonants-english-language.
Verdict: Rewrite.

| Title | URL | Locator | Supports |
| --- | --- | --- | --- |
| Roach et al., Chapter 3: Consonants | https://www.cambridge.org/highereducation/books/english-phonetics-and-phonology/70DA321F274B7A14D475C9856D23F490/consonants/5424C673637BCB29B31C0AFFCC6C2637 | Chapter 3 | Consonant clusters in onset and coda; voicing assimilation in `-ed` |
| British Council, Silent letters | https://africa.teachingenglish.org.uk/classroom/pronunciation/silent-letters | Silent letters | Silent letters in `receipt`, `knee`, `listen`, `write`, `sign` |
| WAEC WASSCE English Language syllabus (mirror) | https://rachel.worldpossible.org/mods/en-wassce/WASSCESYLABUS/ENGLISH_LANGUAGE.pdf | Paper 3, Oral English | Consonants and consonant clusters explicitly listed |

### note_waec_eng_intonation_patterns — Rewrite

Placement: WAEC / english-language / waec-intonation /
waec-falling-pattern-they-ar-rived-to-day-statement-where-did-he.
Verdict: Rewrite. Scope note added: Cambridge describes three patterns
(falling, rising, fall-rise); WAEC Paper 3 tests tune selection for
statements, commands, and question types. The two-tune teaching frame is
retained as the exam frame, with fall-rise mentioned as a Cambridge-attested
third pattern learners may meet, not as a WAEC tune to memorise.

| Title | URL | Locator | Supports |
| --- | --- | --- | --- |
| Cambridge Dictionary, Intonation | https://dictionary.cambridge.org/grammar/british-grammar/intonation | Intonation | Voice rises/falls on the final stressed syllable; falling common in wh-questions and definite statements; rising common in yes-no questions |
| Roach et al., Chapter 13: Intonation | https://www.cambridge.org/highereducation/books/english-phonetics-and-phonology/70DA321F274B7A14D475C9856D23F490/intonation/3CEF1DFB2F4BB6D81E8136F2CE7D5C7B | Chapter 13 | Tonic syllable, intonation in connected speech |
| WAEC WASSCE English Language syllabus (mirror) | https://rachel.worldpossible.org/mods/en-wassce/WASSCESYLABUS/ENGLISH_LANGUAGE.pdf | Paper 3, Oral English | Stress and intonation patterns listed for oral testing |

## Import verification (2026-11-09, 13:04Z)

Revised batch `data/notes-replacements/2026-11-09-revised-notes.json` validated
with `scripts/validate_notes.py` (26/26 pass), then imported with
`cargo run -- import-notes`. Production verification:

- `topic_notes` row count: 26 (unchanged placements).
- `sources` coverage: 26/26 notes with 2 to 7 sources each; 0 empty.
- Headings with manual numeric prefixes in production: 0/26 (was 77).
- `content_hash` changed: 26/26 (sources included in hash, per spec).
- Post-import snapshot: `data/notes-snapshots/2026-11-09-post-import-notes.json`
  plus manifest, validated 26/26 pass. Pre-change rollback remains
  `data/notes-snapshots/2026-11-09-production-notes.json`.

## Production catalog fix (2026-11-09)

The previously noted bug, `NECO.mathematics -> WAEC.mathematics`, was fixed
in production: `UPDATE subjects SET syllabus_subject='general-mathematics'
WHERE exam='NECO' AND slug='mathematics'` (1 row updated). The actual WAEC
subject slug is `general-mathematics` (30 topics). Post-fix scan: 53 mapped
subjects, 0 broken targets.

## Open issues remaining

- Official WAEC syllabus direct PDF URL still not located; a mirror is used.
- NECO syllabus and Chief Examiner reports are paywalled; no NECO notes
  exist, so no NECO claim is made here.
- `db/sync-live.db` is not readable by Python `sqlite3` (libSQL format);
  production reads use the Turso HTTP pipeline, per the runbook.
- Britannica returns 403 to scripted requests; browser access is needed.
  Britannica is used only for a framing definition in the fiction note.
