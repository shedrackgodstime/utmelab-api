#!/usr/bin/env python3
"""
Automated verification for WAEC questions using opencode CLI with free models.
No API key required - uses OpenCode Zen free models.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class Question:
    id: str
    text: str
    options: list[dict]
    answer: str
    explanation: Optional[dict] = None
    subject: str = ""
    exam: str = ""
    year: int = 0


@dataclass
class VerificationResult:
    question_id: str
    answer_correct: bool
    explanation_quality: str  # "good", "partial", "poor", "missing"
    confidence: float
    reasoning: str


class OpenCodeVerifier:
    def __init__(self, model: str = "opencode/zen-default"):
        self.model = model

    async def verify_question(self, question: Question) -> VerificationResult:
        """Verify a single question using opencode CLI with free models."""
        
        # Build the prompt
        prompt = self._build_verification_prompt(question)
        
        # Run opencode CLI
        result = await self._run_opencode(prompt)
        return self._parse_response(question.id, result)

    def _build_verification_prompt(self, question: Question) -> str:
        # Format options
        options_text = ""
        for opt in question.options:
            options_text += f"  {opt['id']}) {opt['text']['text']}\n"
        
        # Format explanation if present
        exp_text = "MISSING"
        if question.explanation:
            kp = question.explanation.get('key_point', {}).get('text', '')
            body = question.explanation.get('body', {}).get('text', '')
            trap = question.explanation.get('trap', {}).get('text', '')
            exp_text = f"Key point: {kp}\nBody: {body}\nTrap: {trap}"
        
        prompt = f"""You are an expert WAEC examiner. Evaluate this question's answer and explanation.

QUESTION:
Subject: {question.subject} ({question.exam} {question.year})
Question: {question['text']['text']}

OPTIONS:
{options_text}

CORRECT ANSWER: {question['answer']}

EXPLANATION PROVIDED:
{exp_text}

EVALUATION CRITERIA:
1. ANSWER CORRECTNESS: Does the provided answer match the correct answer?
2. EXPLANATION QUALITY: Rate the explanation as GOOD, PARTIAL, POOR, or MISSING:
   - GOOD: Key point correct, body explains reasoning, trap identifies distractors
   - PARTIAL: Key point mostly correct, body partially explains, trap partial
   - POOR: Key point wrong/missing, body incorrect/vague, trap missing/wrong
   - MISSING: No explanation provided
3. CONFIDENCE: Your confidence in this evaluation (0.0-1.0)

