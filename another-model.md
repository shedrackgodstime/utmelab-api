do we want to work on the contents, or we should look for some waec/neco questions?  we need atleast 100           ┃  questions on each of those....  or we should start filling our db(filling our db will not be done bash             ┃  processing... it one questions/novel/**" at a time,reviwing each properly checking criterial b4 each).....         ┃  those are what we should pick from....


 Good question — and the numbers push back hard on one of the three. Here's what I measured.

     The WAEC/NECO option is greenfield, not a gap
                                                                                                                           The bank holds 2 non-JAMB rows total: one animal-husbandry (WAEC) and one exam-less civic-education fixture           that is deliberately withheld (D21/D58). "100 each" on the 9 subjects D8 names is ~900 rows from zero.                                                                                                                                      Two things make it much bigger than it sounds:                                                                                                                                                                                              - The harvester cannot supply any of it. config/harvest.json explicitly skips 12 NECO subjects with the reason          "the source carries no JAMB paper, and importing one as JAMB would file the wrong exam." So this isn't                another run of the pipeline — it's a second source (different site, different paper structure, WAEC/NECO              format), then verifying ~900 rows we can't check against our own summaries.                                         - Everything downstream is JAMB-shaped. D63's blueprints are JAMB-only, D41's paper scheme is JAMB's 40-per-            subject, readiness = blueprint × coverage. WAEC/NECO needs scheme + blueprint work before the first question.  
     And it lands on top of the constraint you already have: 2,144 rows already unverified, 2,144 untagged. Adding
     900 unverifiable rows multiplies the exact problem, it doesn't solve it. JAMB is the market D1/D2 already
     chose; the binding constraint on a sellable paper is 180 verified rows per subject and English holds 103.

     Two live defects in the WAEC/NECO story, worth fixing regardless

     While checking this I found drift the repo's own rules should have caught:

     1. D8 is stale. It names 9 subjects as exam: "" — "not JAMB, exam not yet decided, we do not guess" — but data/
        subjects.json has already assigned them WAEC/NECO. Six of them (financial-accounting, general-mathematics,
        visual-arts, english-language) aren't even in D8's list. That's a guessed exam reaching a consumer as fact:
        the same failure D47 (fake year) and D50 (fake weight) exist to prevent, and D7 says no data change without
        a D-row.
     2. The "831 questions already paid for" line in §3.2b is not true of this bank. I walked the history: non-JAMB
        never exceeded 2 rows in data/questions.json at any commit. 831 was measured from the parent DB. It reads
        as "we already hold the WAEC inventory" — which would change your decision — and it isn't true.

     My pick: contents — starting with the 78

     Not because the others are worthless, but because it's the only one that moves a customer-facing number. Right
     now the 78 are served as unanswerable questions: the stem says "the underlined word" and the row carries
     nothing. That's worse than an empty bank — it's a wrong-looking product.

     The shape landed in P1, the worksheet tool already emits all 78 with candidates, and apply writes validated
     Underline marks. Zero marks exist. It's pure data, it's checkable by a human with an ear, and it clears 78 of
     the 102 quarantine findings. Then English verification in ~50-row batches through review.py, which now appends
     D62 log rows instead of flipping a bool.

     On "one at a time, checking criteria" — yes, but not for the DB

     Your instinct is exactly right, and I'd redirect where it lands.

     For content and verification, it's the whole game. D62's point is that one human, one row, one real check at a
     time is the only thing that makes verified mean anything. That's the scarce resource and it should be spent
     there.

     For the DB it would be a mistake. D64 pins the DB as a mechanical mirror of the same structs (R1), hash               maintained on every write (R6), each phase landing only with a parity proof (R8). Row-by-row human review             there buys nothing — there is no judgement in it, and "parity" has no meaning one row at a time. That's a bulk
     script plus a diff report.                                                                                                                                                                                                                  The one DB step that genuinely deserves hand-care is Phase 1: verifications — 188 rows, the highest-churn
     table, and it needs seeding rules agreed before it exists. If you want a small careful DB move, that's it.       
     So: contents (78 underlines → English verification), with the WAEC/NECO decision written down as parked with
     its trigger, and the D8/subjects.json drift corrected. If you'd rather chase WAEC/NECO now, the honest first          step is finding a source that carries those papers — that's the whole question, and it decides everything
     after it.                                                                                                        
     Which way?
