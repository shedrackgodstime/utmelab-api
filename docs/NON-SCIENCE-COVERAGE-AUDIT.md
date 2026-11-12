# Non-science coverage audit: English, Economics, Accounting, Commerce

Date: 2026-11-10

This audit follows the STEM audit rule: every concept is restructured from a
source with the source URL and locator recorded in the concept file. Nothing is
hand-authored or invented. Topics with no matching source are marked
`no_source` rather than filled with guesswork.

Primary sources remain openly licensed. Additional gap-fill and supplement
sources were added under a project decision to prioritise coverage now and
review licence status later; their recorded licence status is kept in this audit,
in each concept file, and in the source tables below.

## Primary sources

| Production subject | Exam/Level | Source | Repository/URL | Licence |
|---|---|---|---|---|
| Economics | JAMB | *Principles of Economics 3e* | `osbooks-principles-economics-bundle` | CC BY-NC-SA 4.0 |
| Principles of Accounts | JAMB | *Principles of Financial Accounting* + *Principles of Managerial Accounting* | `osbooks-principles-accounting-bundle` | CC BY-NC-SA 4.0 |
| Commerce | JAMB | *Introduction to Business 2e* | `osbooks-introduction-business` | CC BY-NC-SA 4.0 |
| Commerce | JAMB | *Entrepreneurship* | `osbooks-entrepreneurship` | CC BY-NC-SA 4.0 |

The OpenStax books supplied 200 modules scraped from CNXML, so tables, figures,
exercises and solutions are preserved where the module contains them.

### English restart and production supplements (foundational base + JAMB/WAEC coverage)

English coverage was restarted from a single coherent foundational series, then
supplemented with sourced concepts to ensure full coverage of JAMB and WAEC
English production topics/subtopics/objectives.

| Level / use | Source | URL | Recorded licence status | Concepts | Locator |
|---|---|---|---|---|---|
| Foundational base | NOUN *GST 101 Use of English and Communication Skills I* | <https://nou.edu.ng/coursewarecontent/GST%20101.pdf> | All rights reserved (licence review pending) | 20 | Modules 1-4, Units 1-5 |
| Foundational base | NOUN *GST 102 Use of English and Communication Skills II* | <https://nou.edu.ng/coursewarecontent/GST%20102.pdf> | All rights reserved (licence review pending) | 20 | Modules 1-4, Units 1-5 |
| Oral/lexis supplement | VMOU *Spoken English: Phonetics and Phonology (CTE-01)* | <https://assets.vmou.ac.in/CTE01.pdf> | As published; licence status to be reviewed | 4 | Units 3, 6, 7, 12 |
| Comprehension supplement | Raymond, *Cloze Procedure in the Teaching of Reading* (TESL Canada Journal, 1988) | <https://teslcanadajournal.ca/index.php/tesl/article/download/544/375> | As published; licence status to be reviewed | 1 | Full article |
| Oral/lexis supplement | Sharma, *Teaching Various Rhymes in English Poetry* (2018) | <https://www.englishjournals.com/assets/archives/2018/vol4issue2/4-2-13-537.pdf> | As published; licence status to be reviewed | 1 | Full article |
| Lexis/structure/comprehension supplement | *Writing for Success – 1st Canadian Edition* (BCcampus / Tara Horkoff) | <https://opentextbc.ca/writingforsuccess/chapter/chapter-2-working-with-words-which-word-is-right/> | CC BY 4.0 | 2 | Ch. 2.2 Spelling; Ch. 2.3 Word Choice and sense relations |
| Lexis/comprehension/usage supplement | *Communication Essentials for College* (eCampusOntario) | <https://ecampusontario.pressbooks.pub/gccomm/> | CC BY-NC 4.0 | 4 | Ch. 13.1 Commonly Confused Words; 13.4 Using Context Clues; 15.7 Slang and Idioms; derived usage mapping |
| Oral exam-skill supplement | KU Open Text & Baruch Tools for Clear Speech (compiled) | <https://opentext.ku.edu/amenglishpronunciation/chapter/thought-groups-and-sentence-stress/> | Source materials as published; licence/status to be reviewed | 1 | Emphatic/contrastive stress (with Baruch TfCS references in concept notes) |
| WAEC syllabus reference | WAEC *WASSCE English Language Syllabus* | <https://modules.oc4d.org/en-wassce/WASSCESYLABUS/ENGLISH_LANGUAGE.pdf> | Official syllabus as published; status recorded for review | 1 | Full syllabus |

