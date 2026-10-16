# FaultLens UI design notes

The operator UI is a Streamlit app, but it is styled as a purpose-built console rather than
default Streamlit. This file records the intent, the tokens, and the reasoning so the design
survives the next change.

## Thesis

> At a glance, how is this unit, and on demand, what is wrong, why, and what to do first.

Audience: a shift technician at a power station and, second, a reliability engineer. The screen is
read in a control room, sometimes on a projector, often while something else is happening. So the
working principle is **calm, high-signal, and quiet until it matters**.

## The signature

One reserved status colour drives the whole health story:

- a **severity spine** (a 4 px left edge on the health cluster) and a status dot,
- tinted banners for escalation,
- and nothing else in the product uses green, amber, or red.

Everything else is monochrome plus a single technical accent (teal) so that when the screen turns
amber or red, it is unambiguous and instantly readable. Charts are deliberately uniform: every
sensor trend is the same teal line so the *data* carries the message, not decoration.

## Tokens

Contrast figures are computed, not estimated (WCAG 2.1, against the surface the text sits on).

**Colour**

| Role | Value | On | Contrast |
|---|---|---|---|
| Canvas | `#F1F4F8` | — | — |
| Surface (cards) | `#FFFFFF` | — | — |
| Ink (primary text) | `#0F172A` | white | 17.6:1 |
| Ink-2 (secondary) | `#475569` | white | 7.5:1 |
| Ink-3 (muted labels) | `#64748B` | white | 5.0:1 |
| Accent (brand / primary action) | `#0E7490` | white | 5.2:1 |
| Status · normal | `#15803D` | tint `#ECFDF3` | 4.6:1 |
| Status · warning | `#B45309` | tint `#FFF7ED` | 4.9:1 |
| Status · critical | `#B91C1C` | tint `#FEF2F2` | 5.9:1 |

The accent is teal, not the green/amber/red family, so brand and status never compete
(`color.md › Best practices`: "Avoid using the same color to mean different things").

**Type** — one family for the interface (system stack; `typography.md › Using system fonts`),
one monospace for identifiers and codes. Scale: 11 px uppercase eyebrows, 12–13 px secondary,
14 px body, 15.5 px summary, 29 px metric values, 30 px page title. All figures use `tabular-nums`
so columns of numbers line up. Nothing sits below 11 px; no light weights
(`typography.md › Ensuring legibility`).

**Layout** — a single 1240 px column: brand bar, page head, a three-cell health cluster, a row of
sensor cards, the diagnose action, then the report. Cards are white on the graphite canvas with a
1 px `#E3E8EF` hairline and a 14 px radius. Hierarchy comes from weight, size, and spacing, not
from boxes or rules.

## What changed, and why

The original screen was default Streamlit: an uncoloured "WARNING" heading, generic blue charts,
and a flat stack of elements with no hierarchy.

| Finding | Severity | Change |
|---|---|---|
| Status shown in plain black text; health not glanceable | Critical | Severity spine + coloured status word + dot. Status is now the loudest thing on screen, and it is the only thing using the status colours. |
| Direction conveyed by the word only; small deltas lost | Medium | Each sensor card shows an arrow, the signed delta, and the anomaly z together (`color.md › Inclusive color`: never signal by colour alone). |
| Charts were inconsistent and decorative | Medium | One chart type, one colour, no chart junk, shared axes language (`charting-data.md › Designing effective charts`). |
| No empty state; a disabled button with no explanation | Low | A calm "within its healthy pattern" state explains the silence and the next step (`writing.md › Best practices`: "Provide clear next steps on any blank screens"). |
| Causes, actions, evidence and the work order were one undifferentiated wall | High | Typed cards: cause + likelihood + citation pills, ordered actions with priority, the work order separated and clearly labelled "needs approval". |
| The human-approval gate was easy to miss | High | The work order is a bordered card under an eyebrow that says it needs approval, with the approver field required before the button enables. |
| Insufficient contrast on secondary text | Medium | Secondary and muted greys raised to 7.5:1 and 5.0:1. |
| An icon font was being clobbered by a global font override | Critical (regression) | Font rule scoped so Material Symbols keep their own face. |

## Quality floor

- **Colour never carries meaning alone**: status always has a word, direction always has an arrow
  and a number, priority always has a label.
- **Contrast**: every text token meets 4.5:1; status words are large and bold on top of that.
- **Motion**: only a 180 ms colour transition on the health cluster, disabled under
  `prefers-reduced-motion`.
- **Narrow widths**: the health cluster stacks and the page title steps down below 900 px.
- **Wording**: action-oriented buttons ("Diagnose", "Approve and raise work order"), sentence-case
  body, uppercase micro-labels, one name per action carried through the flow
  (`writing.md › Best practices`).
- **Branding defers to content**: the mark appears once, small, in the brand bar; the accent is
  spent only on the primary action and the charts (`branding.md › Best practices`).

## Platform note (framework)

This is a web app, so Apple platform conventions (tab bars, sheets, the menu bar) do not apply.
The foundations do: colour, contrast, type legibility and scale, visual hierarchy, status feedback,
and copy. Streamlit's own components are kept where they exist and restyled, rather than replaced,
so familiar behaviour (sliders, selects, expanders, keyboard focus) keeps working.
