# Evidence Yield Audit Report (ΔE = Evidence_after - Evidence_before)

Total session turns analyzed: **23**

## Summary by Question Move / Category

| Move / Target | n | Avg ΔE (Evidence Yield) | Max ΔE | Yield Quality |
|---|---|---|---|---|
| `OUTCOME` | 1 | **10.00** | 10 | HIGH (≥ 3.0) |
| `METRIC_DEFINITION` | 3 | **6.33** | 8 | HIGH (≥ 3.0) |
| `PERTURB` | 2 | **5.50** | 10 | HIGH (≥ 3.0) |
| `FAILURE` | 4 | **4.00** | 6 | HIGH (≥ 3.0) |
| `PEOPLE` | 3 | **4.00** | 7 | HIGH (≥ 3.0) |
| `OPERATING_CONTEXT` | 6 | **3.17** | 7 | HIGH (≥ 3.0) |
| `OPERATIONAL` | 3 | **1.67** | 3 | MODERATE (1.5 - 2.9) |
| `INCIDENT` | 1 | **1.00** | 1 | LOW (< 1.5) |

## Turn-by-Turn Evidence Breakdown

| Candidate | Turn | Move | Question | E_before | E_after | ΔE | Dimension Growth |
|---|---|---|---|---|---|---|---|
| Arjun Mehta | Q1 | `OPERATING_CONTEXT` | 'When you were working on the team, what did you lo...' | 0 | 3 | **+3** | SPECIFICITY:+20, PROCESS:+38, METRIC_OWNERSHIP:+20, EXECUTION:+25 |
| Arjun Mehta | Q2 | `OPERATIONAL` | 'What interface boundary or handoff contract did yo...' | 3 | 3 | **+0** | none |
| Arjun Mehta | Q3 | `METRIC_DEFINITION` | 'You mentioned SLA attainment. How was SLA attainme...' | 0 | 6 | **+6** | SPECIFICITY:+60, PROCESS:+31, METRIC_OWNERSHIP:+100, KNOWLEDGE:+33, EXECUTION:+40 |
| Arjun Mehta | Q4 | `OUTCOME` | 'What specific anomaly on that dashboard triggered ...' | 6 | 16 | **+10** | SPECIFICITY:+40, PROCESS:+50, TOOL_FAMILIARITY:+50, EXECUTION:+48 |
| Arjun Mehta | Q5 | `FAILURE` | 'Tell me about a time the script standardisation di...' | 0 | 6 | **+6** | SPECIFICITY:+60, PROCESS:+38, METRIC_OWNERSHIP:+80, TOOL_FAMILIARITY:+5, KNOWLEDGE:+17, EXECUTION:+40 |
| Arjun Mehta | Q6 | `PEOPLE` | 'Who else was close to the script standardisation, ...' | 6 | 13 | **+7** | SPECIFICITY:+40, PROCESS:+50, METRIC_OWNERSHIP:+20, CAUSAL_REASONING:+40, EXECUTION:+60 |
| Maya Krishnan | Q1 | `METRIC_DEFINITION` | 'You mentioned activation. How was activation actua...' | 0 | 5 | **+5** | SPECIFICITY:+60, PROCESS:+31, METRIC_OWNERSHIP:+45, EXECUTION:+40 |
| Maya Krishnan | Q2 | `FAILURE` | 'Tell me about a time the first-run flow did not go...' | 5 | 9 | **+4** | SPECIFICITY:+20, PROCESS:+57, AUTHENTICITY:+33, EXECUTION:+50, PROBLEM_SOLVING:+33 |
| Maya Krishnan | Q3 | `OPERATING_CONTEXT` | 'When you were working on the user interviews, what...' | 0 | 3 | **+3** | SPECIFICITY:+60, PROCESS:+12, METRIC_OWNERSHIP:+15, EXECUTION:+8 |
| Maya Krishnan | Q4 | `PEOPLE` | 'Who else was close to the user interviews, and wha...' | 3 | 8 | **+5** | SPECIFICITY:+40, PROCESS:+44, CAUSAL_REASONING:+20, EXECUTION:+24 |
| Maya Krishnan | Q5 | `PERTURB` | 'Suppose you had taken on the first-run flow instea...' | 0 | 10 | **+10** | SPECIFICITY:+100, PROCESS:+69, METRIC_OWNERSHIP:+45, CAUSAL_REASONING:+20, EXECUTION:+72 |
| Maya Krishnan | Q6 | `OPERATING_CONTEXT` | 'When you were working on the experiments against a...' | 10 | 13 | **+3** | PROCESS:+31, CAUSAL_REASONING:+50, EXECUTION:+26, PROBLEM_SOLVING:+33, ADAPTABILITY:+50 |
| Priya Raghavan | Q1 | `OPERATING_CONTEXT` | 'When you were working on the team, what did you lo...' | 0 | 7 | **+7** | SPECIFICITY:+80, PROCESS:+81, METRIC_OWNERSHIP:+35, EXECUTION:+57 |
| Priya Raghavan | Q2 | `OPERATIONAL` | 'What interface boundary or handoff contract did yo...' | 7 | 10 | **+3** | SPECIFICITY:+20, PROCESS:+19, EXECUTION:+25 |
| Priya Raghavan | Q3 | `METRIC_DEFINITION` | 'You mentioned CSAT. How was CSAT actually worked o...' | 0 | 8 | **+8** | SPECIFICITY:+80, PROCESS:+44, METRIC_OWNERSHIP:+45, CAUSAL_REASONING:+20, EXECUTION:+48 |
| Priya Raghavan | Q4 | `FAILURE` | 'Tell me about a time the escalation workflow did n...' | 8 | 12 | **+4** | SPECIFICITY:+20, PROCESS:+25, TOOL_FAMILIARITY:+5, EXECUTION:+27 |
| Priya Raghavan | Q5 | `PEOPLE` | 'Who else was close to the call opening scripts, an...' | 0 | 0 | **+0** | none |
| Rohit Verma | Q1 | `OPERATING_CONTEXT` | 'When you were working on the team, what did you lo...' | 0 | 3 | **+3** | SPECIFICITY:+40, PROCESS:+6, METRIC_OWNERSHIP:+35, EXECUTION:+8 |
| Rohit Verma | Q2 | `OPERATIONAL` | 'What interface boundary or handoff contract did yo...' | 3 | 5 | **+2** | SPECIFICITY:+20, PROCESS:+32, EXECUTION:+24 |
| Rohit Verma | Q3 | `FAILURE` | 'Tell me about a time the % improvement did not go ...' | 0 | 2 | **+2** | SPECIFICITY:+20, PROCESS:+31, EXECUTION:+25 |
| Rohit Verma | Q4 | `INCIDENT` | 'What specific constraint or operational bottleneck...' | 2 | 3 | **+1** | PROCESS:+25, EXECUTION:+25 |
| Rohit Verma | Q5 | `PERTURB` | 'Suppose you had taken on the team instead, with th...' | 0 | 1 | **+1** | CAUSAL_REASONING:+50, PROBLEM_SOLVING:+33, ADAPTABILITY:+50 |
| Rohit Verma | Q6 | `OPERATING_CONTEXT` | 'When you were working on the advanced process opti...' | 1 | 1 | **+0** | none |