GST 101/102 provide 40 unit concepts covering listening and note-taking;
reading strategies and comprehension of diverse texts; vocabulary development;
paragraph/letter/report/summary writing; grammar and usage (articles, concord,
sentences, tenses, gerunds/participles, voice/infinitives, modals); and oral
communication/pronunciation (letters and sounds, vowels and consonants, word
stress and intonation, interviews, seminars, public speech).

Supplements add explicit sourced coverage for cloze procedure, diphthongs/
triphthongs and pure vowels, word/sentence/emphatic/contrastive stress,
intonation, rhymes/rhyming words, homonyms/homophones, synonyms/antonyms and
sense relations, idioms/slang and idiomatic usage awareness, context clues and
meaning in context, spelling/homonyms/commonly confused words/word choice and
connotation, and the WAEC syllabus objectives/domains as a sourced reference.

## Fallback / additional sources

These fill gaps that the primary OpenStax books do not address. Each licence or
recorded licence status is stated in this audit and in each concept file.

| Publisher | Title | Recorded licence/status | Concepts | Locator |
|---|---|---|---|---|
| Mountain Top University | *ACC 308 Public Sector Accounting* | CC BY 4.0 | 2 | Lecture 1 and section 1.2 |
| Caitlin Finlayson | *World Regional Geography* | CC BY-NC-SA 4.0 | 1 | Section 1.5 The Human Setting |
| Pondicherry University, Directorate of Distance Education | *BBA1003/BCOM1003 Principles of Financial Accounting* | All rights reserved (licence review pending) | 4 | Lessons 5.2, 6.1, 6.2, 7.1, 7.2 |
| National Open University of Nigeria | *CRD 122 Nigerian Agriculture* | All rights reserved (licence review pending) | 1 | Module 1 Units 1-5; Unit 13 |
| National Open University of Nigeria | *GST 101/102 Use of English and Communication Skills I-II* | All rights reserved (licence review pending) | 40 | GST 101/102 Modules 1-4, Units 1-5 |

## Excluded fallbacks

Several Nigerian and Indian courseware repositories were checked and rejected
for earlier gap-filling passes where open licensing was required. Per current
project direction, licence is not treated as a blocker now: selected
non-open/review-pending sources (Pondicherry accounting, NOUN CRD 122, NOUN
GST 101/102, and listed English supplements) are used with provenance and
recorded licence status for later review.

## Coverage method

1. Pulled the production topic and subtopic lists from Turso for the four subjects (read-only checks recorded during audit work).
2. Pulled each OpenStax collection XML, extracted every module id and title, and matched modules to topics.
3. Scraped mapped modules with `scripts/scrape_openstax_cnx.py` into `data/concepts/<concept_id>.json`, downloading figures into `data/concepts/images/`.
4. Sliced licensed/review-pending PDFs with `scripts/scrape_open_pdf.py` and web/text extraction where a topic had no OpenStax match and a reliable source was identified.
5. Added sourced web supplements (with URL/locator/licence status) for production English exam skills/objectives not fully explicit in the foundational base.
6. Assigned status per topic: `covered` (mapped sources address the topic/subtopics), `thin` (sourced but at least one subtopic not fully matched), `no_source` (no matching source found).

## Production English coverage matrix (JAMB/WAEC)

English is mapped in `data/concepts/audit-nonscience.json` at Foundational, JAMB, and WAEC levels with concept references and notes. All referenced concept files exist.

### JAMB Use of English

| Topic | Production subtopics/objectives | Status | Key sourced concepts/mapping |
|---|---|---|---|
| Comprehension and Summary | Fiction/narrative, cloze, comprehension; interpretation; note-taking/summary skills | covered | GST 101 reading/listening/note-taking units; `eng_cloze_procedure`; `eng_context_clues` |
| Lexis and Structure | Sentence interpretation, antonyms, synonyms, basic grammar; vocabulary/usage in context | covered | GST 101/102 vocabulary and grammar units; `eng_word_choice_sense_relations` (synonyms/antonyms, connotation/sense relations); `eng_context_clues` (meaning in context/sentence interpretation support); `eng_slang_and_idioms`; `eng_spelling_and_homonyms`; `eng_commonly_confused_words`; `eng_homonyms_homophones` |
| Oral Forms | Vowels, consonants, rhymes, word stress, emphatic stress | covered | GST 102 M3U1/M3U2/M3U3-M3U5; `eng_phonetics_diphthongs_triphthongs` (vowels/diphthongs/triphthongs/pure vowels); `eng_phonetics_stress`; `eng_phonetics_intonation`; `eng_emphatic_contrastive_stress`; `eng_rhyme_in_english`; `eng_homonyms_homophones` |