OUTPUT FORMAT (JSON only):
{{
  "answer_correct": true/false,
  "explanation_quality": "GOOD|PARTIAL|POOR|MISSING",
  "confidence": 0.0-1.0,
  "reasoning": "Brief explanation of your evaluation"
}}"""

        return prompt

    async def _run_opencode(self, prompt: str) -> str:
        """Run opencode CLI with the prompt."""
        # Write prompt to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write(prompt)
            prompt_file = f.name

        try:
            # Run opencode with the prompt
            # Using --model flag for free models
            cmd = [
                "opencode", "run",
                "--model", self.model,
                "-p", prompt
            ]
            
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            
            stdout, stderr = await proc.communicate()
            
            if proc.returncode != 0:
                raise RuntimeError(f"opencode failed: {stderr.decode()}")
            
            return stdout.decode()
            
        finally:
            os.unlink(prompt_file)

    def _parse_response(self, question_id: str, response_text: str) -> VerificationResult:
        try:
            # Extract JSON from response
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if not json_match:
                raise ValueError("No JSON found in response")
            
            data = json.loads(json_match.group())
            return VerificationResult(
                question_id=question_id,
                answer_correct=data["answer_correct"],
                explanation_quality=data["explanation_quality"],
                confidence=data["confidence"],
                reasoning=data["reasoning"],
            )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            return VerificationResult(
                question_id=question_id,
                answer_correct=False,
                explanation_quality="POOR",
                confidence=0.0,
                reasoning=f"Failed to parse LLM response: {e}",
            )


def load_questions(data_dir: Path) -> list[Question]:
    """Load questions from WAEC data directory."""
    questions_path = data_dir / "questions.json"
    with open(questions_path) as f:
        data = json.load(f)
    
    questions = []
    for q in data:
        questions.append(Question(
            id=q["id"],
            text=q["text"],
            options=q["options"],
            answer=q["answer"],
            explanation=q.get("explanation"),
            subject=q["subject"],
            exam=q["exam"],
            year=q["year"],
        ))
    return questions


def load_verifications(data_dir: Path) -> dict:
    """Load existing verifications."""
    path = data_dir / "verifications.json"
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def save_verifications(data_dir: Path, verifications: dict):
    path = data_dir / "verifications.json"
    with open(path, "w") as f:
        json.dump(verifications, f, indent=2)


async def main():
    parser = argparse.ArgumentParser(description="Auto-verify WAEC questions using opencode free models")
    parser.add_argument("--subject", help="Subject to verify (e.g., economics)")
    parser.add_argument("--exam", default="WAEC", help="Exam code")
    parser.add_argument("--limit", type=int, default=20, help="Max questions to verify")
    parser.add_argument("--data-dir", default="data/waec", help="Data directory")
    parser.add_argument("--model", default="opencode/zen-default", help="opencode model (free models: opencode/zen-default, opencode/zen-advanced, opencode/zen-fast)")
    parser.add_argument("--threshold", type=float, default=0.8, help="Min confidence to auto-accept")
    parser.add_argument("--dry-run", action="store_true", help="Don't save results")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    questions = load_questions(data_dir)
    
    # Filter questions
    verifications = {}
    verifications_path = data_dir / "verifications.json"
    if Path("data/waec/verifications.json").exists():
        with open("data/waec/verifications.json") as f:
            verifications = json.load(f)
    
    verified_ids = {v["question_id"] for v in verifications}
    
    filtered = [
        q for q in questions
        if q.exam == args.exam and q.subject == args.subject
        and q.explanation is not None
        and q.id not in verified_ids
    ]
    
    if args.limit:
        filtered = filtered[:args.limit]

    if not filtered:
        print("No unverified questions found")
        return

    print(f"Verifying {len(filtered)} questions for {args.exam} {args.subject}...")
    print(f"Model: {args.model} (free model)")

    verifier = OpenCodeVerifier(model=args.model)
    verifications = {}
    stats = {"good": 0, "partial": 0, "poor": 0, "missing": 0, "answer_wrong": 0}

    try:
        for i, question in enumerate(filtered, 1):
            print(f"  [{i}/{len(filtered)}] {question.id}...", end=" ", flush=True)
            
            result = await verifier.verify_question(question)
            
            # Track stats
            if not result.answer_correct:
                stats["answer_wrong"] += 1
            else:
                stats[result.explanation_quality.lower()] += 1
            
            print(f"  Answer: {'✓' if result.answer_correct else '✗'} | "
                  f"Quality: {result.explanation_quality} | "
                  f"Confidence: {result.confidence:.2f}")

            # Auto-accept if confidence high and quality good
            if (result.confidence >= args.threshold and 
                result.answer_correct and 
                result.explanation_quality in ("GOOD", "PARTIAL")):
                
                verifications[question.id] = {
                    "id": f"v_{question.id}_{len(json.loads(open('data/waec/verifications.json').read())) + 1:04d}",
                    "question_id": question.id,
                    "kind": "auto",
                    "verdict": "pass",
                    "scope": ["answer", "explanation"],
                    "verifier": f"auto:opencode-free",
                    "detail": result.reasoning,
                    "content_hash": "",
                    "created_at": datetime.datetime.now(
                        datetime.timezone.utc
                    ).strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
                print("  → AUTO-VERIFIED")
            else:
                print("  → NEEDS MANUAL REVIEW")

    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)

    # Save verifications
    verifications_path = Path("data/waec/verifications.json")
    with open(verifications_path, "w") as f:
        json.dump(verifications, f, indent=2)
    
    print(f"\nSaved verifications to {verifications_path}")
    print(f"\nStats: {stats}")


if __name__ == "__main__":
    asyncio.run(main())