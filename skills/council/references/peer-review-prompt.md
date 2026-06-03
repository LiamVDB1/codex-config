# Peer-review prompt template (Round 2)

The lead agent substitutes `{{QUESTION}}`, `{{CONTEXT}}`, and `{{LETTERED_RESPONSES}}` before sending this to each of the five role agents.

`{{LETTERED_RESPONSES}}` is the five Round-1 responses concatenated in letter order (A through E), each preceded by a heading like `### Response A` and the full response body. No role labels, no model labels.

Every reviewer receives the same lettered set. Anonymity is preserved by the shuffle alone.

---

```
You previously gave one of several independent answers to the question below as part of a five-person decision council. Four other advisors gave their own answers. The five responses are shown here anonymized as letters A–E. Your own answer is somewhere in this set.

You are now reviewing the council's work. Do not try to identify who wrote what. Refer to responses only by letter. If you recognize one as your own, do not say so — evaluate it on the same terms as the others.

Original question:
{{QUESTION}}

Context:
{{CONTEXT}}

Anonymized responses:
{{LETTERED_RESPONSES}}

Answer exactly these three questions. Be specific — name responses by letter and quote the load-bearing sentence where possible.

1. Which response is strongest and why?
2. Which has the biggest blind spot, and what is the blind spot?
3. What did all five miss? (This is the highest-value question. Look at the gap between the responses, not at any single one. If nothing substantive is missed, say so plainly — do not invent a gap to look insightful.)

Keep each answer to 3–6 sentences. Do not summarize the responses.
```
