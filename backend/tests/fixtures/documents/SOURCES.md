# Document OCR fixture sources

All images are synthetically generated (not scanned/sourced from the web), created by
rendering plain text with PIL onto a white background using a Windows system font
(`C:\Windows\Fonts\arial.ttf`). Unlike the attendance-CV face fixtures, there's no
public-domain-photo sourcing question here - these are fully self-authored, so there's
no attribution needed, but the generation approach is documented for reproducibility
and honesty about what they are (clean synthetic renders, not real scanned forms).

Chosen over sourcing real scanned document images because: (1) it gives deterministic,
known ground-truth text so tests can assert exact extraction correctness rather than
"something roughly plausible", and (2) it avoids the licensing/attribution questions
real document images would raise even from ostensibly public-domain sources.

- `admission_form.png` — clean render of an admission-form-style layout (applicant
  name, DOB, guardian name/phone). Expected to OCR near-perfectly.
- `marksheet.png` — clean render of a marksheet-style layout (student name, roll
  number, total marks, percentage). Expected to OCR near-perfectly.
- `id_proof.png` — clean render of an ID-proof-style layout (name, ID number, DOB).
  Expected to OCR near-perfectly.
- `low_confidence_admission_form.png` — same admission-form content, deliberately
  degraded (small font, Gaussian blur, salt noise) to produce genuinely low
  Tesseract word-confidence output, for testing the is_low_confidence flagging and
  manual-correction flow. OCR output on this one is intentionally imperfect (e.g.
  "Applicant Name" misreads as "Applicant Nairie") - that's the point, not a bug in
  the fixture.

Regenerate via the snippet in this repo's OCR session notes if these ever need
tweaking - trivial to reproduce, nothing external to re-download.
