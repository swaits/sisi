researched 2026-11-24 — baseline ranking of models (by class, then score descending; score is vals.ai Terminal-Bench 4.0 %, blank if unranked)

| model | maker | class | score | released | list price | benchmarks | good at, bad at |
|---|---|---|---|---|---|---|---|
| muse-ember-1.0 | meta | routine | 39.39 | | | vals TB4 39.39% ($0.22/test) | good: running and checking (medium/high effort). bad: building, research |
| glm-5.3-flash | zhipu | routine | 37.37 | | $0.2375/M blended ($0.15 in/$0.50 out) | vals TB4 37.37% ($1.22/test) | good: cheap simple edits and reads. bad: tasks needing judgement |
| claude-haiku-5-5 | anthropic | routine | 36.36 | | $0.20/M blended ($0.10 in/$0.50 out <=100k; $0.50/$2.50 >100k) | vals TB4 36.36% ($3.12/test); AA index 36 | good: fast inventory, classification, reads. bad: complex agentic coding, exhaustive search |
| deepseek-v4.1-flash | deepseek | routine | 31.82 | | $0.2625/M blended ($0.15 in/$0.60 out) | vals TB4 31.82% (max effort; 19.70% default; $0.54/test); AA index 33 | good: cheap edits, reads needing reasoning. bad: sometimes states things that are not true; maker claims higher tier unverified |
| minimax-m3.1-flash | minimax | routine | 25.25 | | $0.2625/M blended ($0.15 in/$0.60 out) | vals TB4 25.25% ($0.73/test) | good: cheap routine multimodal coding. bad: weaker than Haiku 5.5 and GLM 5.3 Flash on terminal tasks |
| muse-spark-1.3 | meta | routine | 24.75 | | | vals TB4 24.75% (max effort), 10.61% (default) | good: running and checking (medium/high effort). bad: open-ended web search, building, research |
| mimo-v2.6-flash | xiaomi | routine | 24.24 | | $0.175/M blended ($0.14 in/$0.28 out) | vals TB4 24.24% ($0.21/test) | good: cheapest bulk inventory. bad: weak on agentic tasks |
| hy4-flash-free | tencent | routine | 15.15 | | free | vals TB4 15.15% ($0.10/test) | good: everyday agent tasks. bad: agentic coding |
| gpt-6-luna | openai | routine | 13.64 | | $0.20/M blended ($0.10 in/$0.50 out) | vals TB4 13.64% ($0.35/test) | good: very cheap simple text work. bad: agentic coding |
| beam-free | reflection | routine | 4.04 | | free | maker SWE-bench Verified 81.6%; vals TB4 4.04% | good: patch-style coding. bad: long agentic terminal tasks; text input only |
| hungerg-free | unknown | routine | | 2026-11-24 | free | vals TB4 not found | good: reasoning with image/video input. bad: unverified on benchmarks |
| qwen3.8-flash | alibaba | routine | | | $0.23/M blended ($0.15 in/$0.47 out) | vals TB4 not found | good: cheap routine work, visual/document reasoning (maker). bad: no independent benchmark yet |
| claude-sonnet-5-5 | anthropic | ordinary | 64.14 | | $4.00/M blended ($2.00 in/$10.00 out, cache $0.10) | vals TB4 64.14% ($10.75/test); maker TB4 70.6 | good: edit, debug, review, research, multi-file implementation. bad: costly in long-lived threads |
| gemini-4-carbon | google | ordinary | 63.13 | 2026-10-28 (AA) / 2026-11-10 (Vals) | $4.00/M blended ($2.00 in/$10.00 out) through 2026-11-30; $8.00/M ($4.00/$20.00, cache $0.20) from 2026-12-01 | vals TB4 63.13% ($7.45/test); AA index 60 (high), 58 (medium), 54 (low) | good: top Gemini 4 on vals TB4 (default thought_level high). bad: dearer per token than Neon from 2026-12-01 for lower AA index than Neon xhigh |
| gemini-4-neon | google | ordinary | 61.62 | 2026-11-18 | $6.00/M blended ($3.00 in/$15.00 out, cache $0.15) | vals TB4 61.62% ($6.42/test); AA index 61 (xhigh) | good: lowest per-test cost among Gemini 4 models (thought_level medium/high). bad: xhigh raises token cost |
| muse-wonder-full-1.0 | meta | ordinary | 58.08 | | no self-serve API | vals TB4 58.08% ($10.53/test) | good: multi-file work and review (medium/high effort). bad: slow; independent benchmarks put it at Sonnet level rather than Opus |
| gemini-4-hydrogen | google | ordinary | 54.04 | 2026-11-12 | $3.00/M blended ($1.50 in/$7.50 out, cache $0.075) | vals TB4 54.04% ($7.56/test); Vals Index 67.07%; AA not found | good: cheapest Gemini 4 at ordinary strength (default thought_level medium). bad: weakest Gemini 4 on agentic terminal work |
| muse-wonder-1.0 | meta | ordinary | 49.49 | | $8.00/M blended ($4.00 in/$20.00 out) | vals TB4 49.49% ($14.66/test) | good: research, reads, clear-spec implementation (medium/high effort). bad: slow, lower TB4 than peers |
| glm-5.4 | zhipu | ordinary | | 2026-11-23 | | King Bench 4 55.3%; vals TB4/AA not found | good: tool-using edit-and-test tasks, code review. bad: hard multi-file work unproven |
| claude-opus-5-5 | anthropic | hard | 65.15 | | $8.00/M blended ($4.00 in/$20.00 out, cache $0.20) | vals TB4 65.15% ($12.04/test); maker TB4 66.4 | good: tied first on vals TB4; long sprawling jobs, migrations, audits (maker), hard review. bad: dearest tier |
