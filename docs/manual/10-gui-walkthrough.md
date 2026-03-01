# Desktop GUI walkthrough (v1.1)

The GUI exists to reduce friction, not to hide the truth.
It wraps the same CLI behaviors and keeps receipts.

Launch the GUI.
mmo-gui
(Or run: python -m mmo.gui.main)

What the GUI is good for today.
Point-and-click stem selection.
Render target selection, including render-many defaults.
Layout standard selection.
Headphone preview toggle.
Offline plugin marketplace browsing and installation.
Deterministic visualization dashboard surfaces (spectrum, vectorscope, correlation risk, layout projection, intent cards).

Recommended GUI flow.
1) Choose your stems folder.
2) Choose your output folder.
3) Pick your target, or enable render-many.
4) Choose the layout standard you need for delivery.
5) Run the pipeline.
6) Review issues and receipts.
7) Export deliverables.

Pro notes.
GUI screenshots in this manual are placeholders until the repo includes an automated screenshot harness.
The GUI is deterministic in its computed visualization frames when telemetry inputs are identical.
If you need a zero-ambiguity workflow today, use CLI runs and open the artifacts the GUI points to.