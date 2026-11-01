# Planning-report reference cases

These are synthetic inputs with hand-authored expected report rows. No fixture
contains real parcel/owner data or depends on the live GIS database.

The minimal point, populated point and in-plan parcel cases run through both
the API routes with mocked providers and the pure `planning_reports` builders.
The populated point includes stepped FAR, an exception, all shoreline types,
protection features and nearest-EMSY presentation.

They preserve reviewed software behavior: section order, parcel versus point
references, shoreline approval and distance selection, forest-map fallback,
provisional flood labels, omitted delimitation lines, and EMSY presentation.
They do not establish that a source dataset or a legal interpretation is correct.
Arithmetic tests elsewhere preserve the current outside-plan calculation;
changes to its legal assumptions require a separate review.

When changing report behavior, review the reason and update both the synthetic
input and the expected text as needed. Do not regenerate expected files from
the implementation merely to make a failing test pass. The fixture text uses
the existing three-column pipe protocol and Windows-1253-compatible characters.
