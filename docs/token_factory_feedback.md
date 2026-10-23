# Draft feedback: Nebius Token Factory and NVIDIA Nemotron

_Draft for the submission form. Edit with your own experience before submitting._

## What worked well
- OpenAI-compatible API: the standard `openai` Python package worked by changing only the base URL and key.
- Nemotron 3 Super extracted all 5 policy rules with verbatim, correctly paged quotes on the first real call (~11 s).
- Clear model catalog with context length and precision for each model.

## Friction we hit
- The catalog lists near-identical names with different deployment types (for example
  `Nemotron-3-Nano-30B-A3B` as Public and `NVIDIA-Nemotron-3-Nano-30B-A3B` as Dedicated). We picked the
  Dedicated one by mistake; a clearer label or a warning on the model ID would help.
- The display name in the catalog is not always the exact API model ID; showing a copy button for the ID
  next to each row would save a round trip.
- The $1 trial credit is tight for iterating on prompts; a note pointing hackathon users to the Builder
  Program credits would help.

## Suggestions
- A built-in JSON / structured-output mode documented per model.
- Per-request cost shown in the dashboard to help choose between Nano, Super and Ultra.