### WAEC English Language

| Topic/paper area | Production topics/subtopics/objectives | Status | Key sourced concepts/mapping |
|---|---|---|---|
| Lexis and Structure (Paper 1) | Vocabulary of everyday/common usage and syllabus fields of human activity; idioms/idiomatic expressions and collocations; structural elements (sequence of tenses, concord/agreement, prepositions, pronoun-antecedent matching etc.); figurative usage; sense relations (synonyms, antonyms, homonyms); word choice/meaning in context | covered | GST 101/102 vocabulary and grammar units; `eng_word_choice_sense_relations`; `eng_slang_and_idioms`; `eng_context_clues`; `eng_spelling_and_homonyms`; `eng_commonly_confused_words`; `eng_homonyms_homophones`; `eng_waec_english_language_syllabus` (records lexis fields/domains and objectives) |
| Essay Writing (Paper 2 Section A) | Content relevance; organization/paragraphing/coherence; expression (vocabulary and sentence structure control/variety); mechanical accuracy (grammar, punctuation, spelling); forms including letter, speech, narration, description, argument/debate, report, article, exposition, creative writing | covered | GST 102 M1/M2 paragraph and functional writing units; `eng_spelling_and_homonyms`; `eng_commonly_confused_words`; `eng_word_choice_sense_relations`; `eng_waec_english_language_syllabus` |
| Comprehension (Paper 2 Section B) | Word/phrase equivalents; factual content; inferences; sentiments/emotions/attitudes/tone; grammatical structures/functions in context; literary terms/expressions; recasting phrases/sentences into grammatical alternatives | covered | GST 101 reading/listening/interpretation/critical evaluation units; `eng_context_clues`; `eng_cloze_procedure`; `eng_word_choice_sense_relations`; `eng_waec_english_language_syllabus` |
| Summary (Paper 2 Section C) | Extract relevant information; summarize clearly and concisely; avoid repetition/redundancy; present summary of specific aspects/portions | covered | GST 101 note-taking/skimming/scanning; GST 102 M2U4/M2U5 summarising techniques; `eng_context_clues`; `eng_waec_english_language_syllabus` |
| Oral English / Listening Comprehension (Paper 3) | Consonants and clusters/contrasts; vowels, diphthongs, triphthongs; rhymes/rhyming contrasts; word stress and syllable structure; emphatic/contrastive stress and intonation patterns; dialogues and narratives; phonetic symbols/sound recognition as specified | covered | GST 102 M3 oral/sound units; `eng_phonetics_diphthongs_triphthongs`; `eng_phonetics_stress`; `eng_phonetics_intonation`; `eng_emphatic_contrastive_stress`; `eng_rhyme_in_english`; `eng_homonyms_homophones`; `eng_waec_english_language_syllabus` |

Notes: the WAEC syllabus concept explicitly records syllabus fields/objectives
(including lexis domains, idioms/collocations, figurative usage, structural
elements, and oral/listening features). Domain-specific vocabulary is supported
through GST vocabulary development, context/sense-relation concepts, and the
syllabus domain listing for in-context application and study.

## Status summary (current `audit-nonscience.json`)

| Subject | Level | Topics | Covered | Thin | No source |
|---|---|---:|---:|---:|---:|
| English | Foundational | 6 | 6 | 0 | 0 |
| English | JAMB | 3 | 3 | 0 | 0 |
| English | WAEC | 5 | 5 | 0 | 0 |
| Economics | JAMB | 23 | 7 | 15 | 1 |
| Accounting | JAMB | 18 | 13 | 5 | 0 |
| Commerce | JAMB | 16 | 9 | 7 | 0 |
| **Total** |  | **71** | **43** | **27** | **1** |

