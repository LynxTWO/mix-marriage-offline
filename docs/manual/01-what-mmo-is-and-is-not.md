# What MMO is and is not

MMO is an offline mixing assistant that analyzes stems in a folder and produces
engineering-grade outputs. Those outputs include technical issues, explainable
recommendations, and delivery-safe renders when you ask for them.

MMO is not a DAW plugin. You run MMO on exported stems, then apply the recall
sheet in any DAW.

MMO is not “AI that mixes your song for you.” MMO does technical math and
produces bounded, explainable suggestions. You decide the creative intent.

MMO’s promise is simple. The machine stays consistent and honest. The human
stays artistic.

What MMO can do today. It can scan and validate a stem folder. It can run meters
(basic and truth meters in the base install). It can generate a report JSON, a
CSV recall sheet, and a PDF report (PDF still requires the optional dependency).
It can render conservative outputs using `safe-render`, including render-many
targets and multiple channel-ordering standards. It can run translation checks
(phone, earbuds, car, mono collapse) when a stereo deliverable exists. It can
compute downmix matrices and QA a downmix against a reference. It can scaffold
projects, save sessions, and build GUI payload bundles. It can browse an offline
plugin marketplace and install plugins into the user plugin directory. It
includes a shipped Tauri desktop path with remaining parity work and a fallback
desktop GUI (`mmo-gui`, CustomTkinter) plus an interactive terminal UI launcher.
The CustomTkinter GUI is deprecated after Tauri parity lands.

The design constraints are intentional. Determinism prevents “works on my
machine” drift. Bounded authority prevents silent creative damage.
Ontology-first IDs prevent semantic drift across plugins and tools.
