# Golden content benchmark

This directory defines the representative rows used to compare media and
content providers. The images stay in the bank media store. They are not copied
into the source repository.

Each manifest entry needs a real `asset_id` and a manually checked expected
observation before it becomes a media gold case. The current labels verify only
the image itself. The complete case remains unverified until its source
question, catalogue placement, canonical answer, and explanation requirements
are checked. A provider result is evidence for comparison, not the expected
answer.

Required observations include:

- text fragments that must be readable;
- labels or values that must be preserved;
- whether empty OCR is expected;
- visual facts the description must report;
- the expected topic and subtopic;
- the canonical answer and explanation requirements.

Do not mark an entry as verified from an AI response alone. A person must check
the source image and the exam content first.

Check the manifest without contacting a provider:

```bash
python scripts/check_benchmark_manifest.py
```

Check the local media files as well:

```bash
python scripts/run_media_benchmark.py
```

The media store is local and ignored by Git, so this command is expected to
report missing cases on a fresh checkout until the bank media store is present.

Score an existing OCR result without making another provider request:

```bash
python scripts/score_ocr_benchmark.py /path/to/ocr-results.json
```
