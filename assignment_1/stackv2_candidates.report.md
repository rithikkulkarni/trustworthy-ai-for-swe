# PII Detection Report

- Generated: 2026-09-04T01:30:50+00:00
- Scanned directory: `data\stackv2_sample`
- Files scanned: 3000
- Files flagged: 256
- Total candidates: 342

## Candidates by type

| Type | Count | Files |
| --- | --- | --- |
| name | 175 | 148 |
| email | 101 | 77 |
| username | 36 | 32 |
| ip_address | 28 | 23 |
| password | 1 | 1 |
| key | 1 | 1 |

## Candidates by detector rule

| Method | Count |
| --- | --- |
| regex:name:author_context | 175 |
| regex:email | 101 |
| regex:ipv4 | 28 |
| regex:username:author_context_handle | 24 |
| regex:username:assign | 12 |
| regex:password:assign | 1 |
| regex:key:google | 1 |

## LLM verification

- Model: `gemini-3.5-flash-lite`
- Candidates verified: 312
- Tokens: 23882 in / 15273 out
- Cost: $0.04535 total, $0.00015 per verified candidate
- Verdicts: 273 is_real_pii=true, 39 is_real_pii=false

## Flagged examples
(up to 8 per type; context is redacted, matched values are never printed here)

### name (175 candidates)

- `00007_8d38afc7a12d.java` line 3 — `regex:name:author_context`, llm_verdict=True (confidence=0.95)
- `00007_8d38afc7a12d.java` line 3 — `regex:name:author_context`, llm_verdict=True (confidence=0.95)
- `00010_db063401c88b.java` line 14 — `regex:name:author_context`, llm_verdict=True (confidence=0.95)
- `00019_85fcd4c29749.java` line 11 — `regex:name:author_context`, llm_verdict=True (confidence=0.95)
- `00047_19054b282c02.java` line 16 — `regex:name:author_context`, llm_verdict=True (confidence=0.95)
- `00049_64533b967458.java` line 10 — `regex:name:author_context`, llm_verdict=True (confidence=0.95)
- `00094_cbfda224c589.java` line 20 — `regex:name:author_context`, llm_verdict=True (confidence=0.95)
- `00096_719df7019123.java` line 6 — `regex:name:author_context`, llm_verdict=False (confidence=0.9)
- ... and 167 more

### email (101 candidates)

- `00013_795131938a44.java` line 81 — `regex:email`, llm_verdict=True (confidence=0.9)
- `00013_795131938a44.java` line 87 — `regex:email`, llm_verdict=True (confidence=0.9)
- `00033_4ed153e4d904.java` line 40 — `regex:email`, llm_verdict=True (confidence=0.9)
- `00033_4ed153e4d904.java` line 78 — `regex:email`, llm_verdict=False (confidence=0.9)
- `00055_19fd5fe4a6a8.java` line 7 — `regex:email`, llm_verdict=True (confidence=0.9)
- `00094_cbfda224c589.java` line 21 — `regex:email`, llm_verdict=True (confidence=0.9)
- `00101_0b03c992bc9c.java` line 70 — `regex:email`, llm_verdict=True (confidence=0.95)
- `00126_946e34afa3a1.java` line 12 — `regex:email`, llm_verdict=True (confidence=0.9)
- ... and 93 more

### username (36 candidates)

- `00009_0a5750dd789d.java` line 10 — `regex:username:author_context_handle`, llm_verdict=True (confidence=0.8)
- `00023_b48d3764de48.java` line 29 — `regex:username:author_context_handle`, llm_verdict=True (confidence=0.8)
- `00033_4ed153e4d904.java` line 49 — `regex:username:assign`, llm_verdict=False (confidence=0.85)
- `00127_02f7aa51e3d4.java` line 79 — `regex:username:assign`, llm_verdict=False (confidence=0.9)
- `00148_637f4601a9e9.java` line 15 — `regex:username:author_context_handle`, llm_verdict=True (confidence=0.85)
- `00163_54a8b3862b6f.java` line 20 — `regex:username:author_context_handle`, llm_verdict=True (confidence=0.7)
- `00361_be0e3dbbd224.java` line 35 — `regex:username:author_context_handle`, llm_verdict=True (confidence=0.85)
- `00512_a956a20f944b.java` line 29 — `regex:username:assign`, llm_verdict=False (confidence=0.8)
- ... and 28 more

### ip_address (28 candidates)

- `00192_d1f3b7d9da9a.java` line 212 — `regex:ipv4`
- `00366_b3ae29d68b13.java` line 21 — `regex:ipv4`
- `00470_711f14d4e088.java` line 30 — `regex:ipv4`
- `00551_a00ca3a90551.java` line 60 — `regex:ipv4`
- `00612_b9fdb475d881.java` line 102 — `regex:ipv4`
- `00691_5c0381d1008a.java` line 225 — `regex:ipv4`
- `00790_6577358d6105.java` line 53 — `regex:ipv4`
- `00826_19f4a01ecd00.java` line 77 — `regex:ipv4`
- ... and 20 more

### password (1 candidates)

- `01753_3496665f69da.java` line 29 — `regex:password:assign`

### key (1 candidates)

- `02720_467e0c30f52b.java` line 10 — `regex:key:google`
