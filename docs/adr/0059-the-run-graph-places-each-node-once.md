# 0059. The run graph places each node once, on rings around its request, and never moves it

- **Status:** Accepted
- **Date:** 2026-10-13

## Context
The run graph of Lesson 54 ([ADR 0052](0052-the-page-is-plain-html-css-and-javascript.md)) was a force simulation: nodes push each other
apart, links pull them together, and every new node starts the simulation again. Trying v0.8.0, the user found three problems: labels
overlap, the graph keeps moving, and it is cut off or doesn't fit the panel.

Measured in the browser, with a scripted run (10 requests of 6 tool calls each, a sub-agent with 4 calls in every third request, 104
nodes) in a 323 × 503 px panel:

- **It never stops moving.** With nothing happening, all 104 nodes moved within 5 seconds (by 9 units in the middle, up to 80).
- **Fitting means shrinking.** Once it settled and zoomed out to fit, the labels were 2.4 px tall on screen. In other frames they were
  readable and piled on top of each other. Because it never holds still, there is no single frame to count overlaps on.

## Options
1. **Tune the simulation**: stronger repulsion, cooling, labels that push too. It would still move every node whenever one is added, and its
   layout depends on timing, so no test can pin it down.
2. **A layout library** (dagre, ELK, d3-hierarchy). Good layouts. But it is a dependency, against the page's rule of nothing loaded from
   elsewhere (ADR 0052), and it lays the whole graph out again as it grows, which moves nodes too.
3. **A deterministic layout computed once per node**: a node's place depends only on the nodes before it, is worked out when it is added,
   and never changes.

## Decision
Option 3, in a new `harness/web/static/graph.js` (the force code is gone from `app.js`):

- **Where a node goes.** Requests sit on a timeline, left to right, each far enough from the last to clear its rings and labels. A request's
  tool calls, sub-agents and answer take numbered slots on rings around it: 8 on the first, 16 on the second and so on. The slot straight
  below is skipped, because the request's own label goes there. A sub-agent's calls ring the sub-agent. A slot is also skipped when its dot
  would cover a label or a dot already placed (a sub-agent's ring reaches into its request's).
- **Labels.** A label points away from its request, along the slot's angle (left- or right-aligned, or centred above or below). It is
  checked against everything placed so far and left out if it would overlap. The node's tooltip keeps the name.
- **The view.** **Follow** (the default) centres the newest request and its rings, never below a scale of 0.85 (labels 8.5 px or more).
  **Fit** shows the whole run, and below a scale of 0.55 the labels are hidden. The wheel zooms at the cursor and dragging pans; either one
  leaves Follow until it is clicked again. A `ResizeObserver` reframes when the panel changes size.
- **Pure and tested.** `RunLayout` has no DOM, so `tests/test_web_page.py` runs it in Node on a 202-node run. It checks that no node moves
  once placed, no two shown labels overlap, no dot covers another node's label, nodes keep their distance, the result is the same every
  time, and Fit's box holds every node.

The same run in the browser afterwards:

| | v0.8.0 (force) | now |
|---|---|---|
| nodes that moved after they appeared | all, continually (104 of 104 in 5 s, idle) | 0 |
| labels shown | 104 (piled up or unreadably small) | 104 |
| labels overlapping a label or another node's dot | (never still long enough to count) | 0 |
| label size on screen | 2.4 px once settled | 8.5 px (Follow) |
| nodes inside the view | all, at 2.4 px labels | all (Fit); the newest request (Follow) |

Two bugs were found by measuring in the browser, not by the Node tests. `.node text { text-anchor: middle }` in `app.css` overrode the
`text-anchor` attribute the layout sets (CSS beats SVG presentation attributes), so left- and right-aligned labels were drawn centred, 12
units from where they had been checked. And a sub-agent's call could land on its sub-agent's label. Both have tests now: the stylesheet may
not set `text-anchor`, and the layout test checks dots against labels.

## Consequences
- What you see stays where it is: a node you were looking at is in the same place after the next ten requests.
- A long run is wide. In a narrow panel Fit is an overview of dots (10 requests: scale 0.11); Follow, zoom and pan are for reading. Wrapping
  the timeline into rows would use a tall panel better, but a row break depends on the panel's width, and a resize would then move nodes.
- In a narrow panel, Follow's floor means a big request doesn't fit. At 323 px the view is 380 units wide, so the second ring (from the
  8th call on, radius 110) is in view, but its longest labels run past the edge. Fit or dragging shows them.
- The page keeps at most 400 nodes; the oldest are removed first, and the layout doesn't reuse their places.
