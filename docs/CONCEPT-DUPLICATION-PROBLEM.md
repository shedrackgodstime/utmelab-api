# Concept Duplication Across Exams Problem

Status: Problem statement for review
Date: 2026-11-09

## Current design

Study notes are stored as `topic_notes` rows keyed by exam, subject, topic slug and optional subtopic slug. Each row carries its own identifier, title, key takeaway, sections, worked examples, formulas, active recall checks, examiner traps, sources, linked question IDs, and content hash. The API resolves a request for a topic or subtopic through the syllabus owner for the requested exam and subject, then returns the matching note.

Production currently holds 26 notes across four exam and subject pairs:

- JAMB mathematics: 5
- JAMB physics: 2
- JAMB use-of-english: 12
- WAEC english-language: 7

All 26 notes are text and formula based. None embeds an image.

## Problem

The same underlying concept appears in multiple exam syllabuses under different subject slugs. There is no shared concept identity in storage. Each placement holds a separate copy of the concept.

Trigonometry is one instance: right-triangle definitions, special-angle values, and the identity sin squared plus cos squared equals one are the same mathematical content whether they sit under JAMB mathematics, WAEC general mathematics, or NECO mathematics. Motion, vectors, and measurement show the same pattern: the definition, equations, and standard examples transfer across exams even though the rows are separate.

Because each row is stored independently, a change to the shared concept has to be repeated in every duplicate row. Duplicates can drift in wording, examples, formula choice, figure inclusion, source attribution, and content hash while describing the same idea.

## Scope of the problem

The current syllabus-owner sharing covers a NECO subject that points at a WAEC syllabus subject. It does not provide a shared representation for concepts that belong to different syllabus owners, such as JAMB mathematics and WAEC general mathematics.

Duplication multiplies with placements rather than with distinct concepts. Content size grows with the number of exam placements, not the number of distinct ideas covered. Coverage gaps also differ by exam even where the underlying concepts overlap: JAMB mathematics holds 5 of 77 subtopics, WAEC english-language holds 7 of 60 subtopics, and JAMB use-of-english holds 12 of 12 subtopics.

Source quality and freshness are controlled per row. Two rows describing the same concept can cite different sources for the same claim. A figure or example added for a shared concept would need to be added once per placement, with separate storage and separate records.

## Open questions for review

- How should a concept shared across syllabus owners be represented in storage and in the API?
- How should exam-specific variation be represented alongside shared content?
- How should coverage be counted when the same concept serves multiple exams?