Inventory: 242 non-science concept files (`eng_*`/`eco_*`/`acc_*`/`bus_*`),
27,085 blocks. English inventory: 53 concept files (40 GST foundational units +
13 sourced supplements/syllabus concepts), all schema/consistency-valid in
local checks. All audit concept references resolve to existing files. The
largest revision summary observed is 924 bytes, well under the 16 KiB card
limit (`revision_summary` only; `deep_context` holds full sourced content).

## Topics with no source

| Subject | Topic | Missing material |
|---|---|---|
| Economics | Natural resources and the Nigerian economy | Petroleum, gold and timber; NNPC and OPEC; resource linkage effects |

## Thin topics and remaining gaps

English production JAMB/WAEC topics/subtopics are mapped as covered with sourced
concepts and the WAEC syllabus reference. Remaining non-English gaps:

| Subject | Topic | Still unsourced / thin |
|---|---|---|
| Economics | Methods and Tools of Economic Analysis | Measures of central tendency and dispersion, with merits and demerits |
| Economics | The Theory of Demand | Composite, derived, competitive and joint demand typology |
| Economics | The Theory of Supply | Joint, complementary, competitive and composite supply typology |
| Economics | The Theory of Production | Division of labour and isoquant-isocost producer equilibrium |
| Economics | Theory of Costs and Revenue | Revenue concepts in a dedicated treatment |
| Economics | Money and Inflation | Fisher quantity theory equation |
| Economics | Financial Institutions | Nigerian reforms and bank consolidation |
| Economics | Public Finance | Nigerian revenue allocation and resource control |
| Economics | Economic Growth and Development | Nigerian development planning |
| Economics | Industry and Industrialization | Industry location, localisation and industrialisation strategies |
| Economics | Business Organizations | Privatisation and commercialisation of public enterprises |
| Economics | Population | Age and sex structure, migration types, and the named regional cases |
| Economics | International Economic Organizations | ECOWAS, AU, OPEC, IMF and World Bank roles for Nigeria |
| Economics | Factors of Production and their Theories | Rewards to land, capital and entrepreneurship |
| Economics | Agriculture in Nigeria | Instability in agricultural income (causes, effects and solutions) |
| Accounting | Ethics in Accounting | The JAMB list of accountant qualities |
| Accounting | Cashbook | Columnar cashbooks and trade/cash discounts |
| Accounting | Control Accounts and Self-balancing Ledgers | Control accounts and self-balancing ledgers |
| Accounting | Manufacturing Accounts | The JAMB manufacturing-account layout |
| Accounting | Accounts of Not-For-Profit-Making Organisations | Receipts and payments, income and expenditure, and balance sheet preparation |
| Commerce | Occupation | Industrial, commercial and service occupation typology |
| Commerce | Trade | Export and import documents, customs procedures |
| Commerce | Purchase and Sale of Goods | Terms of trade such as CIF and FOB |
| Commerce | Aids-to-Trade | Transport, insurance, tourism and warehousing |
| Commerce | Trade Associations | Named Nigerian commodity associations and manufacturer associations |
| Commerce | Stock Exchange | Nigeria's second-tier securities market |
| Commerce | Legal Aspects of Business | Contract, agency, sale of goods and hire purchase law |

## Scope limits

- English now has Foundational, JAMB, and WAEC production-level mappings with
  sourced concepts and recorded provenance/licence status. Other non-science
  subjects remain primarily JAMB-mapped; WAEC lists beyond English are not
  comprehensively mapped yet.
- PDF/web-sourced ingestion captures text and inferred headings. It does not
  extract figures or tables from PDFs. PDF-sourced concepts may need a
  figure/table pass before strict greedy capture can be claimed for visuals.
- Concept `placements` arrays are still empty. They will be filled from audit
  mapping when concepts are attached to production topics.
- `data/` (including `data/concepts/`) remains gitignored local staging and was
  not committed.
- One JAMB economics topic remains `no_source`
  (`natural-resources-and-the-nigerian-economy`). `agriculture-in-nigeria` is
  `thin` (income instability not fully covered). Other thin Nigeria/exam-specific
  subtopics remain as listed above.
- Licence/status for NOUN GST/CRD, Pondicherry, VMOU, Raymond, Sharma, and
  compiled emphatic-stress web sources remains pending later review; URLs and
  locators are recorded in concept files and audit/docs.
