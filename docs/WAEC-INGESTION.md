# WAEC ingestion contract

Status: active working contract

This document defines how UTME Lab handles WAEC content before the bank gains
full multi-country ingestion support.

## Country scope

WAEC covers five member countries:

```text
NG  Nigeria
GH  Ghana
SL  Sierra Leone
GM  The Gambia
LR  Liberia
```

The first ingestion scope is `NG` only. MySchool is a Nigerian source, so its
WAEC questions must not be treated as universal WAEC questions.

Every WAEC staging row must eventually carry a country. A row without a
country is not ready for promotion.

## Source scope

The MySchool adapter supplies WAEC objective questions. It does not represent
the complete WAEC examination package. Essay, practical, oral, and other
paper-specific material needs a separate source or adapter.

The source request year is not trusted by itself. The adapter must read and
validate the year attached to each returned question before staging it.

## Syllabus scope

The production catalog remains the authority for WAEC subjects, topics,
subtopics, objectives, and country scope.

Country-scoped syllabus topics must be selected with the same country as the
staged question. The bank must not tag a Nigerian row against an unscoped
multi-country catalog snapshot when country-specific topics exist.

## Catalog readiness

Being present in the MySchool subject map does not make a subject ready for
ingestion. The production subject, topics, and subtopics must exist first.
The repository currently has WAEC syllabus inputs for:

```text
agricultural-science
biology
chemistry
christian-religious-studies
civic-education
economics
english-language
financial-accounting
geography
further-mathematics
government
nigerian-history
insurance
marketing
general-mathematics
physical-education
physics
```

The other mapped subjects remain source-mapped but catalog-pending. They must
stay out of a production scrape until their production catalog is confirmed.
An empty catalog is a block, not a reason to invent topic placement.

The archived WAEC syllabus model records these common section rules:

- Section A applies to all WAEC member countries.
- Section B applies to Ghana.
- Section C applies to Nigeria, Sierra Leone, The Gambia, and Liberia.

Those rules are historical implementation guidance, not a substitute for
checking the production catalog and the official syllabus source.

## Subject mapping

The source slug and the production catalog slug are separate values. The map
must preserve both and must use the exact MySchool slug. Examples include:

```text
Accounts - Principles of Accounts -> accounts-principles-of-accounts
Christian Religious Knowledge    -> christian-religious-knowledge-crk
Islamic Religious Knowledge      -> islamic-religious-knowledge-irk
Fine Arts                         -> fine-arts
```

Subjects with no returned WAEC rows remain mapped only when the source page is
known and the absence is recorded. A missing source page must not be silently
converted into an invented slug.

## Promotion rule

A WAEC row may move beyond staging only when all of these are true:

- country is `NG` for the current ingestion phase;
- exam, subject, and year match the source row;
- the row passes the mechanical gate;
- the question is placed against the country-aware production catalog;
- its answer and explanation are reviewed;
- its media and passage references are resolvable;
- it is not already present in production or the bank.

## Expansion rule

Ghana, Sierra Leone, The Gambia, and Liberia become separate ingestion scopes.
They must not be enabled by changing a default. Each country needs a source
decision, subject coverage check, syllabus check, and bounded dry run first.
